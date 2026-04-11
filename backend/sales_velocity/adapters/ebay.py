"""
eBay adapter for sales_velocity.

Ported in pattern (not copy-pasted) from `D:\\render\\ebay_auth.py`. eBay
OAuth2 uses Basic auth at the token endpoint, 2-hour access tokens, and
18-month refresh tokens. Scopes required: `sell.fulfillment` (reads
orders via `/sell/fulfillment/v1/order`).

Architecture:
- Credentials (`EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `EBAY_RU_NAME`,
  `EBAY_ENVIRONMENT`) come from env vars / settings. Not on the DB
  model, so rotating the dev-app credentials doesn't need a migration.
- Refresh token + access token + expiry live on
  `sales_velocity.OAuthCredential(provider='ebay')`, one row per
  environment.
- First-time setup: Toby visits `/admin/oauth/ebay/connect` once,
  consents in a browser, eBay redirects to `/admin/oauth/ebay/callback`
  with an authorization code, the callback exchanges it for tokens
  and writes them to the DB. See `sales_velocity/views_oauth.py`.
- Every API call checks token expiry (`within_5_min_of_expiry`) and
  refreshes in-place, holding a `SELECT FOR UPDATE` lock to avoid
  the qcluster+web race.

PII scrub: eBay returns buyer name, email, shipping address, and
transaction-level pricing. We whitelist only SKU / quantity / line
identifiers / order creation date.
"""
from __future__ import annotations

import base64
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone as django_tz

from sales_velocity.adapters import (
    ChannelAdapter,
    NormalisedOrderLine,
    ensure_utc,
)
from sales_velocity.models import OAuthCredential

logger = logging.getLogger(__name__)


# ── OAuth endpoint map ───────────────────────────────────────────────────────

EBAY_OAUTH_URLS: dict[str, dict[str, str]] = {
    'sandbox': {
        'auth': 'https://auth.sandbox.ebay.com/oauth2/authorize',
        'token': 'https://api.sandbox.ebay.com/identity/v1/oauth2/token',
        'api_base': 'https://api.sandbox.ebay.com',
    },
    'production': {
        'auth': 'https://auth.ebay.com/oauth2/authorize',
        'token': 'https://api.ebay.com/identity/v1/oauth2/token',
        'api_base': 'https://api.ebay.com',
    },
}

# Required scopes — same set as render's ebay_auth.py. sell.fulfillment
# is the one we actually need for /sell/fulfillment/v1/order.
EBAY_SCOPES: list[str] = [
    'https://api.ebay.com/oauth/api_scope',
    'https://api.ebay.com/oauth/api_scope/sell.inventory',
    'https://api.ebay.com/oauth/api_scope/sell.account',
    'https://api.ebay.com/oauth/api_scope/sell.fulfillment',
    'https://api.ebay.com/oauth/api_scope/sell.marketing',
]

# eBay getOrders endpoint returns up to 200 per page. filter=... is a
# URL-encoded string selecting by creationdate and orderfulfillmentstatus.
MAX_ORDERS_PER_PAGE = 200

# Refresh when access token is within this many seconds of expiry.
TOKEN_REFRESH_BUFFER_SECONDS = 300  # 5 minutes


# ── PII whitelist ────────────────────────────────────────────────────────────

_ORDER_WHITELIST: frozenset[str] = frozenset({
    'orderId', 'legacyOrderId', 'creationDate', 'lastModifiedDate',
    'orderFulfillmentStatus', 'orderPaymentStatus', 'sellerId',
})

_LINE_ITEM_WHITELIST: frozenset[str] = frozenset({
    'lineItemId', 'legacyItemId', 'sku', 'title',
    'quantity', 'lineItemFulfillmentStatus',
})


def _whitelist(payload: Any) -> Any:
    """Recursive whitelist scrub for eBay order responses."""
    if payload is None:
        return None
    if isinstance(payload, list):
        return [_whitelist(x) for x in payload]
    if not isinstance(payload, dict):
        return payload

    out: dict[str, Any] = {}
    for k, v in payload.items():
        if k == 'orders':
            out[k] = [
                {
                    ok: (
                        _whitelist_line_items(ov) if ok == 'lineItems'
                        else ov
                    )
                    for ok, ov in (o or {}).items()
                    if ok in _ORDER_WHITELIST or ok == 'lineItems'
                }
                for o in (v or [])
            ]
        elif k in {'href', 'next', 'prev', 'limit', 'offset', 'total'}:
            # Pagination metadata is safe.
            out[k] = v
        elif k in _ORDER_WHITELIST:
            out[k] = v
    return out


def _whitelist_line_items(items: Any) -> Any:
    if not isinstance(items, list):
        return []
    return [
        {k: v for k, v in (i or {}).items() if k in _LINE_ITEM_WHITELIST}
        for i in items
    ]


# ── Adapter ──────────────────────────────────────────────────────────────────

