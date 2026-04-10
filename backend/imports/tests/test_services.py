"""
Tests for backend/imports/services.py — the preview/confirm appliers that
turn parsed CSV rows into database mutations.

Critical invariants under test:
  * preview_only=True NEVER mutates StockLevel or DispatchOrder
  * confirm mode (preview_only=False) produces exactly the deltas promised
    by the preview
  * unknown SKUs are reported in `skipped`, not raised
  * sales_traffic aggregates units across every marketplace SKU that maps
    to the same M-number
  * zenstores is idempotent on (order_id, sku)

No production code changes in this file — only tests.
"""

from __future__ import annotations

import pytest

from imports.services import (
    APPLIERS,
    apply_fba_inventory,
    apply_restock_inventory,
    apply_sales_traffic,
    apply_zenstores,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def seeded_product(db):
    """One Product with two SKUs (UK + US) and a StockLevel row."""
    from products.models import Product, SKU
    from stock.models import StockLevel

    product = Product.objects.create(
        m_number='M0100',
        description='Test Widget',
        blank='A4s',
    )
    SKU.objects.create(product=product, sku='NBNE-A-UK', channel='UK')
    SKU.objects.create(product=product, sku='NBNE-A-US', channel='US')
    stock = StockLevel.objects.create(
        product=product,
        current_stock=10,
        fba_stock=5,
        sixty_day_sales=20,
        optimal_stock_30d=50,
        stock_deficit=40,
    )
    return {'product': product, 'stock': stock}


@pytest.fixture
def product_no_stock_row(db):
    """A Product + SKU but NO StockLevel — exercises the 'no stock record' skip."""
    from products.models import Product, SKU

    product = Product.objects.create(
        m_number='M0200',
        description='Stock-less Widget',
        blank='A5s',
    )
    SKU.objects.create(product=product, sku='NBNE-B-UK', channel='UK')
    return product


# --------------------------------------------------------------------------- #
# apply_fba_inventory                                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestApplyFBAInventory:
    def test_preview_does_not_mutate(self, seeded_product):
        parsed = {'items': [
            {'sku': 'NBNE-A-UK', 'asin': '', 'fnsku': '', 'fba_quantity': 99},
        ]}
        result = apply_fba_inventory(parsed, preview_only=True)

        # Reload to confirm no write happened
        seeded_product['stock'].refresh_from_db()
        assert seeded_product['stock'].fba_stock == 5  # unchanged
        assert result['preview'] is True
        assert len(result['changes']) == 1
        assert result['changes'][0] == {
            'm_number': 'M0100',
            'sku': 'NBNE-A-UK',
            'field': 'fba_stock',
            'old': 5,
            'new': 99,
        }

    def test_confirm_mutates(self, seeded_product):
        parsed = {'items': [
            {'sku': 'NBNE-A-UK', 'asin': '', 'fnsku': '', 'fba_quantity': 99},
        ]}
        result = apply_fba_inventory(parsed, preview_only=False)
        seeded_product['stock'].refresh_from_db()
        assert seeded_product['stock'].fba_stock == 99
        assert result['preview'] is False
        assert len(result['changes']) == 1

    def test_unknown_sku_is_skipped_not_raised(self, seeded_product):
        parsed = {'items': [
            {'sku': 'UNKNOWN-SKU', 'asin': '', 'fnsku': '', 'fba_quantity': 10},
        ]}
        result = apply_fba_inventory(parsed, preview_only=True)
        assert result['changes'] == []
        assert len(result['skipped']) == 1
        assert result['skipped'][0]['sku'] == 'UNKNOWN-SKU'
        assert result['skipped'][0]['reason'] == 'Unknown SKU'

    def test_no_stock_record_is_skipped(self, product_no_stock_row):
        parsed = {'items': [
            {'sku': 'NBNE-B-UK', 'asin': '', 'fnsku': '', 'fba_quantity': 7},
        ]}
        result = apply_fba_inventory(parsed, preview_only=True)
        assert result['changes'] == []
        assert len(result['skipped']) == 1
        assert 'No stock record' in result['skipped'][0]['reason']

    def test_unchanged_value_produces_no_change_row(self, seeded_product):
        parsed = {'items': [
            {'sku': 'NBNE-A-UK', 'asin': '', 'fnsku': '', 'fba_quantity': 5},
        ]}
        result = apply_fba_inventory(parsed, preview_only=True)
        assert result['changes'] == []
        assert result['total_items'] == 1


# --------------------------------------------------------------------------- #
# apply_sales_traffic                                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestApplySalesTraffic:
    def test_aggregates_across_marketplaces_for_same_product(self, seeded_product):
        # UK + US both resolve to M0100 — expect sixty_day_sales to become 8
        parsed = {'items': [
            {'sku': 'NBNE-A-UK', 'units_ordered': 5, 'sessions': 100},
            {'sku': 'NBNE-A-US', 'units_ordered': 3, 'sessions': 50},
        ]}
        result = apply_sales_traffic(parsed, preview_only=True)
        assert len(result['changes']) == 1
        change = result['changes'][0]
        assert change['m_number'] == 'M0100'
        assert change['field'] == 'sixty_day_sales'
        assert change['old'] == 20
        assert change['new'] == 8

    def test_preview_does_not_mutate_sales(self, seeded_product):
        parsed = {'items': [
            {'sku': 'NBNE-A-UK', 'units_ordered': 99, 'sessions': 0},
        ]}
        apply_sales_traffic(parsed, preview_only=True)
        seeded_product['stock'].refresh_from_db()
        assert seeded_product['stock'].sixty_day_sales == 20  # unchanged

    def test_confirm_mutates_and_recalculates_deficit(self, seeded_product):
        # current_stock=10, optimal_stock_30d=50 -> deficit should recalc to 40
        # (unchanged in this case because we don't touch current/optimal, but
        # the recalculate_deficit() hook should still fire without error)
        parsed = {'items': [
            {'sku': 'NBNE-A-UK', 'units_ordered': 12, 'sessions': 0},
        ]}
        apply_sales_traffic(parsed, preview_only=False)
        seeded_product['stock'].refresh_from_db()
        assert seeded_product['stock'].sixty_day_sales == 12
        assert seeded_product['stock'].stock_deficit == 40

    def test_unknown_sku_skipped(self, seeded_product):
        parsed = {'items': [
            {'sku': 'UNKNOWN', 'units_ordered': 5, 'sessions': 0},
        ]}
        result = apply_sales_traffic(parsed, preview_only=True)
        assert result['changes'] == []
        assert len(result['skipped']) == 1


# --------------------------------------------------------------------------- #
# apply_restock_inventory                                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestApplyRestockInventory:
    def test_preview_reports_restock_recommendation(self, seeded_product):
        parsed = {'items': [
            {'sku': 'NBNE-A-UK', 'asin': 'B0001', 'available': 22, 'restock_quantity': 100},
        ]}
        result = apply_restock_inventory(parsed, preview_only=True)
        assert len(result['changes']) == 1
        change = result['changes'][0]
        assert change['old'] == 5
        assert change['new'] == 22
        assert change['restock_recommended'] == 100

    def test_confirm_writes_available_to_fba_stock(self, seeded_product):
        parsed = {'items': [
            {'sku': 'NBNE-A-UK', 'asin': 'B0001', 'available': 22, 'restock_quantity': 100},
        ]}
        apply_restock_inventory(parsed, preview_only=False)
        seeded_product['stock'].refresh_from_db()
        assert seeded_product['stock'].fba_stock == 22


# --------------------------------------------------------------------------- #
# apply_zenstores                                                             #
# --------------------------------------------------------------------------- #


@pytest.fixture
def dispatch_base_item(seeded_product):
    """A baseline parsed Zenstores item resolving to seeded_product."""
    return {
        'order_id': '123-45-67',
        'sku': 'NBNE-A-UK',
        'quantity': 2,
        'flags': 'Urgent',
        'channel': 'AmazonOD',
        'order_date': '2026-04-10T08:00:00Z',
        'customer_name': 'Jane Smith',
        'description': 'Gorgeous Sign',
    }


@pytest.mark.django_db
class TestApplyZenstores:
    def test_preview_does_not_create_dispatch_orders(self, dispatch_base_item):
        from d2c.models import DispatchOrder

        parsed = {'items': [dispatch_base_item]}
        result = apply_zenstores(parsed, preview_only=True)

        assert DispatchOrder.objects.count() == 0
        assert len(result['changes']) == 1
        assert result['changes'][0]['order_id'] == '123-45-67'
        assert result['changes'][0]['m_number'] == 'M0100'

    def test_confirm_creates_dispatch_order(self, dispatch_base_item):
        from d2c.models import DispatchOrder

        parsed = {'items': [dispatch_base_item]}
        apply_zenstores(parsed, preview_only=False)

        assert DispatchOrder.objects.count() == 1
        order = DispatchOrder.objects.first()
        assert order.order_id == '123-45-67'
        assert order.sku == 'NBNE-A-UK'
        assert order.product.m_number == 'M0100'
        assert order.quantity == 2
        assert order.flags == 'Urgent'
        assert order.channel == 'AmazonOD'
        assert order.customer_name == 'Jane Smith'
        assert order.order_date is not None  # parsed successfully
        assert order.status == 'pending'  # default

    def test_idempotent_on_order_id_plus_sku(self, dispatch_base_item):
        from d2c.models import DispatchOrder

        parsed = {'items': [dispatch_base_item]}
        apply_zenstores(parsed, preview_only=False)
        assert DispatchOrder.objects.count() == 1

        # Re-apply the SAME file → no new rows, one skipped
        result = apply_zenstores(parsed, preview_only=False)
        assert DispatchOrder.objects.count() == 1
        assert len(result['changes']) == 0
        assert len(result['skipped']) == 1
        assert 'already imported' in result['skipped'][0]['reason']

    def test_unknown_sku_still_creates_order_with_null_product(self, dispatch_base_item):
        """Orders with unmatched SKUs shouldn't block the dispatch queue —
        Gabby needs to see them. Product FK is allowed to be null on DispatchOrder."""
        from d2c.models import DispatchOrder

        dispatch_base_item['sku'] = 'UNKNOWN-SKU-99'
        parsed = {'items': [dispatch_base_item]}
        apply_zenstores(parsed, preview_only=False)

        assert DispatchOrder.objects.count() == 1
        order = DispatchOrder.objects.first()
        assert order.sku == 'UNKNOWN-SKU-99'
        assert order.product is None

    def test_preview_shape_includes_unknown_m_number_as_empty(
        self, dispatch_base_item
    ):
        dispatch_base_item['sku'] = 'UNKNOWN-SKU-99'
        parsed = {'items': [dispatch_base_item]}
        result = apply_zenstores(parsed, preview_only=True)
        assert result['changes'][0]['m_number'] == ''

    def test_bad_date_string_does_not_crash(self, dispatch_base_item):
        from d2c.models import DispatchOrder

        dispatch_base_item['order_date'] = 'not-a-real-date'
        parsed = {'items': [dispatch_base_item]}
        apply_zenstores(parsed, preview_only=False)

        order = DispatchOrder.objects.first()
        assert order is not None
        assert order.order_date is None  # gracefully None'd


# --------------------------------------------------------------------------- #
# Applier registry                                                            #
# --------------------------------------------------------------------------- #


class TestApplierRegistry:
    def test_all_four_types_registered(self):
        assert set(APPLIERS.keys()) == {
            'fba_inventory',
            'sales_traffic',
            'restock',
            'zenstores',
        }
