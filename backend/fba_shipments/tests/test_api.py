"""
End-to-end tests for the FBA Shipment REST API.

Uses DRF's APIClient; Django-Q `kick_off` is patched so no real tasks
are enqueued. The goal is to exercise validation, URL routing, and
plan state transitions from HTTP level, not re-test workflow internals
(those are covered in test_workflow.py).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from fba_shipments.models import (
    FBAAPICall,
    FBABox,
    FBABoxItem,
    FBAShipment,
    FBAShipmentPlan,
    FBAShipmentPlanItem,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture(autouse=True)
def patched_kickoff():
    """Auto-applied: no real Django-Q tasks during API tests."""
    with patch('fba_shipments.services.workflow.kick_off') as mocked:
        yield mocked


@pytest.fixture
def product_ready(db):
    """A Product with shipping dimensions + an FBA-eligible SKU + FNSKU barcode."""
    from products.models import Product, SKU
    from barcodes.models import ProductBarcode
    product = Product.objects.create(
        m_number='M1234',
        description='Ready Product',
        blank='A4s',
        shipping_length_cm=Decimal('30'),
        shipping_width_cm=Decimal('20'),
        shipping_height_cm=Decimal('15'),
        shipping_weight_g=2500,
    )
    sku = SKU.objects.create(
        product=product, sku='NBNE-RDY-UK-01', channel='UK', asin='B00RDYASIN',
    )
    ProductBarcode.objects.create(
        product=product,
        marketplace='UK',
        barcode_type='FNSKU',
        barcode_value='X00RDYFN001',
        label_title='Ready Product',
    )
    return {'product': product, 'sku': sku}


@pytest.fixture
def product_no_fnsku(db):
    """A Product with dims but NO FNSKU — should fail submit validation."""
    from products.models import Product, SKU
    product = Product.objects.create(
        m_number='M2000',
        description='No FNSKU Product',
        blank='A5s',
        shipping_length_cm=Decimal('10'),
        shipping_width_cm=Decimal('10'),
        shipping_height_cm=Decimal('10'),
        shipping_weight_g=500,
    )
    sku = SKU.objects.create(
        product=product, sku='NBNE-NOF-UK-01', channel='UK',
    )
    return {'product': product, 'sku': sku}


@pytest.fixture
def product_no_dims(db):
    """A Product with FNSKU but no shipping dims."""
    from products.models import Product, SKU
    from barcodes.models import ProductBarcode
    product = Product.objects.create(
        m_number='M3000',
        description='No Dims Product',
        blank='A4s',
    )
    sku = SKU.objects.create(
        product=product, sku='NBNE-NDM-UK-01', channel='UK',
    )
    ProductBarcode.objects.create(
        product=product, marketplace='UK',
        barcode_type='FNSKU', barcode_value='X00NDMFN001',
    )
    return {'product': product, 'sku': sku}


@pytest.fixture
def draft_plan(db):
    return FBAShipmentPlan.objects.create(
        name='Draft UK Plan',
        marketplace='UK',
        ship_from_address={'name': 'NBNE', 'countryCode': 'GB'},
        status='draft',
    )


# --------------------------------------------------------------------------- #
# Plan CRUD                                                                   #
# --------------------------------------------------------------------------- #


class TestPlanCRUD:
    def test_create_plan_with_default_ship_from(self, api, db):
        resp = api.post('/api/fba/plans/', {
            'name': 'UK Test', 'marketplace': 'UK',
        }, format='json')
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body['name'] == 'UK Test'
        assert body['marketplace'] == 'UK'
        assert body['status'] == 'draft'
        assert 'ship_from_address' in body

    def test_create_plan_with_explicit_ship_from(self, api, db):
        resp = api.post('/api/fba/plans/', {
            'name': 'Custom Ship From',
            'marketplace': 'UK',
            'ship_from_address': {'name': 'Test', 'countryCode': 'GB'},
        }, format='json')
        assert resp.status_code == 201
        assert resp.json()['ship_from_address']['name'] == 'Test'

    def test_list_plans_with_filters(self, api, db):
        FBAShipmentPlan.objects.create(
            name='UK1', marketplace='UK',
            ship_from_address={}, status='draft',
        )
        FBAShipmentPlan.objects.create(
            name='US1', marketplace='US',
            ship_from_address={}, status='ready_to_ship',
        )
        resp = api.get('/api/fba/plans/?marketplace=UK')
        assert resp.status_code == 200
        results = resp.json()['results']
        assert len(results) == 1
        assert results[0]['name'] == 'UK1'

    def test_retrieve_plan_detail_has_nested_arrays(self, api, draft_plan):
        resp = api.get(f'/api/fba/plans/{draft_plan.id}/')
        assert resp.status_code == 200
        body = resp.json()
        for key in ('items', 'boxes', 'shipments', 'recent_api_calls', 'error_log'):
            assert key in body

    def test_patch_plan_name_allowed_in_draft(self, api, draft_plan):
        resp = api.patch(
            f'/api/fba/plans/{draft_plan.id}/',
            {'name': 'Renamed'}, format='json',
        )
        assert resp.status_code == 200
        draft_plan.refresh_from_db()
        assert draft_plan.name == 'Renamed'

    def test_patch_plan_rejected_after_items_added(self, api, draft_plan):
        draft_plan.status = 'items_added'
        draft_plan.save()
        resp = api.patch(
            f'/api/fba/plans/{draft_plan.id}/',
            {'name': 'Too Late'}, format='json',
        )
        assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Plan cancellation                                                           #
# --------------------------------------------------------------------------- #


class TestPlanCancel:
    def test_cancel_pre_api_plan(self, api, draft_plan):
        resp = api.delete(f'/api/fba/plans/{draft_plan.id}/')
        assert resp.status_code == 204
        draft_plan.refresh_from_db()
        assert draft_plan.status == 'cancelled'

    def test_cancel_with_inbound_plan_id_calls_amazon(self, api, draft_plan):
        draft_plan.status = 'plan_created'
        draft_plan.inbound_plan_id = 'wf-123'
        draft_plan.save()
        with patch(
            'fba_shipments.services.sp_api_client.FBAInboundClient'
        ) as mock_client_cls:
            mock_inst = mock_client_cls.return_value
            resp = api.delete(f'/api/fba/plans/{draft_plan.id}/')
        assert resp.status_code == 204
        mock_inst.cancel_inbound_plan.assert_called_once_with('wf-123')
        draft_plan.refresh_from_db()
        assert draft_plan.status == 'cancelled'

    def test_cancel_api_failure_still_marks_cancelled_locally(
        self, api, draft_plan,
    ):
        draft_plan.status = 'plan_created'
        draft_plan.inbound_plan_id = 'wf-boom'
        draft_plan.save()
        with patch(
            'fba_shipments.services.sp_api_client.FBAInboundClient'
        ) as mock_client_cls:
            mock_client_cls.return_value.cancel_inbound_plan.side_effect = (
                RuntimeError('boom')
            )
            resp = api.delete(f'/api/fba/plans/{draft_plan.id}/')
        assert resp.status_code == 204
        draft_plan.refresh_from_db()
        assert draft_plan.status == 'cancelled'


# --------------------------------------------------------------------------- #
# Items                                                                       #
# --------------------------------------------------------------------------- #


class TestPlanItems:
    def test_add_items_snapshots_fnsku(self, api, draft_plan, product_ready):
        resp = api.post(
            f'/api/fba/plans/{draft_plan.id}/items/',
            {'items': [{'sku_id': product_ready['sku'].id, 'quantity': 10}]},
            format='json',
        )
        assert resp.status_code == 201, resp.content
        item = FBAShipmentPlanItem.objects.get(plan=draft_plan)
        assert item.quantity == 10
        assert item.msku == 'NBNE-RDY-UK-01'
        assert item.fnsku == 'X00RDYFN001'

    def test_add_items_without_fnsku_stores_empty_string(
        self, api, draft_plan, product_no_fnsku,
    ):
        """
        The items endpoint does NOT reject missing FNSKUs — that check is
        deferred to submit(). This keeps the add-items flow responsive
        while FNSKU sync is running in the background.
        """
        resp = api.post(
            f'/api/fba/plans/{draft_plan.id}/items/',
            {'items': [{'sku_id': product_no_fnsku['sku'].id, 'quantity': 5}]},
            format='json',
        )
        assert resp.status_code == 201
        item = FBAShipmentPlanItem.objects.get(plan=draft_plan)
        assert item.fnsku == ''

    def test_add_items_bulk_update(self, api, draft_plan, product_ready):
        api.post(
            f'/api/fba/plans/{draft_plan.id}/items/',
            {'items': [{'sku_id': product_ready['sku'].id, 'quantity': 10}]},
            format='json',
        )
        # Re-add should UPDATE quantity, not create a second row
        api.post(
            f'/api/fba/plans/{draft_plan.id}/items/',
            {'items': [{'sku_id': product_ready['sku'].id, 'quantity': 20}]},
            format='json',
        )
        assert draft_plan.items.count() == 1
        assert draft_plan.items.first().quantity == 20

    def test_add_items_rejected_when_not_draft(self, api, draft_plan, product_ready):
        draft_plan.status = 'items_added'
        draft_plan.save()
        resp = api.post(
            f'/api/fba/plans/{draft_plan.id}/items/',
            {'items': [{'sku_id': product_ready['sku'].id, 'quantity': 1}]},
            format='json',
        )
        assert resp.status_code == 400

    def test_remove_item_in_draft(self, api, draft_plan, product_ready):
        item = FBAShipmentPlanItem.objects.create(
            plan=draft_plan, sku=product_ready['sku'], quantity=5,
            msku='NBNE-RDY-UK-01', fnsku='X00RDYFN001',
        )
        resp = api.delete(
            f'/api/fba/plans/{draft_plan.id}/items/{item.id}/',
        )
        assert resp.status_code == 204
        assert draft_plan.items.count() == 0


# --------------------------------------------------------------------------- #
# Boxes                                                                       #
# --------------------------------------------------------------------------- #


class TestPlanBoxes:
    def test_add_box_with_contents(self, api, draft_plan, product_ready):
        item = FBAShipmentPlanItem.objects.create(
            plan=draft_plan, sku=product_ready['sku'], quantity=10,
            msku='NBNE-RDY-UK-01', fnsku='X00RDYFN001',
        )
        resp = api.post(
            f'/api/fba/plans/{draft_plan.id}/boxes/',
            {
                'box_number': 1,
                'length_cm': '30.0', 'width_cm': '20.0',
                'height_cm': '15.0', 'weight_kg': '2.5',
                'contents': [{'plan_item_id': item.id, 'quantity': 10}],
            },
            format='json',
        )
        assert resp.status_code == 201, resp.content
        assert draft_plan.boxes.count() == 1
        assert draft_plan.boxes.first().contents.count() == 1

    def test_add_box_rejects_empty_contents(self, api, draft_plan):
        resp = api.post(
            f'/api/fba/plans/{draft_plan.id}/boxes/',
            {
                'box_number': 1,
                'length_cm': '30.0', 'width_cm': '20.0',
                'height_cm': '15.0', 'weight_kg': '2.5',
                'contents': [],
            },
            format='json',
        )
        assert resp.status_code == 400

    def test_delete_box(self, api, draft_plan):
        box = FBABox.objects.create(
            plan=draft_plan, box_number=1,
            length_cm=Decimal('30'), width_cm=Decimal('20'),
            height_cm=Decimal('15'), weight_kg=Decimal('2.5'),
        )
        resp = api.delete(f'/api/fba/plans/{draft_plan.id}/boxes/{box.id}/')
        assert resp.status_code == 204
        assert draft_plan.boxes.count() == 0


# --------------------------------------------------------------------------- #
# Submit                                                                      #
# --------------------------------------------------------------------------- #


def _fully_populate(plan, sku, qty=10):
    """Helper: add an item + a matching box so the plan is submit-ready."""
    item = FBAShipmentPlanItem.objects.create(
        plan=plan, sku=sku, quantity=qty,
        msku=sku.sku, fnsku='X00RDYFN001',
    )
    box = FBABox.objects.create(
        plan=plan, box_number=1,
        length_cm=Decimal('30'), width_cm=Decimal('20'),
        height_cm=Decimal('15'), weight_kg=Decimal('2.5'),
    )
    FBABoxItem.objects.create(box=box, plan_item=item, quantity=qty)
    return item, box


class TestPlanSubmit:
    def test_submit_happy_path(
        self, api, draft_plan, product_ready, patched_kickoff,
    ):
        _fully_populate(draft_plan, product_ready['sku'])
        resp = api.post(f'/api/fba/plans/{draft_plan.id}/submit/')
        assert resp.status_code == 200, resp.content
        draft_plan.refresh_from_db()
        assert draft_plan.status == 'items_added'
        patched_kickoff.assert_called_once()

    def test_submit_fails_with_no_items(self, api, draft_plan, patched_kickoff):
        resp = api.post(f'/api/fba/plans/{draft_plan.id}/submit/')
        assert resp.status_code == 400
        errors = resp.json()['errors']
        assert any('no items' in e.lower() for e in errors)
        patched_kickoff.assert_not_called()

    def test_submit_fails_when_item_missing_fnsku(
        self, api, draft_plan, product_no_fnsku, patched_kickoff,
    ):
        item = FBAShipmentPlanItem.objects.create(
            plan=draft_plan, sku=product_no_fnsku['sku'],
            quantity=10, msku='NBNE-NOF-UK-01', fnsku='',
        )
        box = FBABox.objects.create(
            plan=draft_plan, box_number=1,
            length_cm=Decimal('30'), width_cm=Decimal('20'),
            height_cm=Decimal('15'), weight_kg=Decimal('2.5'),
        )
        FBABoxItem.objects.create(box=box, plan_item=item, quantity=10)
        resp = api.post(f'/api/fba/plans/{draft_plan.id}/submit/')
        assert resp.status_code == 400
        errors = resp.json()['errors']
        assert any('FNSKU' in e for e in errors)
        patched_kickoff.assert_not_called()

    def test_submit_fails_when_product_missing_dims(
        self, api, draft_plan, product_no_dims, patched_kickoff,
    ):
        item = FBAShipmentPlanItem.objects.create(
            plan=draft_plan, sku=product_no_dims['sku'],
            quantity=5, msku='NBNE-NDM-UK-01', fnsku='X00NDMFN001',
        )
        box = FBABox.objects.create(
            plan=draft_plan, box_number=1,
            length_cm=Decimal('30'), width_cm=Decimal('20'),
            height_cm=Decimal('15'), weight_kg=Decimal('2.5'),
        )
        FBABoxItem.objects.create(box=box, plan_item=item, quantity=5)
        resp = api.post(f'/api/fba/plans/{draft_plan.id}/submit/')
        assert resp.status_code == 400
        errors = resp.json()['errors']
        assert any('shipping dimensions' in e for e in errors)

    def test_submit_fails_when_box_quantity_mismatch(
        self, api, draft_plan, product_ready, patched_kickoff,
    ):
        item = FBAShipmentPlanItem.objects.create(
            plan=draft_plan, sku=product_ready['sku'], quantity=10,
            msku='NBNE-RDY-UK-01', fnsku='X00RDYFN001',
        )
        box = FBABox.objects.create(
            plan=draft_plan, box_number=1,
            length_cm=Decimal('30'), width_cm=Decimal('20'),
            height_cm=Decimal('15'), weight_kg=Decimal('2.5'),
        )
        FBABoxItem.objects.create(box=box, plan_item=item, quantity=5)  # short
        resp = api.post(f'/api/fba/plans/{draft_plan.id}/submit/')
        assert resp.status_code == 400
        errors = resp.json()['errors']
        assert any('does not match' in e for e in errors)

    def test_submit_rejected_outside_draft(
        self, api, draft_plan, product_ready, patched_kickoff,
    ):
        _fully_populate(draft_plan, product_ready['sku'])
        draft_plan.status = 'items_added'
        draft_plan.save()
        resp = api.post(f'/api/fba/plans/{draft_plan.id}/submit/')
        assert resp.status_code == 400
        patched_kickoff.assert_not_called()


# --------------------------------------------------------------------------- #
# Pick option endpoints                                                       #
# --------------------------------------------------------------------------- #


class TestPickOptions:
    def test_pick_packing_option_happy(
        self, api, draft_plan, patched_kickoff,
    ):
        draft_plan.status = 'packing_options_ready'
        draft_plan.packing_options_snapshot = {
            'packingOptions': [
                {'packingOptionId': 'po-A'}, {'packingOptionId': 'po-B'},
            ],
        }
        draft_plan.save()
        resp = api.post(
            f'/api/fba/plans/{draft_plan.id}/pick-packing-option/',
            {'packing_option_id': 'po-B'}, format='json',
        )
        assert resp.status_code == 200
        draft_plan.refresh_from_db()
        assert draft_plan.selected_packing_option_id == 'po-B'
        patched_kickoff.assert_called_once()

    def test_pick_packing_option_rejects_unknown_id(
        self, api, draft_plan, patched_kickoff,
    ):
        draft_plan.status = 'packing_options_ready'
        draft_plan.packing_options_snapshot = {
            'packingOptions': [{'packingOptionId': 'po-A'}],
        }
        draft_plan.save()
        resp = api.post(
            f'/api/fba/plans/{draft_plan.id}/pick-packing-option/',
            {'packing_option_id': 'po-NOT-REAL'}, format='json',
        )
        assert resp.status_code == 400
        patched_kickoff.assert_not_called()

    def test_pick_packing_option_rejected_in_wrong_status(
        self, api, draft_plan, patched_kickoff,
    ):
        resp = api.post(
            f'/api/fba/plans/{draft_plan.id}/pick-packing-option/',
            {'packing_option_id': 'po-A'}, format='json',
        )
        assert resp.status_code == 400

    def test_pick_placement_option_happy(
        self, api, draft_plan, patched_kickoff,
    ):
        draft_plan.status = 'placement_options_ready'
        draft_plan.placement_options_snapshot = {
            'placementOptions': [{'placementOptionId': 'pl-1'}],
        }
        draft_plan.save()
        resp = api.post(
            f'/api/fba/plans/{draft_plan.id}/pick-placement-option/',
            {'placement_option_id': 'pl-1'}, format='json',
        )
        assert resp.status_code == 200
        draft_plan.refresh_from_db()
        assert draft_plan.selected_placement_option_id == 'pl-1'


# --------------------------------------------------------------------------- #
# Retry                                                                       #
# --------------------------------------------------------------------------- #


class TestRetry:
    def test_retry_defaults_to_last_error_step(
        self, api, draft_plan, patched_kickoff,
    ):
        draft_plan.status = 'error'
        draft_plan.error_log = [{
            'at': '2026-04-10T12:00:00', 'step': 'packing_generating',
            'message': 'x', 'type': 'RuntimeError',
        }]
        draft_plan.save()
        resp = api.post(f'/api/fba/plans/{draft_plan.id}/retry/', format='json')
        assert resp.status_code == 200
        draft_plan.refresh_from_db()
        assert draft_plan.status == 'packing_generating'
        patched_kickoff.assert_called_once()

    def test_retry_with_explicit_rewind_to(
        self, api, draft_plan, patched_kickoff,
    ):
        draft_plan.status = 'error'
        draft_plan.save()
        resp = api.post(
            f'/api/fba/plans/{draft_plan.id}/retry/',
            {'rewind_to': 'items_added'}, format='json',
        )
        assert resp.status_code == 200
        draft_plan.refresh_from_db()
        assert draft_plan.status == 'items_added'

    def test_retry_rejects_terminal_rewind_target(
        self, api, draft_plan, patched_kickoff,
    ):
        draft_plan.status = 'error'
        draft_plan.save()
        resp = api.post(
            f'/api/fba/plans/{draft_plan.id}/retry/',
            {'rewind_to': 'cancelled'}, format='json',
        )
        assert resp.status_code == 400

    def test_retry_rejected_when_not_in_error(self, api, draft_plan):
        resp = api.post(f'/api/fba/plans/{draft_plan.id}/retry/')
        assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Dispatch                                                                    #
# --------------------------------------------------------------------------- #


class TestDispatch:
    def test_dispatch_captures_tracking_and_advances_plan(self, api, draft_plan):
        draft_plan.status = 'ready_to_ship'
        draft_plan.save()
        shipment = FBAShipment.objects.create(
            plan=draft_plan, shipment_id='sh-1',
            shipment_confirmation_id='FBA15ABCDEFG',
        )
        resp = api.post(
            f'/api/fba/plans/{draft_plan.id}/shipments/{shipment.id}/dispatch/',
            {'carrier_name': 'Evri', 'tracking_number': 'H001XYZ'},
            format='json',
        )
        assert resp.status_code == 200
        shipment.refresh_from_db()
        assert shipment.carrier_name == 'Evri'
        assert shipment.tracking_number == 'H001XYZ'
        assert shipment.dispatched_at is not None
        draft_plan.refresh_from_db()
        assert draft_plan.status == 'dispatched'

    def test_dispatch_multi_shipment_partial_does_not_advance(self, api, draft_plan):
        draft_plan.status = 'ready_to_ship'
        draft_plan.save()
        s1 = FBAShipment.objects.create(plan=draft_plan, shipment_id='sh-1')
        FBAShipment.objects.create(plan=draft_plan, shipment_id='sh-2')
        resp = api.post(
            f'/api/fba/plans/{draft_plan.id}/shipments/{s1.id}/dispatch/',
            {'carrier_name': 'Evri', 'tracking_number': 'H111'},
            format='json',
        )
        assert resp.status_code == 200
        draft_plan.refresh_from_db()
        assert draft_plan.status == 'ready_to_ship'  # not fully dispatched yet

    def test_dispatch_rejected_before_ready_to_ship(self, api, draft_plan):
        draft_plan.status = 'items_added'
        draft_plan.save()
        shipment = FBAShipment.objects.create(plan=draft_plan, shipment_id='sh-1')
        resp = api.post(
            f'/api/fba/plans/{draft_plan.id}/shipments/{shipment.id}/dispatch/',
            {'carrier_name': 'Evri', 'tracking_number': 'H111'},
            format='json',
        )
        assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# API call audit trail endpoint                                               #
# --------------------------------------------------------------------------- #


class TestAPICallsEndpoint:
    def test_lists_recent_api_calls(self, api, draft_plan):
        FBAAPICall.objects.create(
            plan=draft_plan, operation_name='createInboundPlan',
            response_status=200, duration_ms=120,
        )
        FBAAPICall.objects.create(
            plan=draft_plan, operation_name='generatePackingOptions',
            response_status=429, duration_ms=90, error_message='throttled',
        )
        resp = api.get(f'/api/fba/plans/{draft_plan.id}/api-calls/')
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Newest first (Meta.ordering = -created_at)
        assert data[0]['operation_name'] == 'generatePackingOptions'


# --------------------------------------------------------------------------- #
# Preflight endpoint                                                          #
# --------------------------------------------------------------------------- #


class TestPreflightEndpoint:
    def test_empty_db_returns_zero(self, api, db):
        resp = api.get('/api/fba/preflight/?marketplace=UK')
        assert resp.status_code == 200
        body = resp.json()
        assert body['marketplace'] == 'UK'
        assert body['active_skus'] == 0
        assert body['ready'] is False

    def test_ready_product_counts(self, api, product_ready):
        resp = api.get('/api/fba/preflight/?marketplace=UK')
        assert resp.status_code == 200
        body = resp.json()
        assert body['active_skus'] == 1
        assert body['with_fnsku'] == 1
        assert body['with_dims'] == 1
        assert body['fully_ready'] == 1
        assert body['ready'] is True
        assert body['missing_fnsku'] == []
        assert body['missing_dims'] == []

    def test_mixed_missing(self, api, product_ready, product_no_fnsku, product_no_dims):
        resp = api.get('/api/fba/preflight/?marketplace=UK')
        body = resp.json()
        assert body['active_skus'] == 3
        assert body['fully_ready'] == 1
        assert body['ready'] is False
        assert len(body['missing_fnsku']) == 1
        assert len(body['missing_dims']) == 1

    def test_unsupported_marketplace(self, api, db):
        resp = api.get('/api/fba/preflight/?marketplace=JP')
        assert resp.status_code == 400
