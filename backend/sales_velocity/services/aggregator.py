"""
Sales Velocity aggregator.

Run daily by a Django-Q schedule (see
`sales_velocity/migrations/0002_register_daily_schedule.py`). Also
callable from the `refresh_sales_velocity` management command and the
`POST /api/sales-velocity/refresh/` API endpoint.

Flow per run (brief § Phase 2B.4):

  1. Call every adapter for the last 30 days, collecting
     NormalisedOrderLine records. Adapter failures are logged to the
     audit table but don't block other channels.
  2. Join external_sku to products.Product via SKU.sku CHANNEL-AGNOSTICALLY.
     If one external_sku matches SKU rows pointing to different Products,
     log a duplicate warning and SKIP the row (per user modification (b)
     from the 2026-04-11 planning session) — never silently pick one.
  3. Insert/update SalesVelocityHistory rows for today, one per
     (product, channel, snapshot_date). Re-runs on the same day are
     idempotent via the unique_together constraint.
  4. Capture unmatched SKUs into UnmatchedSKU with rolling 30-day counter
     semantics.
  5. If settings.SALES_VELOCITY_WRITE_ENABLED is True, compute the
     60-day equivalent per Product (sum units_sold_30d across channels
     for today's snapshots, doubled) and update
     StockLevel.sixty_day_sales. On the FIRST write-through after a
     flip from False, write a one-off audit row with endpoint='cutover'.
  6. Return a dict summary for the management command / API endpoint to
     print or return to the caller.

Shadow mode is a single env var check at step 5 — no separate model,
no state machine, just "write or don't write".
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from sales_velocity.adapters import ChannelAdapter, NormalisedOrderLine
from sales_velocity.adapters.amazon import build_all_amazon_adapters
from sales_velocity.adapters.ebay import EbayAdapter
from sales_velocity.adapters.etsy import EtsyAdapter
from sales_velocity.models import (
    CHANNELS_DATA_CLEANUP,
    CHANNELS_OUT_OF_SCOPE,
    DriftAlert,
    SalesVelocityAPICall,
    SalesVelocityHistory,
    UnmatchedSKU,
)

logger = logging.getLogger(__name__)


# ── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_LOOKBACK_DAYS = 30


# ── Result shape ─────────────────────────────────────────────────────────────

@dataclass
class ChannelResult:
    channel: str
    lines_fetched: int = 0
    lines_matched: int = 0
    lines_unmatched: int = 0
    lines_duplicate: int = 0
    snapshots_upserted: int = 0
    error: str = ''


@dataclass
class AggregationResult:
    snapshot_date: date
    lookback_days: int
    total_lines_fetched: int = 0
    total_snapshots_upserted: int = 0
    total_unmatched_skus: int = 0
    total_duplicate_skus_skipped: int = 0
    channels: list[ChannelResult] = field(default_factory=list)
    stock_level_updated: bool = False
    stock_level_products_updated: int = 0
    cutover_fired: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            'snapshot_date': self.snapshot_date.isoformat(),
            'lookback_days': self.lookback_days,
            'total_lines_fetched': self.total_lines_fetched,
            'total_snapshots_upserted': self.total_snapshots_upserted,
            'total_unmatched_skus': self.total_unmatched_skus,
            'total_duplicate_skus_skipped': self.total_duplicate_skus_skipped,
            'stock_level_updated': self.stock_level_updated,
            'stock_level_products_updated': self.stock_level_products_updated,
            'cutover_fired': self.cutover_fired,
            'channels': [
                {
                    'channel': c.channel,
                    'lines_fetched': c.lines_fetched,
                    'lines_matched': c.lines_matched,
                    'lines_unmatched': c.lines_unmatched,
                    'lines_duplicate': c.lines_duplicate,
                    'snapshots_upserted': c.snapshots_upserted,
                    'error': c.error,
                }
                for c in self.channels
            ],
        }


# ── Public entry points ──────────────────────────────────────────────────────

def run_daily_aggregation(
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    channels_filter: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Entry point called by the Django-Q schedule and the management
    command. Returns a JSON-serialisable dict summary.

    Args:
        lookback_days: window size. Default 30.
        channels_filter: if provided, only run adapters whose `channel`
            attribute is in this list. Used by `refresh_sales_velocity
            --channels=amazon_uk,etsy`.
        dry_run: if True, roll back the transaction at the end so no
            database state changes. Still makes real API calls.
    """
    today = timezone.now().date()
    start = today - timedelta(days=lookback_days - 1)
    result = AggregationResult(snapshot_date=today, lookback_days=lookback_days)

    adapters = _build_adapters(channels_filter)
    if not adapters:
        logger.warning(
            'run_daily_aggregation: no adapters matched filter %r — nothing to do',
            channels_filter,
        )
        return result.as_dict()

    # Phase 1: fetch from every adapter. We deliberately do NOT wrap
    # this in a single atomic() — each adapter can fail independently
    # and we want the successful ones to commit.
    all_lines: dict[str, list[NormalisedOrderLine]] = {}
    for adapter in adapters:
        channel_result = ChannelResult(channel=adapter.channel)
        try:
            lines = adapter.fetch_orders(start, today)
            all_lines[adapter.channel] = lines
            channel_result.lines_fetched = len(lines)
        except Exception as exc:
            logger.exception(
                'Aggregator: %s adapter failed: %s',
                adapter.channel, exc,
            )
            channel_result.error = f'{type(exc).__name__}: {exc}'
            all_lines[adapter.channel] = []
        result.channels.append(channel_result)

    # Phase 2: join + aggregate + upsert, per channel, in transactions.
    from products.models import SKU

    # Pre-compute a channel-agnostic SKU -> Product map with duplicate
    # detection. We do this once per run rather than per-line to avoid
    # N queries.
    sku_map, duplicate_skus = _build_sku_product_map()
    logger.info(
        'Aggregator: SKU map has %d unique SKUs, %d duplicates skipped',
        len(sku_map), len(duplicate_skus),
    )

    for channel_result in result.channels:
        channel = channel_result.channel
        lines = all_lines.get(channel, [])
        if not lines:
            continue
        try:
            matched_count, unmatched_count, dup_count, snap_count = (
                _process_channel_lines(
                    channel=channel,
                    lines=lines,
                    sku_map=sku_map,
                    duplicate_skus=duplicate_skus,
                    snapshot_date=today,
                    dry_run=dry_run,
                )
            )
            channel_result.lines_matched = matched_count
            channel_result.lines_unmatched = unmatched_count
            channel_result.lines_duplicate = dup_count
            channel_result.snapshots_upserted = snap_count
        except Exception as exc:
            logger.exception(
                'Aggregator: processing %s lines failed: %s', channel, exc,
            )
            channel_result.error = f'{type(exc).__name__}: {exc}'

    # Phase 3: totals + shadow-mode gate
    result.total_lines_fetched = sum(c.lines_fetched for c in result.channels)
    result.total_snapshots_upserted = sum(c.snapshots_upserted for c in result.channels)
    result.total_unmatched_skus = sum(c.lines_unmatched for c in result.channels)
    result.total_duplicate_skus_skipped = sum(
        c.lines_duplicate for c in result.channels
    )

    write_enabled = bool(
        getattr(settings, 'SALES_VELOCITY_WRITE_ENABLED', False)
    )
    if write_enabled and not dry_run:
        updated_count, cutover_fired = _update_stock_levels(today)
        result.stock_level_updated = True
        result.stock_level_products_updated = updated_count
        result.cutover_fired = cutover_fired

    logger.info(
        'Aggregator complete: snapshot=%s fetched=%d snaps=%d '
        'unmatched=%d duplicates=%d write_enabled=%s',
        today, result.total_lines_fetched, result.total_snapshots_upserted,
        result.total_unmatched_skus, result.total_duplicate_skus_skipped,
        write_enabled,
    )
    return result.as_dict()


