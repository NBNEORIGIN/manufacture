"""
HTTP tests for /api/dispatch/ (DispatchOrderViewSet).

Covers:
  * list + filter by status + filter by channel
  * create with m_number in body resolves product FK
  * mark-made flips status + stamps completed_at / completed_by
  * mark-dispatched flips status
  * stats aggregates by status
  * search across order_id / sku / description / flags / customer_name / m_number

No production code changes in this file — only tests.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def authed_api(api, db):
    user = User.objects.create_user(username='gabby', password='x')
    api.force_authenticate(user=user)
    return api, user


@pytest.fixture
def products(db):
    from products.models import Product
    a = Product.objects.create(m_number='M0400', description='Memorial Stake', blank='Stakes')
    b = Product.objects.create(m_number='M0401', description='A5 Plaque', blank='A5s')
    return {'a': a, 'b': b}


@pytest.fixture
def orders(db, products):
    from d2c.models import DispatchOrder

    o1 = DispatchOrder.objects.create(
        order_id='AMZ-001',
        channel='AmazonOD',
        product=products['a'],
        sku='NBNE-STAKE-UK',
        description='Memorial stake for John',
        quantity=1,
        status='pending',
        flags='Urgent',
        customer_name='Jane Smith',
    )
    o2 = DispatchOrder.objects.create(
        order_id='ETSY-002',
        channel='NorthByNorthEastSign',
        product=products['b'],
        sku='NBNE-A5-UK',
        description='A5 plaque',
        quantity=2,
        status='made',
    )
    o3 = DispatchOrder.objects.create(
        order_id='AMZ-003',
        channel='AmazonOD',
        product=products['b'],
        sku='NBNE-A5-UK',
        description='Another A5 plaque',
        quantity=1,
        status='dispatched',
    )
    return {'o1': o1, 'o2': o2, 'o3': o3}


# --------------------------------------------------------------------------- #
# List + filters                                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestDispatchList:
    def test_list_all(self, api, orders):
        resp = api.get('/api/dispatch/')
        assert resp.status_code == 200
        body = resp.json()
        # Response may be paginated ({count, results}) or a plain list
        results = body['results'] if isinstance(body, dict) else body
        assert len(results) == 3

    def test_filter_by_status(self, api, orders):
        resp = api.get('/api/dispatch/?status=pending')
        body = resp.json()
        results = body['results'] if isinstance(body, dict) else body
        assert len(results) == 1
        assert results[0]['order_id'] == 'AMZ-001'

    def test_filter_by_channel(self, api, orders):
        resp = api.get('/api/dispatch/?channel=AmazonOD')
        body = resp.json()
        results = body['results'] if isinstance(body, dict) else body
        assert len(results) == 2
        order_ids = {r['order_id'] for r in results}
        assert order_ids == {'AMZ-001', 'AMZ-003'}

    def test_search_by_order_id(self, api, orders):
        resp = api.get('/api/dispatch/?search=ETSY-002')
        body = resp.json()
        results = body['results'] if isinstance(body, dict) else body
        assert len(results) == 1
        assert results[0]['sku'] == 'NBNE-A5-UK'

    def test_search_by_customer_name(self, api, orders):
        resp = api.get('/api/dispatch/?search=Jane')
        body = resp.json()
        results = body['results'] if isinstance(body, dict) else body
        assert len(results) == 1
        assert results[0]['order_id'] == 'AMZ-001'

    def test_search_by_m_number(self, api, orders):
        resp = api.get('/api/dispatch/?search=M0400')
        body = resp.json()
        results = body['results'] if isinstance(body, dict) else body
        assert len(results) == 1
        assert results[0]['order_id'] == 'AMZ-001'

    def test_list_includes_m_number(self, api, orders):
        resp = api.get('/api/dispatch/?status=pending')
        body = resp.json()
        results = body['results'] if isinstance(body, dict) else body
        assert results[0]['m_number'] == 'M0400'


# --------------------------------------------------------------------------- #
# Create                                                                      #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestDispatchCreate:
    def test_create_with_m_number_resolves_product(self, api, products):
        payload = {
            'order_id': 'MANUAL-001',
            'sku': 'ANY-SKU',
            'quantity': 1,
            'status': 'pending',
            'm_number': 'M0400',  # read by perform_create
            'channel': 'manual',
        }
        resp = api.post('/api/dispatch/', data=payload, format='json')
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body['m_number'] == 'M0400'

        from d2c.models import DispatchOrder
        order = DispatchOrder.objects.get(order_id='MANUAL-001')
        assert order.product is not None
        assert order.product.m_number == 'M0400'

    def test_create_with_unknown_m_number_still_succeeds(self, api):
        payload = {
            'order_id': 'MANUAL-002',
            'sku': 'ANY-SKU',
            'quantity': 1,
            'status': 'pending',
            'm_number': 'M9999',  # doesn't exist
            'channel': 'manual',
        }
        resp = api.post('/api/dispatch/', data=payload, format='json')
        assert resp.status_code == 201
        from d2c.models import DispatchOrder
        order = DispatchOrder.objects.get(order_id='MANUAL-002')
        assert order.product is None


# --------------------------------------------------------------------------- #
# Actions                                                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestDispatchActions:
    def test_mark_made_sets_status_and_stamps_completion(self, authed_api, orders):
        api, user = authed_api
        o = orders['o1']
        resp = api.post(f'/api/dispatch/{o.id}/mark-made/')
        assert resp.status_code == 200
        body = resp.json()
        assert body['status'] == 'made'
        assert body['completed_at'] is not None
        # completed_by stamped to authed user
        o.refresh_from_db()
        assert o.status == 'made'
        assert o.completed_at is not None
        assert o.completed_by == user

    def test_mark_made_unauthenticated_leaves_completed_by_null(self, api, orders):
        o = orders['o1']
        resp = api.post(f'/api/dispatch/{o.id}/mark-made/')
        assert resp.status_code == 200
        o.refresh_from_db()
        assert o.status == 'made'
        assert o.completed_at is not None
        assert o.completed_by is None

    def test_mark_dispatched(self, api, orders):
        o = orders['o2']  # currently 'made'
        resp = api.post(f'/api/dispatch/{o.id}/mark-dispatched/')
        assert resp.status_code == 200
        assert resp.json()['status'] == 'dispatched'
        o.refresh_from_db()
        assert o.status == 'dispatched'


# --------------------------------------------------------------------------- #
# Stats                                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestDispatchStats:
    def test_stats_shape(self, api, orders):
        resp = api.get('/api/dispatch/stats/')
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            'pending': 1,
            'in_progress': 0,
            'made': 1,
            'dispatched': 1,
            'total': 3,
            'fulfillable': 0,
        }

    def test_stats_empty_db(self, api, db):
        resp = api.get('/api/dispatch/stats/')
        assert resp.status_code == 200
        body = resp.json()
        assert body['total'] == 0
        assert body['pending'] == 0
