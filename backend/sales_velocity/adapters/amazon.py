"""
Amazon adapter for the sales_velocity module.

Uses the same python-amazon-sp-api library as
`fba_shipments.services.sp_api_client` but for the Orders API (OrdersV0)
rather than FulfillmentInboundV20240320. One `AmazonAdapter` instance
per marketplace; the `build_all_amazon_adapters()` factory returns all
9 in use: UK, US, CA, AU, DE, FR, ES, NL, IT.

Library inspection (2026-04-11, python-amazon-sp-api installed at
D:\\manufacture\\.venv):

    from sp_api.api.orders.orders_v0 import OrdersV0
    # Public methods verified:
    #   - get_orders(**kwargs) -> ApiResponse
    #       kwargs: CreatedAfter, CreatedBefore, LastUpdatedAfter,
    #               LastUpdatedBefore, OrderStatuses, MarketplaceIds,
    #               FulfillmentChannels, NextToken, MaxResultsPerPage, ...
    #   - get_order_items(order_id, **kwargs) -> ApiResponse
    #       kwargs: NextToken

    from sp_api.base import Marketplaces
    # All 9 target marketplaces present:
    #   - UK/GB, DE, FR, IT, ES, NL -> sellingpartnerapi-eu.amazon.com
    #   - US, CA                     -> sellingpartnerapi-na.amazon.com
    #   - AU                         -> sellingpartnerapi-fe.amazon.com

Design notes:

- Amazon returns order-level data from get_orders() and line-item data
  from get_order_items(order_id). Fetching velocity requires BOTH calls:
  one paginated get_orders() to list orders in the window, then one
  get_order_items() per shipped order. For a 30-day window with ~500
  orders that's ~500 extra calls, which fits within the Orders API
  burst rate (0.0167 req/s sustained, burst 20) over a few minutes.
  Fine for the daily 04:17 UTC cron.

- We filter to OrderStatuses=[Shipped, PartiallyShipped]. Unshipped
  orders haven't contributed to velocity yet (customer may still cancel),
  and Cancelled orders shouldn't count at all. PartiallyShipped orders
  are included because get_order_items reflects the actual shipped
  quantities via QuantityShipped per line.

- Returns netting is OUT OF SCOPE for v1 (see brief § "Known
  limitations"). Gross shipped units only.

- PII scrub: `scrub_response_body()` whitelists only the keys we need
  for debugging. BuyerEmail, BuyerName, ShippingAddress, etc. are
  dropped. Whitelist-not-blacklist means a new PII field in a future
  API version won't accidentally get persisted.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from typing import Any

from django.conf import settings

from sales_velocity.adapters import (
    ChannelAdapter,
    NormalisedOrderLine,
    ensure_utc,
)

logger = logging.getLogger(__name__)


# ── saleweaver imports (guarded, matching fba_shipments pattern) ─────────────

try:
    from sp_api.api.orders.orders_v0 import OrdersV0
    from sp_api.base import Marketplaces
    from sp_api.base.exceptions import (
        SellingApiException,
        SellingApiRequestThrottledException,
    )
    SP_API_AVAILABLE = True
except ImportError:  # pragma: no cover - defensive
    SP_API_AVAILABLE = False
    OrdersV0 = None  # type: ignore[assignment]
    Marketplaces = None  # type: ignore[assignment]
    SellingApiException = Exception  # type: ignore[assignment,misc]
    SellingApiRequestThrottledException = Exception  # type: ignore[assignment,misc]


# ── Marketplace mapping ──────────────────────────────────────────────────────

# sales_velocity channel code -> saleweaver Marketplaces enum attribute name.
# UK and GB are aliases on the enum; we use UK for consistency with
# settings.SP_API_REFRESH_TOKENS and the rest of the manufacture app.
SALES_VELOCITY_TO_ENUM: dict[str, str] = {
    'amazon_uk': 'UK',
    'amazon_us': 'US',
    'amazon_ca': 'CA',
    'amazon_au': 'AU',
    'amazon_de': 'DE',
    'amazon_fr': 'FR',
    'amazon_es': 'ES',
    'amazon_nl': 'NL',
    'amazon_it': 'IT',
}


# ── PII whitelist ────────────────────────────────────────────────────────────

_ORDER_WHITELIST: frozenset[str] = frozenset({
    'AmazonOrderId',
    'PurchaseDate',
    'LastUpdateDate',
    'OrderStatus',
    'FulfillmentChannel',
    'NumberOfItemsShipped',
    'NumberOfItemsUnshipped',
    'SalesChannel',
    'MarketplaceId',
    'OrderType',
})

_ORDER_ITEM_WHITELIST: frozenset[str] = frozenset({
    'ASIN',
    'SellerSKU',
    'OrderItemId',
    'Title',
    'QuantityOrdered',
    'QuantityShipped',
    'ConditionId',
    'IsGift',
})


def _whitelist(payload: Any) -> Any:
    """
    Recursively strip any key not in the whitelist.

    Amazon payloads are nested dicts with list-of-dict under Orders and
    OrderItems. The structure is shallow enough that this hand-rolled
    walker is clearer than a generic JSON transformer.
    """
    if payload is None:
        return None
    if isinstance(payload, list):
        return [_whitelist(x) for x in payload]
    if not isinstance(payload, dict):
        return payload

    out: dict[str, Any] = {}
    for k, v in payload.items():
        if k == 'Orders':
            out[k] = [
                {ok: ov for ok, ov in (o or {}).items() if ok in _ORDER_WHITELIST}
                for o in (v or [])
            ]
        elif k == 'OrderItems':
            out[k] = [
                {ik: iv for ik, iv in (i or {}).items() if ik in _ORDER_ITEM_WHITELIST}
                for i in (v or [])
            ]
        elif k == 'NextToken':
            # Opaque token — safe to keep for debugging pagination.
            out[k] = v
        elif k in _ORDER_WHITELIST or k in _ORDER_ITEM_WHITELIST:
            out[k] = v
        # Everything else is dropped.
    return out


# ── Retry + rate-limit constants ─────────────────────────────────────────────

MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 2
DEFAULT_MAX_RESULTS_PER_PAGE = 100  # Amazon's cap is 100 for get_orders

# Amazon's shipped-only filter — matches the brief's "gross shipped units"
# scope. PartiallyShipped orders are included because their line items
# already reflect the actual shipped quantities via QuantityShipped.
SHIPPED_STATUSES = ['Shipped', 'PartiallyShipped']


# ── Adapter ──────────────────────────────────────────────────────────────────

class AmazonAdapter(ChannelAdapter):
    """
    One AmazonAdapter per marketplace. Set `channel` at instantiation time
    rather than as a class attribute because we want 9 instances backed
    by 9 different marketplace endpoints sharing one class.
    """

    def __init__(
        self,
        sales_velocity_channel: str,
        *,
        _client: Any = None,
    ) -> None:
        if sales_velocity_channel not in SALES_VELOCITY_TO_ENUM:
            raise ValueError(
                f'Unknown Amazon sales_velocity channel {sales_velocity_channel!r}; '
                f'expected one of {sorted(SALES_VELOCITY_TO_ENUM)}'
            )
        # Set channel BEFORE super().__init__() so the ABC validation passes.
        self.channel = sales_velocity_channel
        super().__init__()

        self._marketplace_code = SALES_VELOCITY_TO_ENUM[sales_velocity_channel]
        self._client = _client  # test injection hook

    # ------------------------------------------------------------------ #
    # Client construction                                                #
    # ------------------------------------------------------------------ #

    def _get_client(self) -> Any:
        """
        Return the underlying saleweaver OrdersV0 client, constructing it
        lazily on first use. Tests inject via `_client=` on __init__.
        """
        if self._client is not None:
            return self._client

        if not SP_API_AVAILABLE:
            raise ImportError(
                'python-amazon-sp-api is not installed. Add it to '
                'requirements.txt before running AmazonAdapter.'
            )

        credentials = self._build_credentials()
        marketplace_enum = getattr(Marketplaces, self._marketplace_code)
        self._client = OrdersV0(
            marketplace=marketplace_enum,
            credentials=credentials,
        )
        return self._client

    def _build_credentials(self) -> dict[str, str]:
        """
        Compose the credentials dict, using the per-marketplace refresh
        token from settings.SP_API_REFRESH_TOKENS. Matches the pattern
        used by `fba_shipments.services.sp_api_client.FBAInboundClient`.
        """
        base = dict(getattr(settings, 'SP_API_CREDENTIALS', {}) or {})
        refresh_tokens = getattr(settings, 'SP_API_REFRESH_TOKENS', {}) or {}
        refresh_key = SALES_VELOCITY_TO_ENUM[self.channel]
        override = refresh_tokens.get(refresh_key)
        if override:
            base['refresh_token'] = override
        return base

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def fetch_orders(
        self,
        start_date: date,
        end_date: date,
    ) -> list[NormalisedOrderLine]:
        """
        Fetch every shipped line item for this marketplace whose
        PurchaseDate falls in the window. Two-phase fetch:

          1. Paginate get_orders() with CreatedAfter/CreatedBefore +
             OrderStatuses=Shipped,PartiallyShipped. Collect AmazonOrderId
             and PurchaseDate.
          2. For each order, call get_order_items(order_id) and emit
             one NormalisedOrderLine per line item with a SellerSKU and
             a positive QuantityShipped.

        On throttle: exponential backoff up to MAX_RETRIES per call.
        On unrecoverable error: log to audit, re-raise so the aggregator
        records a channel failure and moves on to the next channel.
        """
        start_dt = datetime.combine(
            start_date, datetime.min.time(), tzinfo=timezone.utc,
        )
        end_dt = datetime.combine(
            end_date, datetime.max.time(), tzinfo=timezone.utc,
        )

        # Phase 1 — paginate get_orders and collect (order_id, purchase_date).
        order_purchase_dates: dict[str, datetime] = {}
        next_token: str | None = None
        page_count = 0
        while True:
            page_count += 1
            payload = self._call_get_orders(
                created_after=start_dt,
                created_before=end_dt,
                next_token=next_token,
            )
            orders = (payload or {}).get('Orders', []) or []
            for order in orders:
                order_id = order.get('AmazonOrderId')
                if not order_id:
                    continue
                order_purchase_dates[order_id] = (
                    ensure_utc(order.get('PurchaseDate')) or start_dt
                )
            next_token = (payload or {}).get('NextToken')
            if not next_token:
                break

        # Phase 2 — fetch line items for each order. We deliberately do NOT
        # parallelise — saleweaver shares a single underlying HTTP client
        # and concurrent calls would just race the rate limiter.
        lines: list[NormalisedOrderLine] = []
        for order_id, purchase_date in order_purchase_dates.items():
            items_payload = self._call_get_order_items(order_id=order_id)
            items = (items_payload or {}).get('OrderItems', []) or []
            for item in items:
                sku = item.get('SellerSKU')
                qty = self._extract_shipped_qty(item)
                if not sku or qty <= 0:
                    continue
                lines.append(NormalisedOrderLine(
                    external_sku=sku,
                    quantity=qty,
                    sale_date=purchase_date,
                    raw_data={
                        'order_id': order_id,
                        'order_item_id': item.get('OrderItemId'),
                        'asin': item.get('ASIN'),
                        'marketplace': self._marketplace_code,
                    },
                ))

        logger.info(
            'AmazonAdapter[%s]: %d pages, %d orders, %d line items',
            self.channel, page_count, len(order_purchase_dates), len(lines),
        )
        return lines

    # ------------------------------------------------------------------ #
    # Raw call helpers                                                   #
    # ------------------------------------------------------------------ #

    def _call_get_orders(
        self,
        *,
        created_after: datetime,
        created_before: datetime,
        next_token: str | None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            'CreatedAfter': created_after.isoformat(),
            'CreatedBefore': created_before.isoformat(),
            'OrderStatuses': SHIPPED_STATUSES,
            'MaxResultsPerPage': DEFAULT_MAX_RESULTS_PER_PAGE,
        }
        if next_token:
            kwargs['NextToken'] = next_token
        return self._call(
            endpoint='orders/v0/orders',
            method_name='get_orders',
            method_kwargs=kwargs,
        )

    def _call_get_order_items(self, *, order_id: str) -> Any:
        return self._call(
            endpoint=f'orders/v0/orders/{order_id}/orderItems',
            method_name='get_order_items',
            method_args=(order_id,),
            method_kwargs={},
        )

    def _call(
        self,
        *,
        endpoint: str,
        method_name: str,
        method_args: tuple = (),
        method_kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """
        Central retry + audit helper. Mirrors the pattern in
        `fba_shipments.services.sp_api_client._call`, adapted for Orders.
        Audit rows go to `SalesVelocityAPICall` via the ABC's
        `_log_api_call`.
        """
        method_kwargs = method_kwargs or {}
        client = self._get_client()
        method = getattr(client, method_name)

        backoff = INITIAL_BACKOFF_SECONDS
        last_exception: Exception | None = None

        for attempt in range(MAX_RETRIES):
            with self._time_call() as timer:
                try:
                    response = method(*method_args, **method_kwargs)
                except SellingApiRequestThrottledException as exc:
                    last_exception = exc
                    logger.warning(
                        'AmazonAdapter[%s] throttled on %s (attempt %d/%d); '
                        'backing off %ds',
                        self.channel, method_name, attempt + 1, MAX_RETRIES, backoff,
                    )
                    self._log_api_call(
                        endpoint=endpoint,
                        request_params={'args': list(method_args), **method_kwargs},
                        response_status=429,
                        response_body=None,
                        duration_ms=timer.ms,
                        error_message=f'throttled: {exc}',
                    )
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                except SellingApiException as exc:
                    self._log_api_call(
                        endpoint=endpoint,
                        request_params={'args': list(method_args), **method_kwargs},
                        response_status=getattr(exc, 'code', None) or 500,
                        response_body=None,
                        duration_ms=timer.ms,
                        error_message=f'{type(exc).__name__}: {exc}',
                    )
                    raise

            payload = _extract_payload(response)
            self._log_api_call(
                endpoint=endpoint,
                request_params={'args': list(method_args), **method_kwargs},
                response_status=200,
                response_body=payload,
                duration_ms=timer.ms,
                error_message='',
            )
            return payload

        # Exhausted retries on throttle
        assert last_exception is not None
        raise last_exception

    # ------------------------------------------------------------------ #
    # Derivation helpers                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_shipped_qty(item: dict[str, Any]) -> int:
        """
        Extract the actual shipped quantity for one line item.

        Amazon returns QuantityShipped and QuantityOrdered. For velocity,
        we want shipped (gross, no return netting). Amazon returns ints
        directly (no nested {Amount, CurrencyCode} wrapping for counts).
        """
        qty = item.get('QuantityShipped', 0)
        try:
            return int(qty) if qty is not None else 0
        except (TypeError, ValueError):
            return 0

    # ------------------------------------------------------------------ #
    # PII scrub (overrides ABC default)                                  #
    # ------------------------------------------------------------------ #

    def scrub_response_body(self, response_body: Any) -> Any:
        return _whitelist(response_body)


# ── Response payload extraction ──────────────────────────────────────────────

def _extract_payload(response: Any) -> Any:
    """
    Normalise saleweaver ApiResponse (or a raw dict) to its payload.
    saleweaver returns an ApiResponse with .payload for Orders calls;
    tests often pass raw dicts so we accept both.
    """
    if hasattr(response, 'payload'):
        return response.payload
    return response


# ── Factory ──────────────────────────────────────────────────────────────────

def build_all_amazon_adapters() -> list[AmazonAdapter]:
    """
    Instantiate one AmazonAdapter per marketplace NBNE sells through.
    Used by the aggregator at the start of every daily run.
    """
    return [
        AmazonAdapter(channel_code)
        for channel_code in SALES_VELOCITY_TO_ENUM.keys()
    ]


__all__ = [
    'AmazonAdapter',
    'build_all_amazon_adapters',
    'SALES_VELOCITY_TO_ENUM',
    'SHIPPED_STATUSES',
]
