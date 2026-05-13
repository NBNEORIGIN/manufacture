"""
Tests for Phase 5: stock-aware dispatch — fulfil-from-stock and bulk-fulfil.

Covers:
  * fulfil-from-stock deducts stock + dispatches + recalculates deficit
  * fulfil with insufficient stock → 400
  * fulfil personalised order → 400
  * fulfil already-dispatched order → 400
  * fulfil order with no product → 400
  * bulk-fulfil: mix of success and failure
  * stats endpoint includes fulfillable count
  * serializer includes stock-aware fields
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from d2c.models import DispatchOrder
from products.models import Product
from stock.models import StockLevel


# d2c fulfilment is a stock-decrement path. While the Master Stock
# Google Sheet is the source of truth (settings.STOCK_PUSH_TO_SHEET_ENABLED=False),
# the decrement is gated off — see stock.services.stock_writes_allowed.
# These tests validate the post-cutover (Manufacture-canonical) semantics
# so they enable the gate via an autouse fixture. The gated-off
# production behavior is trivial (dispatch succeeds, stock untouched)
# and doesn't need dedicated test coverage beyond manual verification.
@pytest.fixture(autouse=True)
def _enable_stock_writes(settings):
    settings.STOCK_PUSH_TO_SHEET_ENABLED = True


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(username='ben', password='x')


@pytest.fixture
def authed_api(api, user):
    api.force_authenticate(user=user)
    return api


@pytest.fixture
def products(db):
    generic = Product.objects.create(
        m_number='M0500', description='A5 Slate Plaque', blank='SAVILLE',
        blank_family='A5s', is_personalised=False,
    )
    personalised = Product.objects.create(
        m_number='M0501', description='Memorial Stake Custom', blank='Stakes',
        blank_family='Stakes', is_personalised=True,
    )
    no_stock = Product.objects.create(
        m_number='M0502', description='Dick Sign', blank='DICK',
        blank_family='Dicks', is_personalised=False,
    )
    return {'generic': generic, 'personalised': personalised, 'no_stock': no_stock}


@pytest.fixture
def stock(products):
    s1 = StockLevel.objects.create(product=products['generic'], current_stock=10, optimal_stock_30d=20)
    s1.recalculate_deficit()
    s2 = StockLevel.objects.create(product=products['personalised'], current_stock=0, optimal_stock_30d=0)
    s3 = StockLevel.objects.create(product=products['no_stock'], current_stock=0, optimal_stock_30d=15)
    s3.recalculate_deficit()
    return {'generic': s1, 'personalised': s2, 'no_stock': s3}


@pytest.fixture
def orders(products, stock):
    o_fulfillable = DispatchOrder.objects.create(
        order_id='AMZ-100', channel='AmazonOD', product=products['generic'],
        sku='NBNE-A5-UK', quantity=2, status='pending',
    )
    o_personalised = DispatchOrder.objects.create(
        order_id='AMZ-101', channel='AmazonOD', product=products['personalised'],
        sku='NBNE-STAKE-UK', quantity=1, status='pending',
    )
    o_no_stock = DispatchOrder.objects.create(
        order_id='AMZ-102', channel='AmazonOD', product=products['no_stock'],
        sku='NBNE-DICK-UK', quantity=3, status='pending',
    )
    o_dispatched = DispatchOrder.objects.create(
        order_id='AMZ-103', channel='AmazonOD', product=products['generic'],
        sku='NBNE-A5-UK', quantity=1, status='dispatched',
    )
    o_no_product = DispatchOrder.objects.create(
        order_id='AMZ-104', channel='AmazonOD', product=None,
        sku='UNKNOWN-SKU', quantity=1, status='pending',
    )
    return {
        'fulfillable': o_fulfillable,
        'personalised': o_personalised,
        'no_stock': o_no_stock,
        'dispatched': o_dispatched,
        'no_product': o_no_product,
    }


# --------------------------------------------------------------------------- #
# Fulfil from stock                                                           #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestFulfilFromStock:
    def test_fulfil_deducts_stock_and_dispatches(self, authed_api, orders, stock, user):
        order = orders['fulfillable']
        resp = authed_api.post(f'/api/dispatch/{order.id}/fulfil-from-stock/')
        assert resp.status_code == 200

        body = resp.json()
        assert body['status'] == 'dispatched'
        assert body['stock_updated'] is True
        assert body['completed_at'] is not None

        # Stock deducted
        stock['generic'].refresh_from_db()
        assert stock['generic'].current_stock == 8  # 10 - 2

        # Deficit recalculated
        assert stock['generic'].stock_deficit == 12  # max(0, 20 - 8)

        # Order updated
        order.refresh_from_db()
        assert order.status == 'dispatched'
        assert order.completed_by == user

    def test_fulfil_insufficient_stock_returns_400(self, authed_api, orders):
        resp = authed_api.post(f'/api/dispatch/{orders["no_stock"].id}/fulfil-from-stock/')
        assert resp.status_code == 400
        assert 'Insufficient stock' in resp.json()['error']

    def test_fulfil_personalised_returns_400(self, authed_api, orders):
        resp = authed_api.post(f'/api/dispatch/{orders["personalised"].id}/fulfil-from-stock/')
        assert resp.status_code == 400
        assert 'personalised' in resp.json()['error'].lower()

    def test_fulfil_already_dispatched_returns_400(self, authed_api, orders):
        resp = authed_api.post(f'/api/dispatch/{orders["dispatched"].id}/fulfil-from-stock/')
        assert resp.status_code == 400
        assert 'dispatched' in resp.json()['error']

    def test_fulfil_no_product_returns_400(self, authed_api, orders):
        resp = authed_api.post(f'/api/dispatch/{orders["no_product"].id}/fulfil-from-stock/')
        assert resp.status_code == 400
        assert 'no linked product' in resp.json()['error'].lower()

    def test_fulfil_unauthenticated_still_works(self, api, orders, stock):
        """Fulfil works without auth (like mark-made), completed_by is null."""
        resp = api.post(f'/api/dispatch/{orders["fulfillable"].id}/fulfil-from-stock/')
        assert resp.status_code == 200
        orders['fulfillable'].refresh_from_db()
        assert orders['fulfillable'].completed_by is None
        assert orders['fulfillable'].status == 'dispatched'


# --------------------------------------------------------------------------- #
# Bulk fulfil                                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestBulkFulfil:
    def test_bulk_fulfil_mixed_results(self, authed_api, orders, stock):
        """
        Bulk-fulfil is intentionally lenient: it dispatches Needs-making rows
        even when stock is 0 (clamping the deduction). Only genuinely invalid
        orders (personalised, no product, wrong status) land in `failed`.
        """
        ids = [
            orders['fulfillable'].id,
            orders['personalised'].id,
            orders['no_stock'].id,
        ]
        resp = authed_api.post('/api/dispatch/bulk-fulfil/', data={'ids': ids}, format='json')
        assert resp.status_code == 200

        body = resp.json()
        # fulfillable + no_stock both dispatch (no_stock clamps to 0 deduct)
        fulfilled_ids = {f['order_id'] for f in body['fulfilled']}
        assert 'AMZ-100' in fulfilled_ids
        assert 'AMZ-102' in fulfilled_ids
        assert len(body['fulfilled']) == 2

        # Only the personalised order is rejected
        failed_ids = {f['order_id'] for f in body['failed']}
        assert failed_ids == {'AMZ-101'}
        # Stock for the no-stock product stays at 0 (nothing to deduct)
        stock['no_stock'].refresh_from_db()
        assert stock['no_stock'].current_stock == 0

    def test_bulk_fulfil_empty_ids(self, authed_api, orders):
        resp = authed_api.post('/api/dispatch/bulk-fulfil/', data={'ids': []}, format='json')
        assert resp.status_code == 400

    def test_bulk_fulfil_clamps_stock_when_short(self, authed_api, products, stock):
        """Two orders for same product — stock=10, one needs 7, one needs 5.
        Both dispatch; stock clamps to zero after the combined deduction.
        (Bulk-fulfil is lenient by design — see _deduct_stock_and_dispatch.)"""
        o1 = DispatchOrder.objects.create(
            order_id='BULK-01', channel='AmazonOD', product=products['generic'],
            sku='NBNE-A5-UK', quantity=7, status='pending',
        )
        o2 = DispatchOrder.objects.create(
            order_id='BULK-02', channel='AmazonOD', product=products['generic'],
            sku='NBNE-A5-UK', quantity=5, status='pending',
        )
        resp = authed_api.post('/api/dispatch/bulk-fulfil/', data={'ids': [o1.id, o2.id]}, format='json')
        assert resp.status_code == 200
        body = resp.json()
        # Both dispatched; failed list is empty
        assert len(body['fulfilled']) == 2
        assert body['failed'] == []
        # Stock clamped to 0 (10 - 7 = 3, then -min(5,3) = 0)
        stock['generic'].refresh_from_db()
        assert stock['generic'].current_stock == 0


# --------------------------------------------------------------------------- #
# Stats                                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestStatsWithFulfillable:
    def test_stats_includes_fulfillable(self, api, orders, stock):
        resp = api.get('/api/dispatch/stats/')
        assert resp.status_code == 200
        body = resp.json()
        # Only orders['fulfillable'] has stock and is pending + generic
        assert body['fulfillable'] == 1
        assert 'pending' in body
        assert 'total' in body


# --------------------------------------------------------------------------- #
# Serializer fields                                                           #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestSerializerStockFields:
    def test_response_includes_stock_fields(self, api, orders, stock):
        resp = api.get(f'/api/dispatch/{orders["fulfillable"].id}/')
        assert resp.status_code == 200
        body = resp.json()

        assert body['current_stock'] == 10
        assert body['can_fulfil_from_stock'] is True
        assert body['product_is_personalised'] is False
        assert body['blank'] == 'SAVILLE'
        assert body['blank_family'] == 'A5s'

    def test_personalised_order_cannot_fulfil(self, api, orders, stock):
        resp = api.get(f'/api/dispatch/{orders["personalised"].id}/')
        body = resp.json()
        assert body['can_fulfil_from_stock'] is False
        assert body['product_is_personalised'] is True

    def test_no_product_defaults(self, api, orders, stock):
        resp = api.get(f'/api/dispatch/{orders["no_product"].id}/')
        body = resp.json()
        assert body['current_stock'] == 0
        assert body['can_fulfil_from_stock'] is False
        assert body['product_is_personalised'] is False
        assert body['blank'] == ''
