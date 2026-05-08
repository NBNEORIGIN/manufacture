"""
eBay adapter for sales_velocity.

**This adapter does NOT touch eBay directly.** Following the same pattern
as Etsy (see `etsy.py`), eBay OAuth + ingestion now live in Deek/Cairn.
Manufacture reads sales over HTTP via Cairn's `GET /ebay/sales` endpoint.

Cairn shipped this on 2026-05-08 (commit `4f40a1a`). Cairn owns:
- The `ebay_oauth_tokens` row + auto-refresh lifecycle
- The `ebay_sales` / `ebay_listings` Postgres tables
- The Sell Fulfillment API calls
- VAT handling, fee model, m_number resolution, GBP conversion

Manufacture's only job here is to pull pre-ingested per-line sales over
HTTP and emit one `NormalisedOrderLine` per sale.

History: this adapter previously held the full OAuth + pagination logic
(see `D:\\render\\ebay_auth.py` for the original pattern). All of that
moved to Deek alongside the Etsy migration. The Manufacture-side
`OAuthCredential(provider='ebay')` row is left in place as a one-line
revert path until ~7 days of clean Deek-sourced runs prove the cutover.

`EBAY_OAUTH_URLS` and `EBAY_SCOPES` are retained at module level because
`sales_velocity/views_oauth.py` still imports them for the legacy
admin-side connect/callback flow. Once that flow is retired (after the
Deek-side OAuth has been stable in production), both constants can be
deleted with the views_oauth eBay routes.

Architecture rule: cross-module direct DB access is forbidden
(`D:\\claw\\CLAUDE.md`). HTTP only.

Failure modes:
- Cairn unreachable (network, down for deploy, etc.): the aggregator
  logs the failure to SalesVelocityAPICall and skips the eBay leg
  for this run. Other channels proceed. No retries within the same
  run — the next daily tick picks it up.
- Cairn returns rows whose SKU isn't in the canonical Stock Sheet:
  rendered as cost_source='missing' / confidence='LOW' upstream and
  skipped here when the SKU is empty.

PII whitelist: Cairn's `/ebay/sales` response strips buyer name / email
/ address before transit (only ISO `buyer_country` is exposed for VAT
attribution). The whitelist below is conservative — defensive against
future endpoint additions.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import httpx
from django.conf import settings

from sales_velocity.adapters import (
    ChannelAdapter,
    NormalisedOrderLine,
    ensure_utc,
)

logger = logging.getLogger(__name__)


# ── Legacy constants — retained for views_oauth.py imports only ─────────────

# These powered the original Manufacture-side OAuth consent flow. The
# adapter doesn't use them any more; Deek does. Will be removed once the
# views_oauth.py eBay routes are retired.

EBAY_OAUTH_URLS: dict[str, dict[str, str]] = {
    'sandbox': {
        'auth':     'https://auth.sandbox.ebay.com/oauth2/authorize',
        'token':    'https://api.sandbox.ebay.com/identity/v1/oauth2/token',
        'api_base': 'https://api.sandbox.ebay.com',
    },
    'production': {
        'auth':     'https://auth.ebay.com/oauth2/authorize',
        'token':    'https://api.ebay.com/identity/v1/oauth2/token',
        'api_base': 'https://api.ebay.com',
    },
}

EBAY_SCOPES: list[str] = [
    'https://api.ebay.com/oauth/api_scope',
    'https://api.ebay.com/oauth/api_scope/sell.inventory',
    'https://api.ebay.com/oauth/api_scope/sell.account',
    'https://api.ebay.com/oauth/api_scope/sell.fulfillment',
    'https://api.ebay.com/oauth/api_scope/sell.marketing',
]


# ── PII whitelist — applied to Cairn responses before audit logging ────────

# Cairn's /ebay/sales response is already PII-stripped at the source.
# This whitelist defends against future endpoint additions: anything
# we don't explicitly recognise is dropped from the audit log payload.

_SALE_WHITELIST: frozenset[str] = frozenset({
    'order_id', 'legacy_order_id', 'line_item_id', 'item_id',
    'sku', 'quantity', 'unit_price', 'total_price', 'shipping_cost',
    'total_paid', 'fees', 'currency', 'buyer_country',
    'fulfillment_status', 'payment_status', 'sale_date',
})

_TOP_WHITELIST: frozenset[str] = frozenset({
    'count', 'days_back', 'sales',
})


class EbayAdapter(ChannelAdapter):
    """
    Thin HTTP wrapper over Cairn's /ebay/sales endpoint.

    Each row in the response is one (order_id, line_item_id) pair from
    `ebay_sales` — one NormalisedOrderLine per row. No client-side
    aggregation, no OAuth handling, no pagination.

    Roughly the same shape as EtsyAdapter, with two differences:
    - /ebay/sales returns transaction-level rows (not pre-aggregated)
    - The window param is `days_back` (eBay convention) not `days` (Etsy)
    """

    channel = 'ebay'
    HTTP_TIMEOUT_SECONDS = 30.0

    def __init__(
        self,
        *,
        _http_client: httpx.Client | None = None,
    ) -> None:
        """
        Args:
            _http_client: test-injection hook. Tests pass a mocked
                httpx.Client to avoid real network calls.
        """
        super().__init__()
        self._http_client = _http_client

    def fetch_orders(
        self,
        start_date: date,
        end_date: date,
    ) -> list[NormalisedOrderLine]:
        """
        Calls Cairn /ebay/sales?days_back=N and converts the per-line
        rows into NormalisedOrderLine records.

        Cairn returns ONE row per (order_id, line_item_id) — already
        flattened from eBay's nested order/lineItems structure. Each
        carries sku, quantity, sale_date, and pricing metadata.
        """
        base_url = getattr(settings, 'CAIRN_API_URL', '') or 'http://localhost:8765'
        api_key = getattr(settings, 'CAIRN_API_KEY', '')
        # Inclusive range: end - start + 1 days. Floor at 1 to handle
        # same-day calls (the Cairn endpoint rejects days_back<1).
        days_back = max(1, (end_date - start_date).days + 1)

        url = f'{base_url.rstrip("/")}/ebay/sales'
        params = {'days_back': days_back}
        headers = {'X-API-Key': api_key} if api_key else {}

        with self._time_call() as timer:
            try:
                client = self._http_client or httpx.Client(
                    timeout=self.HTTP_TIMEOUT_SECONDS,
                )
                owns_client = self._http_client is None
                try:
                    response = client.get(url, params=params, headers=headers)
                finally:
                    if owns_client:
                        client.close()
            except httpx.HTTPError as exc:
                self._log_api_call(
                    endpoint='GET /ebay/sales',
                    request_params={'days_back': days_back},
                    response_status=None,
                    response_body=None,
                    duration_ms=timer.ms,
                    error_message=f'{type(exc).__name__}: {exc}',
                )
                logger.error(
                    'EbayAdapter: Cairn unreachable (%s) — skipping eBay leg '
                    'for this run',
                    exc,
                )
                # Re-raise so the aggregator records a channel failure.
                raise

        if response.status_code != 200:
            self._log_api_call(
                endpoint='GET /ebay/sales',
                request_params={'days_back': days_back},
                response_status=response.status_code,
                response_body=None,
                duration_ms=timer.ms,
                error_message=f'HTTP {response.status_code}: {response.text[:500]}',
            )
            response.raise_for_status()  # raises httpx.HTTPStatusError

        payload = response.json()
        self._log_api_call(
            endpoint='GET /ebay/sales',
            request_params={'days_back': days_back},
            response_status=200,
            response_body=payload,
            duration_ms=timer.ms,
            error_message='',
        )

        lines: list[NormalisedOrderLine] = []
        for row in payload.get('sales', []) or []:
            sku = row.get('sku')
            qty_raw = row.get('quantity', 0)
            try:
                qty = int(qty_raw or 0)
            except (TypeError, ValueError):
                qty = 0
            if not sku or qty <= 0:
                continue

            sale_date = ensure_utc(row.get('sale_date'))
            if sale_date is None:
                # Cairn always populates sale_date; falling back to the
                # window end keeps the aggregator from crashing on a row
                # with bad data, but logs as a warning.
                logger.warning(
                    'EbayAdapter: row missing sale_date — using end_date as fallback. '
                    'order_id=%s line_item_id=%s',
                    row.get('order_id'), row.get('line_item_id'),
                )
                sale_date = datetime.combine(
                    end_date, datetime.min.time(), tzinfo=timezone.utc,
                )

            lines.append(NormalisedOrderLine(
                external_sku=sku,
                quantity=qty,
                sale_date=sale_date,
                raw_data={
                    'order_id':           row.get('order_id'),
                    'legacy_order_id':    row.get('legacy_order_id'),
                    'line_item_id':       row.get('line_item_id'),
                    'item_id':            row.get('item_id'),
                    'fulfillment_status': row.get('fulfillment_status'),
                    'total_paid':         row.get('total_paid'),
                    'currency':           row.get('currency', 'GBP'),
                    'buyer_country':      row.get('buyer_country'),
                },
            ))

        logger.info(
            'EbayAdapter: %d sales rows from Cairn -> %d NormalisedOrderLines',
            payload.get('count', 0), len(lines),
        )
        return lines

    def scrub_response_body(self, response_body: Any) -> Any:
        """
        Whitelist-only scrub. Cairn's /ebay/sales payload contains no PII
        (buyer name/email/address are stripped at source — only ISO
        `buyer_country` is exposed for VAT) but we still default-deny
        unknown keys in case the endpoint grows.
        """
        if not isinstance(response_body, dict):
            return None
        out: dict[str, Any] = {}
        for k, v in response_body.items():
            if k not in _TOP_WHITELIST:
                continue
            if k == 'sales':
                out[k] = [
                    {sk: sv for sk, sv in (s or {}).items() if sk in _SALE_WHITELIST}
                    for s in (v or [])
                ]
            else:
                out[k] = v
        return out


__all__ = ['EbayAdapter', 'EBAY_OAUTH_URLS', 'EBAY_SCOPES']
