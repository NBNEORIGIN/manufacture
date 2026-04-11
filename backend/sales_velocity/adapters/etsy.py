"""
Etsy adapter for sales_velocity.

**This adapter does NOT touch Etsy directly.** Etsy OAuth lives in Cairn
(`D:\\claw\\core\\etsy_intel\\`) and Cairn syncs receipts to its
`etsy_sales` Postgres table daily. Manufacture reads the aggregated
window via Cairn's `GET /etsy/sales?days=N` endpoint, which was added
in Phase 2B.0(a) on the Cairn branch `feat/etsy-sales-endpoint`
(NBNEORIGIN/cairn#7). The endpoint is authenticated with
`X-API-Key: $CLAW_API_KEY`.

Architecture rule: cross-module direct DB access is forbidden
(`D:\\claw\\CLAUDE.md`). That's why we go over HTTP, not SQL.

Failure modes:
- Cairn unreachable (network, down for deploy, etc.): the aggregator
  logs the failure to SalesVelocityAPICall and skips the Etsy leg
  for this run. Other channels proceed. No retries within the same
  run — the next daily tick picks it up.
- Cairn reports skipped_multi_sku > 0: indicates a data-quality
  regression upstream. We log a warning and still include the clean
  rows we did get back.
- shop_id_filter is not set at the adapter level — Cairn defaults to
  "all configured shops". NBNE's Copper Bracelets Shop is excluded
  from M-numbered products per the brief, so either (a) Cairn's
  ETSY_SHOP_IDS already scopes to NBNE Print and Sign, or (b)
  Copper Bracelets listings have no SKUs that match any Product in
  manufacture and will silently fall through as UnmatchedSKU entries.
  Both outcomes are safe.
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


# PII whitelist for scrubbed audit rows. Cairn's /etsy/sales response
# already has no PII (it's pre-aggregated by listing_id with only sku,
# quantity, and date fields), so the whitelist is conservative.
_ROW_WHITELIST: frozenset[str] = frozenset({
    'shop_id', 'listing_id', 'external_sku', 'total_quantity',
    'first_sale_date', 'last_sale_date',
})

_TOP_WHITELIST: frozenset[str] = frozenset({
    'rows', 'window_days', 'window_end', 'shop_id_filter',
    'row_count', 'skipped_null_sku', 'skipped_multi_sku',
})


class EtsyAdapter(ChannelAdapter):
    """
    Thin HTTP wrapper over Cairn's /etsy/sales endpoint.

    No OAuth state, no token refresh, no Etsy API endpoints — Cairn
    owns that lifecycle entirely. ~40 lines of real logic plus audit
    logging and defensive error handling.
    """

    channel = 'etsy'
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
        Calls Cairn /etsy/sales?days=N and converts the aggregated
        per-listing rows into NormalisedOrderLine records.

        Note that Cairn returns ONE row per (shop, listing) with the
        summed quantity for the window — not one row per transaction.
        This is deliberate: manufacture's aggregator only needs
        per-channel-per-product totals, so pre-aggregating at the SQL
        layer saves wire weight. We emit ONE NormalisedOrderLine per
        Cairn row, with sale_date set to the window's last_sale_date
        (which is what matters for "did this listing move recently").
        """
        base_url = getattr(settings, 'CAIRN_API_URL', '') or 'http://localhost:8765'
        api_key = getattr(settings, 'CAIRN_API_KEY', '')
        days = max(1, (end_date - start_date).days + 1)

        url = f'{base_url.rstrip("/")}/etsy/sales'
        params = {'days': days}
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
                    endpoint='GET /etsy/sales',
                    request_params={'days': days},
                    response_status=None,
                    response_body=None,
                    duration_ms=timer.ms,
                    error_message=f'{type(exc).__name__}: {exc}',
                )
                logger.error(
                    'EtsyAdapter: Cairn unreachable (%s) — skipping Etsy leg '
                    'for this run',
                    exc,
                )
                # Re-raise so the aggregator records a channel failure.
                raise

        if response.status_code != 200:
            self._log_api_call(
                endpoint='GET /etsy/sales',
                request_params={'days': days},
                response_status=response.status_code,
                response_body=None,
                duration_ms=timer.ms,
                error_message=f'HTTP {response.status_code}: {response.text[:500]}',
            )
            response.raise_for_status()  # raises httpx.HTTPStatusError

        payload = response.json()
        self._log_api_call(
            endpoint='GET /etsy/sales',
            request_params={'days': days},
            response_status=200,
            response_body=payload,
            duration_ms=timer.ms,
            error_message='',
        )

        skipped_multi_sku = payload.get('skipped_multi_sku', 0)
        if skipped_multi_sku:
            logger.warning(
                'EtsyAdapter: Cairn reported skipped_multi_sku=%d — '
                'data-quality regression upstream. Affected listings were '
                'excluded from this run.',
                skipped_multi_sku,
            )

        lines: list[NormalisedOrderLine] = []
        for row in payload.get('rows', []) or []:
            sku = row.get('external_sku')
            qty = row.get('total_quantity', 0)
            if not sku or not qty or qty <= 0:
                continue
            last_sale = ensure_utc(row.get('last_sale_date'))
            if last_sale is None:
                last_sale = datetime.combine(
                    end_date, datetime.min.time(), tzinfo=timezone.utc,
                )
            lines.append(NormalisedOrderLine(
                external_sku=sku,
                quantity=int(qty),
                sale_date=last_sale,
                raw_data={
                    'cairn_row': {k: v for k, v in row.items() if k in _ROW_WHITELIST},
                    'shop_id': row.get('shop_id'),
                    'listing_id': row.get('listing_id'),
                },
            ))

        logger.info(
            'EtsyAdapter: %d rows from Cairn -> %d NormalisedOrderLines '
            '(skipped_null_sku=%d, skipped_multi_sku=%d)',
            payload.get('row_count', 0), len(lines),
            payload.get('skipped_null_sku', 0),
            skipped_multi_sku,
        )
        return lines

    def scrub_response_body(self, response_body: Any) -> Any:
        """
        Whitelist-only scrub. Cairn's /etsy/sales payload contains no PII
        but we still default-deny unknown keys in case the endpoint grows.
        """
        if not isinstance(response_body, dict):
            return None
        out: dict[str, Any] = {}
        for k, v in response_body.items():
            if k not in _TOP_WHITELIST:
                continue
            if k == 'rows':
                out[k] = [
                    {rk: rv for rk, rv in (r or {}).items() if rk in _ROW_WHITELIST}
                    for r in (v or [])
                ]
            else:
                out[k] = v
        return out


__all__ = ['EtsyAdapter']