# ── Internal helpers ─────────────────────────────────────────────────────────

def _build_adapters(
    channels_filter: list[str] | None,
) -> list[ChannelAdapter]:
    """
    Return the list of adapters to run. Honours the CLI --channels
    filter if given.
    """
    adapters: list[ChannelAdapter] = []
    adapters.extend(build_all_amazon_adapters())
    adapters.append(EtsyAdapter())
    adapters.append(EbayAdapter())
    # ManualAdapter (footfall) is handled separately — manual entries
    # are already in ManualSale and get rolled into SalesVelocityHistory
    # by _process_manual_sales below.
    if channels_filter:
        filter_set = set(channels_filter)
        adapters = [a for a in adapters if a.channel in filter_set]
    return adapters


def _build_sku_product_map() -> tuple[dict[str, int], set[str]]:
    """
    Channel-agnostic SKU -> product_id map.

    A SKU string that appears on multiple SKU rows pointing to DIFFERENT
    Products is added to `duplicate_skus` and omitted from the map. This
    is the safety mechanism from user modification (b) — we never
    silently pick a winner when a duplicate collision happens.

    Returns:
        (sku_map, duplicate_skus)
    """
    from products.models import SKU

    # Load every (sku, product_id) pair. NBNE has ~3000 SKUs tops, so
    # this fits comfortably in memory.
    pairs = SKU.objects.values_list('sku', 'product_id', 'channel')
    sku_to_products: dict[str, set[int]] = defaultdict(set)
    for sku_string, product_id, channel in pairs:
        # Skip out-of-scope and cleanup channels at the map-build stage
        # so they never participate in matching.
        if channel in CHANNELS_OUT_OF_SCOPE:
            continue
        if channel in CHANNELS_DATA_CLEANUP:
            continue
        if product_id is None:
            # SKU row exists but has no Product FK — treat as unmatched
            # at join time by omitting from the map.
            continue
        sku_to_products[sku_string].add(product_id)

    clean_map: dict[str, int] = {}
    duplicate_skus: set[str] = set()
    for sku_string, product_ids in sku_to_products.items():
        if len(product_ids) == 1:
            clean_map[sku_string] = next(iter(product_ids))
        else:
            duplicate_skus.add(sku_string)
            logger.warning(
                'SKU join: %r maps to %d different products %r — skipping '
                'to avoid silent mis-attribution',
                sku_string, len(product_ids), sorted(product_ids),
            )
    return clean_map, duplicate_skus


