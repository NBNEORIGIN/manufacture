"""
Channel adapter framework for the sales_velocity module.

Each adapter implements the `ChannelAdapter` ABC and returns a flat list
of `NormalisedOrderLine` records for a given date window. The aggregator
(`sales_velocity.services.aggregator`, Phase 2B.4) joins these to the
products.SKU table channel-agnostically and rolls them up into daily
`SalesVelocityHistory` snapshots.

Design rules (all mandatory):

1. Adapters are stateless across runs — no pagination cursors, no
   caches, no last-seen watermarks. The aggregator calls `fetch_orders`
   with an explicit (start_date, end_date) window each time and the
   adapter handles internal pagination fully within that call.

2. Every outbound API call is logged to `SalesVelocityAPICall` via
   `_log_api_call()`, which strips PII before persisting. The whitelist
   is per-adapter — Amazon drops BuyerEmail/BuyerName/ShippingAddress;
   Etsy-via-Cairn doesn't see buyer data at all; eBay drops buyer
   identifiers and shipping addresses. Never blacklist — whitelist the
   keys you keep.

3. `NormalisedOrderLine.raw_data` is a debug-only blob, NOT for
   aggregator consumption. The aggregator only reads external_sku,
   quantity, and sale_date. raw_data is there so SalesVelocityAPICall
   rows can be cross-referenced back to the normalised output when a
   bug needs chasing.

4. Gross shipped units only for v1 — no returns netting. See
   docs/sales_velocity_brief.md § "Known limitations".

5. Adapter instances are cheap to construct. The aggregator builds all
   9 Amazon adapters + Etsy + eBay + Footfall + Shop on every run and
   calls fetch_orders on each. Don't hold connection pools on the
   adapter — the underlying SP-API client handles that internally.
"""
from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from sales_velocity.models import SalesVelocityAPICall

logger = logging.getLogger(__name__)


# ── Core data shape ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class NormalisedOrderLine:
    """
    One line item from one order from one channel, normalised to the
    minimum the aggregator needs.

    `external_sku` is the channel's SKU string — Amazon SellerSKU, Etsy
    listing SKU, eBay SKU, whatever the channel calls it. The aggregator
    joins this to `products.SKU.sku` channel-agnostically.

    `quantity` is the shipped quantity for this line item (gross,
    no returns netting).

    `sale_date` is the order creation date in UTC. Amazon's PurchaseDate,
    Etsy's create_timestamp, eBay's creationDate — whichever the channel
    uses for "when the customer placed the order". Shipped-on date would
    be a different choice but creation date is what the brief's 30-day
    window is measured against.

    `raw_data` is a debug blob — the adapter should put enough of the
    upstream response in here for a future engineer to reconstruct how
    a line was derived. NOT consumed by the aggregator.
    """

    external_sku: str
    quantity: int
    sale_date: datetime
    raw_data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.quantity < 0:
            raise ValueError(
                f'NormalisedOrderLine.quantity must be >= 0, got {self.quantity}'
            )
        if self.sale_date.tzinfo is None:
            raise ValueError(
                'NormalisedOrderLine.sale_date must be timezone-aware '
                f'(got naive datetime {self.sale_date!r})'
            )


# ── ABC ──────────────────────────────────────────────────────────────────────

class ChannelAdapter(ABC):
    """
    Base class for all sales_velocity channel adapters.

    Subclasses must set the class attribute `channel` to one of the
    CHANNEL_CHOICES codes defined in sales_velocity.models, and
    implement `fetch_orders(start_date, end_date)`.

    Audit logging and PII scrubbing is provided via `_log_api_call()` —
    subclasses call it once per outbound HTTP request.
    """

    channel: str = ''  # subclasses override

    def __init__(self) -> None:
        if not self.channel:
            raise ValueError(
                f'{type(self).__name__} must set a class-level `channel` '
                'attribute before instantiation'
            )

    @abstractmethod
    def fetch_orders(
        self,
        start_date: date,
        end_date: date,
    ) -> list[NormalisedOrderLine]:
        """
        Return every shipped line item from this channel whose
        sale_date falls in [start_date, end_date] (inclusive on both
        ends — adapters are responsible for their own window boundary
        handling if the upstream API uses half-open intervals).

        Must handle pagination, rate limiting, and retries internally.
        Must NOT catch exceptions except for logging + audit purposes —
        unrecoverable errors should propagate so the aggregator can
        record a failure for this adapter and continue with the others.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Audit logging + PII scrub                                          #
    # ------------------------------------------------------------------ #

    def _log_api_call(
        self,
        *,
        endpoint: str,
        request_params: dict[str, Any] | None = None,
        response_status: int | None = None,
        response_body: Any = None,
        duration_ms: int | None = None,
        error_message: str = '',
    ) -> None:
        """
        Persist one audit row. `response_body` is scrubbed via
        `scrub_response_body()` (which subclasses override) before
        writing. Never raises — audit logging failing must not break
        the aggregator.
        """
        try:
            SalesVelocityAPICall.objects.create(
                channel=self.channel,
                endpoint=endpoint[:120],
                request_params=_safe_json(request_params),
                response_status=response_status,
                response_body=self.scrub_response_body(response_body),
                duration_ms=duration_ms,
                error_message=error_message[:5000] if error_message else '',
            )
        except Exception:
            logger.exception(
                'Failed to persist SalesVelocityAPICall for %s %s — swallowing '
                'so the aggregator keeps running',
                self.channel, endpoint,
            )

    def scrub_response_body(self, response_body: Any) -> Any:
        """
        Default PII scrub: store nothing. Subclasses override to
        whitelist specific safe keys (SKU, quantity, sale_date, order
        identifiers used for dedupe).

        Default-deny is deliberate — an adapter that forgets to
        override this method stores NO response bodies, which is the
        safe failure mode.
        """
        return None

    # ------------------------------------------------------------------ #
    # Timing helper                                                      #
    # ------------------------------------------------------------------ #

    def _time_call(self) -> '_CallTimer':
        """Context manager: `with self._time_call() as t: ... ; t.ms`."""
        return _CallTimer()


class _CallTimer:
    """Minimal stopwatch for request duration logging."""

    def __init__(self) -> None:
        self._start: float = 0.0
        self.ms: int = 0

    def __enter__(self) -> '_CallTimer':
        self._start = time.monotonic()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.ms = int((time.monotonic() - self._start) * 1000)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _safe_json(obj: Any) -> Any:
    """
    Coerce a potentially non-JSON-serialisable object (Decimal, datetime,
    set, etc.) into something JSONField can store, by round-tripping
    through json with default=str. Idempotent for already-serialisable
    values. Returns None for None. Mirrors the helper in
    fba_shipments.services.sp_api_client for consistency.
    """
    if obj is None:
        return None
    try:
        return json.loads(json.dumps(obj, default=str))
    except (TypeError, ValueError):
        return {'__unserialisable__': str(obj)}


def ensure_utc(value: datetime | str | None) -> datetime | None:
    """
    Coerce a datetime or ISO 8601 string to a tz-aware UTC datetime.
    Amazon returns ISO strings; Etsy (via Cairn) returns ISO strings;
    eBay returns ISO strings. None pass-through.
    """
    if value is None:
        return None
    if isinstance(value, str):
        # Handle trailing Z which fromisoformat() rejects pre-3.11 edge cases
        if value.endswith('Z'):
            value = value[:-1] + '+00:00'
        dt = datetime.fromisoformat(value)
    else:
        dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


__all__ = [
    'ChannelAdapter',
    'NormalisedOrderLine',
    'ensure_utc',
]
