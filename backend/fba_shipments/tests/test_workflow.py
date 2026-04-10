"""
Unit tests for fba_shipments.services.workflow.

No network, no Django-Q cluster — `FBAInboundClient` is passed in with a
`_client=MagicMock()` hook, and the Django-Q re-enqueue path is patched so
calls are recorded but no task actually runs.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from fba_shipments.models import (
    FBAAPICall,
    FBABox,
    FBABoxItem,
    FBAShipment,
    FBAShipmentPlan,
    FBAShipmentPlanItem,
)
from fba_shipments.services import workflow as wf
from fba_shipments.services.workflow import (
    TRANSITIONS,
    WAITING_STATUSES,
    _build_packing_groups_from_boxes,
    _handler_for,
    advance_plan,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def ship_from():
    return {
        'name': 'NBNE',
        'addressLine1': '1 Test Street',
        'city': 'Alnwick',
        'countryCode': 'GB',
        'postalCode': 'NE66 1AA',
        'phoneNumber': '+441665000000',
        'email': 'shipping@nbne.test',
    }


@pytest.fixture
def plan(db, ship_from):
    return FBAShipmentPlan.objects.create(
        name='Test UK Plan',
        marketplace='UK',
        ship_from_address=ship_from,
        status='items_added',
    )


@pytest.fixture
def sku(db):
    from products.models import Product, SKU
    product = Product.objects.create(
        m_number='M1234',
        description='Test Product',
        blank='A4s',
    )
    return SKU.objects.create(
        product=product,
        sku='NBNE-TEST-UK-01',
        channel='amazon_uk',
        asin='B00TESTASIN',
    )


@pytest.fixture
def plan_with_item(plan, sku):
    FBAShipmentPlanItem.objects.create(
        plan=plan,
        sku=sku,
        quantity=10,
        msku='NBNE-TEST-UK-01',
        fnsku='X00TESTFN01',
    )
    return plan


@pytest.fixture
def mock_client():
    c = MagicMock(name='FBAInboundClient')
    return c


@pytest.fixture
def patched_client(mock_client):
    """Patch FBAInboundClient constructor to return our mock."""
    with patch(
        'fba_shipments.services.workflow.FBAInboundClient',
        return_value=mock_client,
    ):
        yield mock_client


@pytest.fixture
def patched_enqueue():
    """Patch _enqueue_next so no real Django-Q task is scheduled."""
    with patch('fba_shipments.services.workflow._enqueue_next') as mocked:
        yield mocked


# --------------------------------------------------------------------------- #
# TRANSITIONS + _handler_for                                                  #
# --------------------------------------------------------------------------- #


class TestDispatch:
    def test_transitions_has_no_terminal_states(self):
        """Terminal statuses must NOT be in the TRANSITIONS table."""
        for terminal in FBAShipmentPlan.TERMINAL_STATUSES:
            assert terminal not in TRANSITIONS

    def test_transitions_has_no_pause_states(self):
        """Pause states are dispatched by _handler_for, not TRANSITIONS."""
        assert 'packing_options_ready' not in TRANSITIONS
        assert 'placement_options_ready' not in TRANSITIONS

    def test_every_transition_has_a_handler(self):
        """Every handler name in TRANSITIONS must exist as _step_* in the module."""
        for status, handler_name in TRANSITIONS.items():
            assert hasattr(wf, f'_step_{handler_name}'), (
                f'Missing handler _step_{handler_name} for status {status}'
            )

    def test_waiting_statuses_are_all_in_transitions(self):
        """Every WAITING status should have a handler (it's the state we re-enter)."""
        for status in WAITING_STATUSES:
            assert status in TRANSITIONS

    def test_handler_for_terminal_returns_none(self, plan):
        for terminal in FBAShipmentPlan.TERMINAL_STATUSES:
            plan.status = terminal
            assert _handler_for(plan) is None

    def test_handler_for_packing_pause_without_selection(self, plan):
        plan.status = 'packing_options_ready'
        plan.selected_packing_option_id = ''
        assert _handler_for(plan) is None

    def test_handler_for_packing_ready_with_selection(self, plan):
        plan.status = 'packing_options_ready'
        plan.selected_packing_option_id = 'po-1'
        assert _handler_for(plan) == 'set_packing_info'

    def test_handler_for_placement_pause_without_selection(self, plan):
        plan.status = 'placement_options_ready'
        plan.selected_placement_option_id = ''
        assert _handler_for(plan) is None

    def test_handler_for_placement_ready_with_selection(self, plan):
        plan.status = 'placement_options_ready'
        plan.selected_placement_option_id = 'pl-1'
        assert _handler_for(plan) == 'confirm_placement'

    def test_handler_for_items_added(self, plan):
        plan.status = 'items_added'
        assert _handler_for(plan) == 'create_plan'


# --------------------------------------------------------------------------- #
# advance_plan entry point                                                    #
# --------------------------------------------------------------------------- #


class TestAdvancePlan:
    def test_missing_plan_returns_missing(self, db):
        assert advance_plan(999_999) == 'missing'

    def test_terminal_plan_returns_status_no_handler(
        self, plan_with_item, patched_client, patched_enqueue,
    ):
        plan_with_item.status = 'ready_to_ship'
        plan_with_item.save()
        assert advance_plan(plan_with_item.id) == 'ready_to_ship'
        patched_client.create_inbound_plan.assert_not_called()
        patched_enqueue.assert_not_called()

    def test_paused_plan_returns_status_no_handler(
        self, plan_with_item, patched_client, patched_enqueue,
    ):
        plan_with_item.status = 'packing_options_ready'
        plan_with_item.selected_packing_option_id = ''
        plan_with_item.save()
        assert advance_plan(plan_with_item.id) == 'packing_options_ready'
        patched_enqueue.assert_not_called()

    def test_happy_path_create_plan_runs_and_reenqueues(
        self, plan_with_item, patched_client, patched_enqueue,
    ):
        patched_client.create_inbound_plan.return_value = {
            'inboundPlanId': 'wf-abc',
            'operationId': 'op-1',
        }
        result = advance_plan(plan_with_item.id)
        assert result == 'plan_creating'
        plan_with_item.refresh_from_db()
        assert plan_with_item.status == 'plan_creating'
        assert plan_with_item.inbound_plan_id == 'wf-abc'
        assert plan_with_item.current_operation_id == 'op-1'
        assert plan_with_item.current_operation_started_at is not None
        patched_client.create_inbound_plan.assert_called_once()
        # Waiting state → delay
        patched_enqueue.assert_called_once()
        _, kwargs = patched_enqueue.call_args
        assert kwargs.get('delay_seconds') == wf.WAIT_DELAY_SECONDS

    def test_handler_exception_moves_to_error_and_logs(
        self, plan_with_item, patched_client, patched_enqueue,
    ):
        patched_client.create_inbound_plan.side_effect = RuntimeError('boom')
        result = advance_plan(plan_with_item.id)
        assert result == 'error'
        plan_with_item.refresh_from_db()
        assert plan_with_item.status == 'error'
        assert len(plan_with_item.error_log) == 1
        entry = plan_with_item.error_log[0]
        assert entry['step'] == 'items_added'
        assert 'boom' in entry['message']
        assert entry['type'] == 'RuntimeError'
        patched_enqueue.assert_not_called()

    def test_error_log_reassigns_rather_than_appends(
        self, plan_with_item, patched_client, patched_enqueue,
    ):
        """Regression: error_log must survive a second failure on the same plan."""
        plan_with_item.error_log = [{'at': 'earlier', 'step': 'foo', 'message': 'x', 'type': 'X'}]
        plan_with_item.save()
        patched_client.create_inbound_plan.side_effect = RuntimeError('second')
        advance_plan(plan_with_item.id)
        plan_with_item.refresh_from_db()
        assert len(plan_with_item.error_log) == 2

    def test_auto_advance_from_ready_with_selection(
        self, plan_with_item, patched_client, patched_enqueue, sku,
    ):
        """
        After fetch_packing_options auto-selects a single option and moves
        the plan to packing_options_ready, the NEXT advance_plan call must
        dispatch set_packing_info (not pause).
        """
        # Make the plan look like we've just finished fetch with a selection
        box = FBABox.objects.create(
            plan=plan_with_item, box_number=1,
            length_cm=Decimal('30'), width_cm=Decimal('20'),
            height_cm=Decimal('15'), weight_kg=Decimal('2.5'),
        )
        FBABoxItem.objects.create(
            box=box, plan_item=plan_with_item.items.first(), quantity=10,
        )
        plan_with_item.status = 'packing_options_ready'
        plan_with_item.inbound_plan_id = 'wf-xyz'
        plan_with_item.selected_packing_option_id = 'po-1'
        plan_with_item.save()

        patched_client.set_packing_information.return_value = {'operationId': 'op-2'}
        result = advance_plan(plan_with_item.id)
        assert result == 'packing_info_setting'
        plan_with_item.refresh_from_db()
        assert plan_with_item.current_operation_id == 'op-2'
        patched_client.set_packing_information.assert_called_once()


# --------------------------------------------------------------------------- #
# Individual step handlers — direct unit tests                                #
# --------------------------------------------------------------------------- #


class TestCreatePlan:
    def test_create_plan_body_shape(self, plan_with_item, mock_client):
        mock_client.create_inbound_plan.return_value = {
            'inboundPlanId': 'wf-1', 'operationId': 'op-1',
        }
        wf._step_create_plan(plan_with_item, mock_client)
        mock_client.create_inbound_plan.assert_called_once()
        body = mock_client.create_inbound_plan.call_args[0][0]
        assert body['name'] == plan_with_item.name
        assert body['destinationMarketplaces'] == ['A1F83G8C2ARO7P']
        assert body['sourceAddress'] == plan_with_item.ship_from_address
        assert body['items'] == [{
            'msku': 'NBNE-TEST-UK-01',
            'quantity': 10,
            'labelOwner': 'SELLER',
            'prepOwner': 'SELLER',
        }]
        assert plan_with_item.status == 'plan_creating'
        assert plan_with_item.inbound_plan_id == 'wf-1'
        assert plan_with_item.current_operation_id == 'op-1'

    def test_create_plan_raises_on_empty_items(self, plan, mock_client):
        with pytest.raises(RuntimeError, match='no items on plan'):
            wf._step_create_plan(plan, mock_client)


class TestWaitHandlers:
    def test_wait_success_advances(self, plan, mock_client):
        plan.status = 'plan_creating'
        plan.current_operation_id = 'op-1'
        mock_client.get_operation_status.return_value = {'operationStatus': 'SUCCESS'}
        wf._step_wait_for_plan_creation(plan, mock_client)
        assert plan.status == 'plan_created'
        assert plan.current_operation_id == ''
        assert plan.last_polled_at is not None

    def test_wait_failed_raises(self, plan, mock_client):
        plan.status = 'plan_creating'
        plan.current_operation_id = 'op-1'
        mock_client.get_operation_status.return_value = {
            'operationStatus': 'FAILED',
            'operationProblems': [{'code': 'FBA_INB_0182', 'message': 'prep missing'}],
        }
        with pytest.raises(RuntimeError, match='createInboundPlan failed'):
            wf._step_wait_for_plan_creation(plan, mock_client)

    def test_wait_in_progress_leaves_status_unchanged(self, plan, mock_client):
        plan.status = 'plan_creating'
        plan.current_operation_id = 'op-1'
        mock_client.get_operation_status.return_value = {'operationStatus': 'IN_PROGRESS'}
        wf._step_wait_for_plan_creation(plan, mock_client)
        assert plan.status == 'plan_creating'  # unchanged
        assert plan.current_operation_id == 'op-1'  # still polling this op

    def test_poll_op_without_current_operation_id_raises(self, plan, mock_client):
        plan.status = 'plan_creating'
        plan.current_operation_id = ''
        with pytest.raises(RuntimeError, match='no current_operation_id'):
            wf._step_wait_for_plan_creation(plan, mock_client)


class TestFetchPackingOptions:
    def test_single_option_auto_selects(self, plan, mock_client):
        mock_client.list_packing_options.return_value = {
            'packingOptions': [{'packingOptionId': 'po-1'}],
        }
        wf._step_fetch_packing_options(plan, mock_client)
        assert plan.selected_packing_option_id == 'po-1'
        assert plan.status == 'packing_options_ready'
        assert plan.packing_options_snapshot == {
            'packingOptions': [{'packingOptionId': 'po-1'}],
        }

    def test_multiple_options_do_not_auto_select(self, plan, mock_client):
        mock_client.list_packing_options.return_value = {
            'packingOptions': [
                {'packingOptionId': 'po-1'},
                {'packingOptionId': 'po-2'},
            ],
        }
        wf._step_fetch_packing_options(plan, mock_client)
        assert plan.selected_packing_option_id == ''
        assert plan.status == 'packing_options_ready'

    def test_zero_options_do_not_crash(self, plan, mock_client):
        mock_client.list_packing_options.return_value = {'packingOptions': []}
        wf._step_fetch_packing_options(plan, mock_client)
        assert plan.selected_packing_option_id == ''
        assert plan.status == 'packing_options_ready'


class TestFetchPlacementOptions:
    def test_single_option_auto_selects(self, plan, mock_client):
        mock_client.list_placement_options.return_value = {
            'placementOptions': [{'placementOptionId': 'pl-1'}],
        }
        wf._step_fetch_placement_options(plan, mock_client)
        assert plan.selected_placement_option_id == 'pl-1'
        assert plan.status == 'placement_options_ready'

    def test_multiple_options_do_not_auto_select(self, plan, mock_client):
        mock_client.list_placement_options.return_value = {
            'placementOptions': [
                {'placementOptionId': 'pl-1'},
                {'placementOptionId': 'pl-2'},
            ],
        }
        wf._step_fetch_placement_options(plan, mock_client)
        assert plan.selected_placement_option_id == ''
        assert plan.status == 'placement_options_ready'


class TestMaterialiseShipments:
    def test_creates_shipments_from_snapshot(self, plan):
        plan.placement_options_snapshot = {
            'placementOptions': [{
                'placementOptionId': 'pl-1',
                'shipmentIds': ['sh-aaa', 'sh-bbb'],
            }],
        }
        plan.selected_placement_option_id = 'pl-1'
        wf._materialise_shipments_from_placement(plan)
        ids = set(plan.shipments.values_list('shipment_id', flat=True))
        assert ids == {'sh-aaa', 'sh-bbb'}

    def test_idempotent(self, plan):
        FBAShipment.objects.create(plan=plan, shipment_id='sh-aaa')
        plan.placement_options_snapshot = {
            'placementOptions': [{
                'placementOptionId': 'pl-1',
                'shipmentIds': ['sh-aaa', 'sh-bbb'],
            }],
        }
        plan.selected_placement_option_id = 'pl-1'
        wf._materialise_shipments_from_placement(plan)
        assert plan.shipments.count() == 2

    def test_missing_selection_is_noop(self, plan, caplog):
        plan.placement_options_snapshot = {
            'placementOptions': [{'placementOptionId': 'pl-other', 'shipmentIds': ['sh']}],
        }
        plan.selected_placement_option_id = 'pl-1'
        wf._materialise_shipments_from_placement(plan)
        assert plan.shipments.count() == 0


class TestFetchLabels:
    def test_fetches_labels_for_every_shipment(self, plan, mock_client):
        FBAShipment.objects.create(
            plan=plan, shipment_id='sh-1',
            shipment_confirmation_id='FBA15ABCDEFG',
        )
        FBAShipment.objects.create(
            plan=plan, shipment_id='sh-2',
            shipment_confirmation_id='FBA15HIJKLMN',
        )
        mock_client.get_labels.return_value = {'downloadURL': 'http://labels/x.pdf'}
        wf._step_fetch_labels(plan, mock_client)
        assert mock_client.get_labels.call_count == 2
        for s in plan.shipments.all():
            assert s.labels_url == 'http://labels/x.pdf'
            assert s.labels_fetched_at is not None
        assert plan.status == 'ready_to_ship'

    def test_raises_when_no_shipments(self, plan, mock_client):
        with pytest.raises(RuntimeError, match='no shipments'):
            wf._step_fetch_labels(plan, mock_client)


# --------------------------------------------------------------------------- #
# _build_packing_groups_from_boxes                                            #
# --------------------------------------------------------------------------- #


def _add_box(plan, number, l=30, w=20, h=15, kg=Decimal('2.5')):
    return FBABox.objects.create(
        plan=plan, box_number=number,
        length_cm=Decimal(l), width_cm=Decimal(w),
        height_cm=Decimal(h), weight_kg=kg,
    )


class TestBuildPackingGroups:
    def test_requires_selected_option(self, plan_with_item):
        plan_with_item.selected_packing_option_id = ''
        with pytest.raises(RuntimeError, match='selected_packing_option_id'):
            _build_packing_groups_from_boxes(plan_with_item)

    def test_requires_boxes(self, plan_with_item):
        plan_with_item.selected_packing_option_id = 'po-1'
        with pytest.raises(RuntimeError, match='no FBABox rows'):
            _build_packing_groups_from_boxes(plan_with_item)

    def test_box_without_contents_raises(self, plan_with_item):
        plan_with_item.selected_packing_option_id = 'po-1'
        _add_box(plan_with_item, 1)
        with pytest.raises(RuntimeError, match='box 1 has no contents'):
            _build_packing_groups_from_boxes(plan_with_item)

    def test_single_box_single_item(self, plan_with_item):
        plan_with_item.selected_packing_option_id = 'po-1'
        box = _add_box(plan_with_item, 1)
        FBABoxItem.objects.create(
            box=box, plan_item=plan_with_item.items.first(), quantity=10,
        )
        result = _build_packing_groups_from_boxes(plan_with_item)
        assert len(result) == 1
        assert result[0]['packingGroupId'] == 'po-1'
        boxes = result[0]['boxes']
        assert len(boxes) == 1
        b = boxes[0]
        assert b['boxId'] == 'box-001'
        assert b['dimensions'] == {
            'length': 30.0, 'width': 20.0, 'height': 15.0, 'unitOfMeasurement': 'CM',
        }
        assert b['weight'] == {'value': 2.5, 'unit': 'KG'}
        assert b['contentInformationSource'] == 'BOX_CONTENT_PROVIDED'
        assert b['quantity'] == 1
        assert b['items'] == [{
            'msku': 'NBNE-TEST-UK-01',
            'quantity': 10,
            'prepOwner': 'SELLER',
            'labelOwner': 'SELLER',
        }]

    def test_single_box_multiple_items(self, plan_with_item, db):
        from products.models import Product, SKU
        p2 = Product.objects.create(m_number='M2000', description='Second', blank='A5s')
        sku2 = SKU.objects.create(product=p2, sku='NBNE-TEST-UK-02', channel='amazon_uk')
        item2 = FBAShipmentPlanItem.objects.create(
            plan=plan_with_item, sku=sku2, quantity=5,
            msku='NBNE-TEST-UK-02', fnsku='X00TESTFN02',
        )
        plan_with_item.selected_packing_option_id = 'po-1'
        box = _add_box(plan_with_item, 1)
        FBABoxItem.objects.create(
            box=box, plan_item=plan_with_item.items.first(), quantity=10,
        )
        FBABoxItem.objects.create(box=box, plan_item=item2, quantity=5)
        result = _build_packing_groups_from_boxes(plan_with_item)
        items = result[0]['boxes'][0]['items']
        assert len(items) == 2
        mskus = {i['msku'] for i in items}
        assert mskus == {'NBNE-TEST-UK-01', 'NBNE-TEST-UK-02'}

    def test_multiple_boxes_mixed(self, plan_with_item):
        plan_with_item.selected_packing_option_id = 'po-1'
        box1 = _add_box(plan_with_item, 1, kg=Decimal('1.5'))
        box2 = _add_box(plan_with_item, 2, kg=Decimal('3.5'))
        item = plan_with_item.items.first()
        FBABoxItem.objects.create(box=box1, plan_item=item, quantity=4)
        FBABoxItem.objects.create(box=box2, plan_item=item, quantity=6)
        result = _build_packing_groups_from_boxes(plan_with_item)
        assert len(result) == 1
        boxes = result[0]['boxes']
        assert len(boxes) == 2
        assert [b['boxId'] for b in boxes] == ['box-001', 'box-002']
        assert boxes[0]['weight']['value'] == 1.5
        assert boxes[1]['weight']['value'] == 3.5
        assert boxes[0]['items'][0]['quantity'] == 4
        assert boxes[1]['items'][0]['quantity'] == 6


# --------------------------------------------------------------------------- #
# _enqueue_next                                                               #
# --------------------------------------------------------------------------- #


class TestEnqueueNext:
    def test_no_delay_uses_async_task(self, plan):
        with patch('django_q.tasks.async_task') as mocked_async:
            wf._enqueue_next(plan, delay_seconds=0)
        mocked_async.assert_called_once_with(
            'fba_shipments.services.workflow.advance_plan', plan.id,
        )

    def test_delay_uses_schedule(self, plan):
        with patch('django_q.tasks.async_task') as mocked_async, \
             patch('django_q.models.Schedule.objects.create') as mocked_schedule:
            wf._enqueue_next(plan, delay_seconds=5)
        mocked_async.assert_not_called()
        mocked_schedule.assert_called_once()
        _, kwargs = mocked_schedule.call_args
        assert kwargs['func'] == 'fba_shipments.services.workflow.advance_plan'
        assert kwargs['args'] == f'{plan.id}'