def _process_channel_lines(
    *,
    channel: str,
    lines: list[NormalisedOrderLine],
    sku_map: dict[str, int],
    duplicate_skus: set[str],
    snapshot_date: date,
    dry_run: bool,
) -> tuple[int, int, int, int]:
    """
    Aggregate one channel's NormalisedOrderLines into per-product
    totals and upsert into SalesVelocityHistory.

    Returns: (matched_count, unmatched_count, duplicate_count, snapshots_upserted)
    """
    per_product: dict[int, int] = defaultdict(int)
    unmatched_per_sku: dict[str, int] = defaultdict(int)
    matched = 0
    unmatched = 0
    duplicate = 0

    for line in lines:
        sku = line.external_sku
        if sku in duplicate_skus:
            duplicate += 1
            continue
        product_id = sku_map.get(sku)
        if product_id is None:
            unmatched += 1
            unmatched_per_sku[sku] += line.quantity
            continue
        matched += 1
        per_product[product_id] += line.quantity

    if dry_run:
        return matched, unmatched, duplicate, 0

    with transaction.atomic():
        # Upsert SalesVelocityHistory rows. unique_together(product,
        # channel, snapshot_date) makes this idempotent on re-runs.
        snapshots_upserted = 0
        for product_id, qty in per_product.items():
            _, created = SalesVelocityHistory.objects.update_or_create(
                product_id=product_id,
                channel=channel,
                snapshot_date=snapshot_date,
                defaults={'units_sold_30d': qty},
            )
            snapshots_upserted += 1

        # Upsert UnmatchedSKU rows with rolling-window semantics.
        today = snapshot_date
        for external_sku, qty in unmatched_per_sku.items():
            obj, created = UnmatchedSKU.objects.get_or_create(
                channel=channel,
                external_sku=external_sku,
                defaults={
                    'units_sold_30d': qty,
                    'first_seen': today,
                    'last_seen': today,
                },
            )
            if not created:
                obj.units_sold_30d = qty
                obj.last_seen = today
                obj.save(update_fields=['units_sold_30d', 'last_seen'])

        # Any SalesVelocityHistory rows for this (channel, snapshot_date)
        # whose product wasn't in per_product should be decayed to 0.
        # This handles the case where a product stopped selling on this
        # channel since yesterday's run.
        stale = SalesVelocityHistory.objects.filter(
            channel=channel,
            snapshot_date=snapshot_date,
        ).exclude(product_id__in=per_product.keys())
        for obj in stale:
            obj.units_sold_30d = 0
            obj.save(update_fields=['units_sold_30d'])

    return matched, unmatched, duplicate, snapshots_upserted


def _update_stock_levels(snapshot_date: date) -> tuple[int, bool]:
    """
    Write-through from SalesVelocityHistory to StockLevel.sixty_day_sales.
    Called only when SALES_VELOCITY_WRITE_ENABLED is True.

    Returns: (products_updated, cutover_fired)

    cutover_fired is True on the VERY FIRST write-through after a flip,
    detected by the absence of any prior cutover audit row.
    """
    from django.db.models import Sum
    from stock.models import StockLevel

    # Detect first-time cutover: any prior SalesVelocityAPICall with
    # endpoint='cutover'?
    is_first_cutover = not SalesVelocityAPICall.objects.filter(
        endpoint='cutover',
    ).exists()

    # Sum SalesVelocityHistory per product for today, across channels.
    per_product = dict(
        SalesVelocityHistory.objects
        .filter(snapshot_date=snapshot_date)
        .values('product_id')
        .annotate(total_30d=Sum('units_sold_30d'))
        .values_list('product_id', 'total_30d')
    )

    updated_count = 0
    with transaction.atomic():
        for product_id, total_30d in per_product.items():
            sixty_day = (total_30d or 0) * 2
            updated = StockLevel.objects.filter(
                product_id=product_id,
            ).update(sixty_day_sales=sixty_day)
            updated_count += updated

    if is_first_cutover:
        SalesVelocityAPICall.objects.create(
            channel='amazon_uk',  # sentinel channel — not per-channel
            endpoint='cutover',
            request_params={'snapshot_date': snapshot_date.isoformat()},
            response_status=200,
            response_body={
                'products_updated': updated_count,
                'message': (
                    'First SALES_VELOCITY_WRITE_ENABLED=True write-through. '
                    'StockLevel.sixty_day_sales now sourced from the '
                    'aggregator instead of spreadsheet imports.'
                ),
            },
        )
        logger.info(
            'Aggregator: FIRST CUTOVER — StockLevel updated for %d products',
            updated_count,
        )

    return updated_count, is_first_cutover