class EbayAdapter(ChannelAdapter):
    """
    Native OAuth adapter for eBay Sell Fulfillment API.

    Stateless across runs — on every `fetch_orders` call, it:
    1. Looks up the eBay OAuthCredential row (created by the one-time
       consent flow), refreshing the access token if within 5 min of
       expiry (holds SELECT FOR UPDATE during refresh to avoid races).
    2. Paginates GET /sell/fulfillment/v1/order with a creationdate
       filter.
    3. Emits one NormalisedOrderLine per lineItem with positive
       quantity.
    """

    channel = 'ebay'
    HTTP_TIMEOUT_SECONDS = 30.0

    def __init__(
        self,
        *,
        _http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__()
        self._http_client = _http_client

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def fetch_orders(
        self,
        start_date: date,
        end_date: date,
    ) -> list[NormalisedOrderLine]:
        access_token = self._get_valid_access_token()
        env = (getattr(settings, 'EBAY_ENVIRONMENT', 'production') or 'production').lower()
        api_base = EBAY_OAUTH_URLS[env]['api_base']

        start_dt = datetime.combine(
            start_date, datetime.min.time(), tzinfo=timezone.utc,
        )
        end_dt = datetime.combine(
            end_date, datetime.max.time(), tzinfo=timezone.utc,
        )

        # eBay filter syntax: creationdate:[2026-03-12T00:00:00.000Z..2026-04-11T23:59:59.999Z]
        filter_str = (
            f'creationdate:[{start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")}'
            f'..{end_dt.strftime("%Y-%m-%dT%H:%M:%S.999Z")}]'
            ',orderfulfillmentstatus:{FULFILLED|IN_PROGRESS}'
        )

        lines: list[NormalisedOrderLine] = []
        url: str | None = (
            f'{api_base}/sell/fulfillment/v1/order?'
            f'filter={filter_str}&limit={MAX_ORDERS_PER_PAGE}'
        )
        page_count = 0
        while url:
            page_count += 1
            payload = self._call_get_orders(url, access_token)
            orders = (payload or {}).get('orders', []) or []
            for order in orders:
                creation_date = ensure_utc(order.get('creationDate'))
                if creation_date is None:
                    continue
                for line_item in order.get('lineItems', []) or []:
                    sku = line_item.get('sku')
                    qty = line_item.get('quantity', 0)
                    try:
                        qty = int(qty)
                    except (TypeError, ValueError):
                        qty = 0
                    if not sku or qty <= 0:
                        continue
                    lines.append(NormalisedOrderLine(
                        external_sku=sku,
                        quantity=qty,
                        sale_date=creation_date,
                        raw_data={
                            'order_id': order.get('orderId'),
                            'legacy_order_id': order.get('legacyOrderId'),
                            'line_item_id': line_item.get('lineItemId'),
                            'fulfillment_status': order.get('orderFulfillmentStatus'),
                        },
                    ))
            # Follow pagination link; eBay returns `next` as an absolute URL.
            url = (payload or {}).get('next')

        logger.info(
            'EbayAdapter: %d pages, %d line items',
            page_count, len(lines),
        )
        return lines

    # ------------------------------------------------------------------ #
    # Token management                                                   #
    # ------------------------------------------------------------------ #

    def _get_valid_access_token(self) -> str:
        """
        Fetch a valid access token from the OAuthCredential row,
        refreshing in-place if it's within the expiry buffer. Holds
        a SELECT FOR UPDATE lock for the duration so concurrent
        qcluster + web calls don't race the refresh endpoint.

        If refresh fails (revoked token, bad credentials), the cleared
        tokens are committed via the atomic block and the original
        exception is re-raised AFTER the commit so the blanking
        survives. Raising inside the atomic block would roll the save
        back, which is the opposite of what we want — we need the
        cleared state persisted so the UI's red "reauth required"
        pill surfaces on the next request.
        """
        refresh_error: Exception | None = None
        access_token = ''
        with transaction.atomic():
            try:
                cred = OAuthCredential.objects.select_for_update().get(provider='ebay')
            except OAuthCredential.DoesNotExist as exc:
                raise RuntimeError(
                    'eBay OAuthCredential row does not exist. Complete the '
                    'one-time consent flow at /admin/oauth/ebay/connect '
                    'before running the aggregator.'
                ) from exc

            now = django_tz.now()
            needs_refresh = (
                not cred.access_token
                or cred.access_token_expires_at is None
                or cred.access_token_expires_at
                   <= now + timedelta(seconds=TOKEN_REFRESH_BUFFER_SECONDS)
            )
            if needs_refresh:
                try:
                    self._refresh_access_token(cred)
                except Exception as exc:
                    # Hold onto the exception so the atomic block can
                    # commit the cleared-token save, then re-raise below.
                    refresh_error = exc
            access_token = cred.access_token
        if refresh_error is not None:
            raise refresh_error
        return access_token

    def _refresh_access_token(self, cred: OAuthCredential) -> None:
        """
        POST /identity/v1/oauth2/token with grant_type=refresh_token.
        Updates the row in-place. Called inside the SELECT FOR UPDATE
        block so the write is serialised.
        """
        env = (getattr(settings, 'EBAY_ENVIRONMENT', 'production') or 'production').lower()
        token_url = EBAY_OAUTH_URLS[env]['token']
        client_id = getattr(settings, 'EBAY_CLIENT_ID', '')
        client_secret = getattr(settings, 'EBAY_CLIENT_SECRET', '')
        if not client_id or not client_secret:
            raise RuntimeError(
                'EBAY_CLIENT_ID / EBAY_CLIENT_SECRET must be set in '
                'manufacture .env before the eBay adapter can refresh tokens.'
            )

        basic = base64.b64encode(
            f'{client_id}:{client_secret}'.encode()
        ).decode()
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {basic}',
        }
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': cred.refresh_token,
            'scope': ' '.join(EBAY_SCOPES),
        }

        with self._time_call() as timer:
            try:
                client = self._http_client or httpx.Client(
                    timeout=self.HTTP_TIMEOUT_SECONDS,
                )
                owns_client = self._http_client is None
                try:
                    response = client.post(token_url, headers=headers, data=data)
                finally:
                    if owns_client:
                        client.close()
            except httpx.HTTPError as exc:
                self._log_api_call(
                    endpoint='POST /identity/v1/oauth2/token',
                    request_params={'grant_type': 'refresh_token'},
                    response_status=None,
                    response_body=None,
                    duration_ms=timer.ms,
                    error_message=f'{type(exc).__name__}: {exc}',
                )
                raise

        if response.status_code != 200:
            self._log_api_call(
                endpoint='POST /identity/v1/oauth2/token',
                request_params={'grant_type': 'refresh_token'},
                response_status=response.status_code,
                response_body=None,
                duration_ms=timer.ms,
                error_message=f'HTTP {response.status_code}: {response.text[:500]}',
            )
            # eBay 400 on refresh usually means the refresh token was
            # revoked or expired. Blank the access token so a subsequent
            # run surfaces the problem via the Sales Velocity tab's red
            # eBay-reauth pill. Don't delete the row — keep it for the
            # admin reconnect flow to update.
            cred.access_token = ''
            cred.access_token_expires_at = None
            cred.save(update_fields=['access_token', 'access_token_expires_at'])
            response.raise_for_status()

        token_data = response.json()
        cred.access_token = token_data['access_token']
        cred.access_token_expires_at = django_tz.now() + timedelta(
            seconds=int(token_data.get('expires_in', 7200)),
        )
        cred.last_refreshed_at = django_tz.now()
        # eBay may rotate the refresh token — use the new one if present.
        new_refresh = token_data.get('refresh_token')
        if new_refresh:
            cred.refresh_token = new_refresh
        cred.save(update_fields=[
            'access_token', 'access_token_expires_at',
            'last_refreshed_at', 'refresh_token',
        ])

        self._log_api_call(
            endpoint='POST /identity/v1/oauth2/token',
            request_params={'grant_type': 'refresh_token'},
            response_status=200,
            response_body={'expires_in': token_data.get('expires_in')},
            duration_ms=0,
            error_message='',
        )

    # ------------------------------------------------------------------ #
    # API calls                                                          #
    # ------------------------------------------------------------------ #

    def _call_get_orders(self, url: str, access_token: str) -> Any:
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
        }
        with self._time_call() as timer:
            try:
                client = self._http_client or httpx.Client(
                    timeout=self.HTTP_TIMEOUT_SECONDS,
                )
                owns_client = self._http_client is None
                try:
                    response = client.get(url, headers=headers)
                finally:
                    if owns_client:
                        client.close()
            except httpx.HTTPError as exc:
                self._log_api_call(
                    endpoint='GET /sell/fulfillment/v1/order',
                    request_params={'url': url[:200]},
                    response_status=None,
                    response_body=None,
                    duration_ms=timer.ms,
                    error_message=f'{type(exc).__name__}: {exc}',
                )
                raise

        if response.status_code != 200:
            self._log_api_call(
                endpoint='GET /sell/fulfillment/v1/order',
                request_params={'url': url[:200]},
                response_status=response.status_code,
                response_body=None,
                duration_ms=timer.ms,
                error_message=f'HTTP {response.status_code}: {response.text[:500]}',
            )
            response.raise_for_status()

        payload = response.json()
        self._log_api_call(
            endpoint='GET /sell/fulfillment/v1/order',
            request_params={'url': url[:200]},
            response_status=200,
            response_body=payload,
            duration_ms=timer.ms,
            error_message='',
        )
        return payload

    # ------------------------------------------------------------------ #
    # PII scrub (overrides ABC default)                                  #
    # ------------------------------------------------------------------ #

    def scrub_response_body(self, response_body: Any) -> Any:
        return _whitelist(response_body)


__all__ = ['EbayAdapter', 'EBAY_OAUTH_URLS', 'EBAY_SCOPES']
