"""
Tests for the sales_velocity aggregator service.

Covers:
- channel-agnostic SKU join (including duplicate detection)
- SalesVelocityHistory upsert idempotency on re-run
- UnmatchedSKU rolling counter semantics
- Shadow-mode: SALES_VELOCITY_WRITE_ENABLED=False does NOT update StockLevel
- Cutover: SALES_VELOCITY_WRITE_ENABLED=True DOES update StockLevel, and
  fires the one-off cutover audit row exactly once
- Weekly sanity check drift alert creation
- Audit purge retention policy
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone as django_tz

from sales_velocity.adapters import NormalisedOrderLine
from sales_velocity.models import (
    DriftAlert,
    SalesVelocityAPICall,
    SalesVelocityHistory,
    UnmatchedSKU,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def product_m0823(db):
    from products.models import Product
    return Product.objects.create(
        m_number='M0823',
        description='Small Oak Memorial Plaque',
        blank='OAK',
    )


@pytest.fixture
def product_m0824(db):
    from products.models import Product
    return Product.objects.create(
        m_number='M0824',
        description='Medium Oak Memorial Plaque',
        blank='OAK',
    )


@pytest.fixture
def sku_m0823_uk(db, product_m0823):
    from products.models import SKU
    return SKU.objects.create(
        sku='NBN-M0823-SM-OAK',
        channel='UK',
        product=product_m0823,
    )


@pytest.fixture
def sku_m0823_etsy(db, product_m0823):
    from products.models import SKU
    return SKU.objects.create(
        sku='NBN-M0823-SM-OAK',  # same SKU string on different channel — still same product
        channel='ETSY',
        product=product_m0823,
    )


@pytest.fixture
def sku_m0824_uk(db, product_m0824):
    from products.models import SKU
    return SKU.objects.create(
        sku='NBN-M0824-MD-OAK',
        channel='UK',
        product=product_m0824,
    )


@pytest.fixture
def duplicate_sku_collision(db, product_m0823, product_m0824):
    """Same external_sku on two channels, pointing to DIFFERENT products."""
    from products.models import SKU
    SKU.objects.create(
        sku='AMBIGUOUS-123', channel='UK', product=product_m0823,
    )
    SKU.objects.create(
        sku='AMBIGUOUS-123', channel='DE', product=product_m0824,
    )
    return 'AMBIGUOUS-123'


def _utc(y, m, d):
    return datetime(y, m, d, 12, 0, tzinfo=timezone.utc)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_adapter(channel: str, lines: list[NormalisedOrderLine]):
    """Return a MagicMock that behaves like a ChannelAdapter."""
    mock = MagicMock()
    mock.channel = channel
    mock.fetch_orders = MagicMock(return_value=lines)
    return mock


def _patch_adapters(amazon_mocks=None, etsy_mock=None, ebay_mock=None):
    """
    Context manager helper: patches build_all_amazon_adapters + EtsyAdapter
    + EbayAdapter inside the aggregator so tests don't touch real adapters.
    """
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(patch(
        'sales_velocity.services.aggregator.build_all_amazon_adapters',
        return_value=list(amazon_mocks or []),
    ))
    stack.enter_context(patch(
        'sales_velocity.services.aggregator.EtsyAdapter',
        return_value=(etsy_mock or _mock_adapter('etsy', [])),
    ))
    stack.enter_context(patch(
        'sales_velocity.services.aggregator.EbayAdapter',
        return_value=(ebay_mock or _mock_adapter('ebay', [])),
    ))
    return stack


# ── Tests: channel-agnostic join ──────────────────────────────────────────────

@pytest.mark.django_db
class TestChannelAgnosticJoin:
    def test_matched_line_updates_history(
        self, sku_m0823_uk, sku_m0823_etsy, product_m0823,
    ):
        from sales_velocity.services.aggregator import run_daily_aggregation

        amazon_uk_mock = _mock_adapter('amazon_uk', [
            NormalisedOrderLine(
                external_sku='NBN-M0823-SM-OAK',
                quantity=3,
                sale_date=_utc(2026, 4, 5),
            ),
        ])

        with _patch_adapters(amazon_mocks=[amazon_uk_mock]):
            result = run_daily_aggregation()

        assert result['total_lines_fetched'] == 1  # one NormalisedOrderLine
        amazon = next(c for c in result['channels'] if c['channel'] == 'amazon_uk')
        assert amazon['lines_matched'] == 1
        assert amazon['snapshots_upserted'] == 1

        snap = SalesVelocityHistory.objects.get(
            product=product_m0823, channel='amazon_uk',
        )
        assert snap.units_sold_30d == 3

    def test_aggregates_multiple_lines_per_product(
        self, sku_m0823_uk, product_m0823,
    ):
        from sales_velocity.services.aggregator import run_daily_aggregation

        amazon_uk_mock = _mock_adapter('amazon_uk', [
            NormalisedOrderLine(
                external_sku='NBN-M0823-SM-OAK',
                quantity=2,
                sale_date=_utc(2026, 4, 5),
            ),
            NormalisedOrderLine(
                external_sku='NBN-M0823-SM-OAK',
                quantity=3,
                sale_date=_utc(2026, 4, 6),
            ),
        ])

        with _patch_adapters(amazon_mocks=[amazon_uk_mock]):
            run_daily_aggregation()

        snap = SalesVelocityHistory.objects.get(
            product=product_m0823, channel='amazon_uk',
        )
        assert snap.units_sold_30d == 5  # 2 + 3

    def test_reruns_are_idempotent(self, sku_m0823_uk, product_m0823):
        from sales_velocity.services.aggregator import run_daily_aggregation
        lines = [NormalisedOrderLine(
            external_sku='NBN-M0823-SM-OAK',
            quantity=4,
            sale_date=_utc(2026, 4, 5),
        )]
        with _patch_adapters(amazon_mocks=[_mock_adapter('amazon_uk', lines)]):
            run_daily_aggregation()
        with _patch_adapters(amazon_mocks=[_mock_adapter('amazon_uk', lines)]):
            run_daily_aggregation()

        # Only one row — unique_together enforces it
        assert SalesVelocityHistory.objects.filter(
            product=product_m0823, channel='amazon_uk',
        ).count() == 1
        snap = SalesVelocityHistory.objects.get(
            product=product_m0823, channel='amazon_uk',
        )
        assert snap.units_sold_30d == 4

    def test_duplicate_sku_skipped_not_silently_resolved(
        self, duplicate_sku_collision,
    ):
        """
        The heart of user modification (b): if one external_sku matches
        SKU rows pointing to multiple Products, SKIP the row rather than
        pick a winner.
        """
        from sales_velocity.services.aggregator import run_daily_aggregation

        amazon_uk_mock = _mock_adapter('amazon_uk', [
            NormalisedOrderLine(
                external_sku='AMBIGUOUS-123',
                quantity=10,
                sale_date=_utc(2026, 4, 5),
            ),
        ])

        with _patch_adapters(amazon_mocks=[amazon_uk_mock]):
            result = run_daily_aggregation()

        # No history rows — the line was skipped
        assert SalesVelocityHistory.objects.count() == 0
        assert result['total_duplicate_skus_skipped'] == 1

    def test_unmatched_sku_populates_table(self, db):
        from sales_velocity.services.aggregator import run_daily_aggregation

        mock = _mock_adapter('amazon_uk', [
            NormalisedOrderLine(
                external_sku='UNKNOWN-SKU-XYZ',
                quantity=7,
                sale_date=_utc(2026, 4, 5),
            ),
        ])

        with _patch_adapters(amazon_mocks=[mock]):
            run_daily_aggregation()

        unmatched = UnmatchedSKU.objects.get(
            channel='amazon_uk', external_sku='UNKNOWN-SKU-XYZ',
        )
        assert unmatched.units_sold_30d == 7

    def test_unmatched_sku_is_rolling_not_cumulative(self, db):
        """Two runs on the same day => overwrites, not accumulates."""
        from sales_velocity.services.aggregator import run_daily_aggregation

        lines_first = [NormalisedOrderLine(
            external_sku='UNKNOWN-X', quantity=5, sale_date=_utc(2026, 4, 5),
        )]
        lines_second = [NormalisedOrderLine(
            external_sku='UNKNOWN-X', quantity=3, sale_date=_utc(2026, 4, 5),
        )]

        with _patch_adapters(amazon_mocks=[_mock_adapter('amazon_uk', lines_first)]):
            run_daily_aggregation()
        with _patch_adapters(amazon_mocks=[_mock_adapter('amazon_uk', lines_second)]):
            run_daily_aggregation()

        obj = UnmatchedSKU.objects.get(channel='amazon_uk', external_sku='UNKNOWN-X')
        assert obj.units_sold_30d == 3  # Rolling, not 5+3


# ── Tests: shadow mode ───────────────────────────────────────────────────────

@pytest.mark.django_db
class TestShadowMode:
    def test_shadow_off_does_not_touch_stock_level(
        self, sku_m0823_uk, product_m0823, settings,
    ):
        from sales_velocity.services.aggregator import run_daily_aggregation
        from stock.models import StockLevel

        settings.SALES_VELOCITY_WRITE_ENABLED = False
        stock, _ = StockLevel.objects.get_or_create(
            product=product_m0823,
            defaults={'current_stock': 50, 'sixty_day_sales': 100},
        )

        mock = _mock_adapter('amazon_uk', [NormalisedOrderLine(
            external_sku='NBN-M0823-SM-OAK', quantity=5, sale_date=_utc(2026, 4, 5),
        )])
        with _patch_adapters(amazon_mocks=[mock]):
            result = run_daily_aggregation()

        stock.refresh_from_db()
        assert stock.sixty_day_sales == 100  # unchanged
        assert result['stock_level_updated'] is False

    def test_shadow_on_updates_stock_level_and_fires_cutover(
        self, sku_m0823_uk, product_m0823, settings,
    ):
        from sales_velocity.services.aggregator import run_daily_aggregation
        from stock.models import StockLevel

        settings.SALES_VELOCITY_WRITE_ENABLED = True
        stock, _ = StockLevel.objects.get_or_create(
            product=product_m0823,
            defaults={'current_stock': 50, 'sixty_day_sales': 100},
        )

        mock = _mock_adapter('amazon_uk', [NormalisedOrderLine(
            external_sku='NBN-M0823-SM-OAK', quantity=5, sale_date=_utc(2026, 4, 5),
        )])
        with _patch_adapters(amazon_mocks=[mock]):
            result = run_daily_aggregation()

        stock.refresh_from_db()
        # 5 shipped in 30d * 2 = 10 for sixty_day_sales
        assert stock.sixty_day_sales == 10
        assert result['stock_level_updated'] is True
        assert result['cutover_fired'] is True

        # Cutover audit row fired exactly once
        cutover_rows = SalesVelocityAPICall.objects.filter(endpoint='cutover')
        assert cutover_rows.count() == 1

    def test_cutover_only_fires_on_first_write_through(
        self, sku_m0823_uk, product_m0823, settings,
    ):
        from sales_velocity.services.aggregator import run_daily_aggregation
        from stock.models import StockLevel

        settings.SALES_VELOCITY_WRITE_ENABLED = True
        StockLevel.objects.get_or_create(
            product=product_m0823,
            defaults={'current_stock': 50, 'sixty_day_sales': 100},
        )
        mock_lines = [NormalisedOrderLine(
            external_sku='NBN-M0823-SM-OAK', quantity=5, sale_date=_utc(2026, 4, 5),
        )]

        # First run — cutover fires
        with _patch_adapters(amazon_mocks=[_mock_adapter('amazon_uk', mock_lines)]):
            r1 = run_daily_aggregation()
        # Second run — cutover does NOT fire again
        with _patch_adapters(amazon_mocks=[_mock_adapter('amazon_uk', mock_lines)]):
            r2 = run_daily_aggregation()

        assert r1['cutover_fired'] is True
        assert r2['cutover_fired'] is False
        assert SalesVelocityAPICall.objects.filter(endpoint='cutover').count() == 1


# ── Tests: weekly sanity check ────────────────────────────────────────────────

@pytest.mark.django_db
class TestWeeklySanityCheck:
    def test_creates_drift_alert_on_variance(self, product_m0823):
        from sales_velocity.services.aggregator import run_weekly_sanity_check

        today = date(2026, 4, 11)
        # Rolling 7-day: each day had units_sold_30d ~= 10
        for i in range(1, 8):
            SalesVelocityHistory.objects.create(
                product=product_m0823,
                channel='amazon_uk',
                snapshot_date=today - timedelta(days=i),
                units_sold_30d=10,
            )
        # Today: massive spike
        SalesVelocityHistory.objects.create(
            product=product_m0823,
            channel='amazon_uk',
            snapshot_date=today,
            units_sold_30d=30,
        )

        result = run_weekly_sanity_check(tolerance_pct=5.0)
        assert result['alerts_created'] == 1
        alert = DriftAlert.objects.get(product=product_m0823)
        assert alert.current_velocity == 30
        assert alert.rolling_avg_velocity == 10
        assert alert.variance_pct == 200.0

    def test_no_alert_within_tolerance(self, product_m0823):
        from sales_velocity.services.aggregator import run_weekly_sanity_check

        today = date(2026, 4, 11)
        for i in range(1, 8):
            SalesVelocityHistory.objects.create(
                product=product_m0823,
                channel='amazon_uk',
                snapshot_date=today - timedelta(days=i),
                units_sold_30d=10,
            )
        SalesVelocityHistory.objects.create(
            product=product_m0823,
            channel='amazon_uk',
            snapshot_date=today,
            units_sold_30d=10,  # no variance
        )
        result = run_weekly_sanity_check(tolerance_pct=5.0)
        assert result['alerts_created'] == 0
        assert not DriftAlert.objects.exists()


# ── Tests: audit purge ───────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAuditPurge:
    def test_purges_old_success_rows_but_keeps_recent(self, product_m0823):
        from sales_velocity.services.aggregator import purge_audit_log

        old_success = SalesVelocityAPICall.objects.create(
            channel='amazon_uk', endpoint='test-old', response_status=200,
        )
        SalesVelocityAPICall.objects.filter(pk=old_success.pk).update(
            created_at=django_tz.now() - timedelta(days=20),
        )
        SalesVelocityAPICall.objects.create(
            channel='amazon_uk', endpoint='test-recent', response_status=200,
        )

        result = purge_audit_log()

        assert result['success_deleted'] == 1
        assert SalesVelocityAPICall.objects.filter(endpoint='test-recent').exists()
        assert not SalesVelocityAPICall.objects.filter(endpoint='test-old').exists()

    def test_keeps_error_rows_up_to_90_days(self, product_m0823):
        from sales_velocity.services.aggregator import purge_audit_log

        old_error = SalesVelocityAPICall.objects.create(
            channel='amazon_uk', endpoint='test-err', response_status=500,
            error_message='boom',
        )
        SalesVelocityAPICall.objects.filter(pk=old_error.pk).update(
            created_at=django_tz.now() - timedelta(days=30),
        )

        result = purge_audit_log()

        assert result['error_deleted'] == 0
        assert SalesVelocityAPICall.objects.filter(endpoint='test-err').exists()

    def test_purges_errors_older_than_90_days(self, product_m0823):
        from sales_velocity.services.aggregator import purge_audit_log

        very_old_error = SalesVelocityAPICall.objects.create(
            channel='amazon_uk', endpoint='test-ancient', response_status=500,
            error_message='boom',
        )
        SalesVelocityAPICall.objects.filter(pk=very_old_error.pk).update(
            created_at=django_tz.now() - timedelta(days=100),
        )

        result = purge_audit_log()

        assert result['error_deleted'] == 1
        assert not SalesVelocityAPICall.objects.filter(endpoint='test-ancient').exists()