# ── Weekly sanity check (Phase 2B.6 support) ─────────────────────────────────

def run_weekly_sanity_check(
    *,
    tolerance_pct: float = 5.0,
) -> dict[str, Any]:
    """
    Post-cutover drift detector. Compares today's velocity (sum across
    channels for latest snapshot) against the 7-day rolling average
    from SalesVelocityHistory. Variance > tolerance_pct inserts a
    DriftAlert row.

    Does NOT auto-revert anything. Alert-only.

    Called weekly by a Django-Q schedule (see migration 0002).
    """
    from django.db.models import Avg, Max, Sum

    latest = SalesVelocityHistory.objects.aggregate(m=Max('snapshot_date'))['m']
    if latest is None:
        return {'status': 'no_data', 'alerts_created': 0}

    # Today's per-product total
    today_totals: dict[int, int] = dict(
        SalesVelocityHistory.objects
        .filter(snapshot_date=latest)
        .values('product_id')
        .annotate(total=Sum('units_sold_30d'))
        .values_list('product_id', 'total')
    )

    # 7-day rolling average per product
    rolling_start = latest - timedelta(days=7)
    rolling: dict[int, float] = {}
    for row in (
        SalesVelocityHistory.objects
        .filter(snapshot_date__gte=rolling_start, snapshot_date__lt=latest)
        .values('product_id', 'snapshot_date')
        .annotate(day_total=Sum('units_sold_30d'))
    ):
        pid = row['product_id']
        rolling.setdefault(pid, []).append(row['day_total'] or 0)

    alerts_created = 0
    for product_id, today in today_totals.items():
        days = rolling.get(product_id) or []
        if not days:
            continue
        avg = sum(days) / len(days)
        if avg == 0:
            continue
        variance = abs(today - avg) / avg * 100
        if variance > tolerance_pct:
            DriftAlert.objects.create(
                product_id=product_id,
                detected_at=timezone.now(),
                current_velocity=int(today),
                rolling_avg_velocity=int(round(avg)),
                variance_pct=round(variance, 2),
            )
            alerts_created += 1

    logger.info(
        'Weekly sanity check: %d alerts created (tolerance %.1f%%)',
        alerts_created, tolerance_pct,
    )
    return {
        'status': 'ok',
        'alerts_created': alerts_created,
        'tolerance_pct': tolerance_pct,
        'snapshot_date': latest.isoformat(),
    }


# ── Audit purge (Phase 2B.6 support) ─────────────────────────────────────────

def purge_audit_log(
    *,
    success_retention_days: int = 14,
    error_retention_days: int = 90,
    drift_retention_days: int = 90,
) -> dict[str, Any]:
    """
    Deletes stale audit rows. Called weekly by a Django-Q schedule.
    Success rows age out at 14 days; errored rows at 90; DriftAlert at 90.
    """
    from django.db.models import Q
    now = timezone.now()
    success_cutoff = now - timedelta(days=success_retention_days)
    error_cutoff = now - timedelta(days=error_retention_days)
    drift_cutoff = now - timedelta(days=drift_retention_days)

    success_deleted, _ = SalesVelocityAPICall.objects.filter(
        created_at__lt=success_cutoff,
        response_status=200,
        error_message='',
    ).delete()

    error_deleted, _ = SalesVelocityAPICall.objects.filter(
        created_at__lt=error_cutoff,
    ).filter(
        Q(response_status__gte=400) | ~Q(error_message=''),
    ).delete()

    drift_deleted, _ = DriftAlert.objects.filter(
        detected_at__lt=drift_cutoff,
    ).delete()

    logger.info(
        'Audit purge: %d success rows, %d error rows, %d drift alerts',
        success_deleted, error_deleted, drift_deleted,
    )
    return {
        'success_deleted': success_deleted,
        'error_deleted': error_deleted,
        'drift_deleted': drift_deleted,
    }
