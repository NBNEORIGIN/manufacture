"""
Resumable state machine for the FBA v2024-03-20 inbound workflow.

Design principles (see Phase 2.3 brief):

1. **One Django-Q task per plan advancement.** `advance_plan(plan_id)` runs
   a single handler, saves, then either terminates (terminal/paused) or
   re-enqueues itself for the next step. This bounds per-task runtime and
   keeps failures recoverable.
2. **State is authoritative.** Handlers are dispatched purely on
   `plan.status`. They never assume what happened previously.
3. **Every transition persists immediately** via a single `plan.save()`
   call at the end of `advance_plan`. Handlers mutate in-memory only.
4. **Errors are caught at the task level** and written to `plan.error_log`
   with `plan.status = 'error'`. The task does NOT raise — it returns
   `'error'` — so Django-Q does not auto-retry. Manual retry via UI.
5. **Never `.append()` to a JSONField list.** Django's dirty tracking
   doesn't reliably detect in-place mutations; always reassign.
6. **Polling is one-shot per invocation.** A `*_wait` handler does ONE
   `getInboundOperationStatus` call. If still IN_PROGRESS the plan stays
   in its current state and `advance_plan` re-enqueues itself with a small
   delay. Worker slots are never blocked for minutes.

Each handler is intentionally 5–15 lines. Read them top-to-bottom to
follow the 23-step flow.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

from fba_shipments.models import FBAShipment, FBAShipmentPlan
from fba_shipments.services.sp_api_client import (
    FBAInboundClient,
    MARKETPLACE_TO_AMAZON_ID,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# State → handler dispatch                                                    #
# --------------------------------------------------------------------------- #

# Mapping from current plan.status to the handler function suffix in this
# module. The terminal states (ready_to_ship, dispatched, cancelled, error)
# are NOT in this map — advance_plan handles them explicitly. The two
# *_options_ready pause states are also handled specially because dispatch
# depends on whether a selection has been made.
TRANSITIONS: dict[str, str] = {
    # --- Plan creation -----------------------------------------------------
    'items_added':                'create_plan',
    'plan_creating':              'wait_for_plan_creation',
    'plan_created':               'generate_packing',
    # --- Packing options ---------------------------------------------------
    'packing_generating':         'wait_for_packing_generation',
    'packing_options_fetching':   'fetch_packing_options',
    # packing_options_ready: handled specially (pause or set_packing_info)
    'packing_info_setting':       'wait_for_packing_info',
    'packing_info_set':           'confirm_packing',
    'packing_confirming':         'wait_for_packing_confirm',
    'packing_confirmed':          'generate_placement',
    # --- Placement options -------------------------------------------------
    'placement_generating':       'wait_for_placement_generation',
    'placement_options_fetching': 'fetch_placement_options',
    # placement_options_ready: handled specially (pause or confirm_placement)
    'placement_confirming':       'wait_for_placement_confirm',
    'placement_confirmed':        'generate_transport',
    # --- Transportation options --------------------------------------------
    'transport_generating':       'wait_for_transport_generation',
    'transport_options_fetching': 'fetch_transport_options',
    'transport_options_ready':    'generate_delivery_window',
    # --- Delivery windows --------------------------------------------------
    'delivery_window_generating': 'wait_for_delivery_window_generation',
    'delivery_window_fetching':   'fetch_delivery_window',
    'delivery_window_ready':      'confirm_transport',
    'transport_confirming':       'wait_for_transport_confirm',
    'transport_confirmed':        'fetch_labels',
    # labels_fetching resolves inline inside fetch_labels → ready_to_ship
}

# Statuses where `advance_plan` should re-enqueue itself with a small delay
# rather than immediately, to avoid spinning on an in-flight async op.
# Every `*_wait` handler's incoming state belongs here.
WAITING_STATUSES: set[str] = {
    'plan_creating',
    'packing_generating',
    'packing_info_setting',
    'packing_confirming',
    'placement_generating',
    'placement_confirming',
    'transport_generating',
    'delivery_window_generating',
    'transport_confirming',
}

WAIT_DELAY_SECONDS = 3


def _handler_for(plan: FBAShipmentPlan) -> str | None:
    """
    Return the handler function name for this plan's current state, or None
    if the plan is paused (waiting for user) or terminal.
    """
    status = plan.status
    if status in FBAShipmentPlan.TERMINAL_STATUSES:
        return None
    # Pause-aware dispatch for the two human-review states:
    if status == 'packing_options_ready':
        return 'set_packing_info' if plan.selected_packing_option_id else None
    if status == 'placement_options_ready':
        return 'confirm_placement' if plan.selected_placement_option_id else None
    return TRANSITIONS.get(status)


# --------------------------------------------------------------------------- #
# Task entry point                                                            #
# --------------------------------------------------------------------------- #


def advance_plan(plan_id: int) -> str:
    """
    Django-Q entry point. Advances a single plan by one logical step and
    re-enqueues itself unless the plan is now terminal or paused.

    Returns the final plan.status for the Q task log. Does NOT raise —
    errors are caught, written to plan.error_log, and the plan is moved
    to 'error' so the user can retry from the UI.
    """
    try:
        plan = FBAShipmentPlan.objects.get(pk=plan_id)
    except FBAShipmentPlan.DoesNotExist:
        logger.warning('advance_plan: plan %s not found', plan_id)
        return 'missing'

    if plan.status in FBAShipmentPlan.TERMINAL_STATUSES:
        return plan.status

    handler_name = _handler_for(plan)
    if handler_name is None:
        logger.info('advance_plan: plan %s paused at %s', plan_id, plan.status)
        return plan.status

    # Capture the starting step BEFORE the handler runs. If the handler
    # raises after mutating plan.status, error_log must reference the step
    # that actually failed, not the mutated-but-unsaved status.
    starting_status = plan.status

    handler = globals().get(f'_step_{handler_name}')
    if handler is None:
        _record_error(
            plan, starting_status,
            f'No handler _step_{handler_name} for status {starting_status}',
            'ConfigurationError',
        )
        return 'error'

    try:
        client = FBAInboundClient(marketplace_code=plan.marketplace, plan=plan)
        handler(plan, client)
        plan.save()
    except Exception as exc:  # noqa: BLE001 — we genuinely want to catch everything
        logger.exception('Plan %s failed at step %s', plan_id, starting_status)
        # Important: _record_error does its own save with plan.status='error'.
        # Any partial mutations in `plan` from the handler are preserved in
        # memory but overwritten by _record_error's explicit assignments.
        _record_error(
            plan, starting_status,
            str(exc) or exc.__class__.__name__,
            exc.__class__.__name__,
        )
        return 'error'

    # Decide whether to re-enqueue.
    if plan.status in FBAShipmentPlan.TERMINAL_STATUSES:
        return plan.status
    if _handler_for(plan) is None:
        # Plan is now paused (e.g. fetch_* put it into *_options_ready with
        # >1 options and no auto-selection). Leave it for user confirmation.
        logger.info('advance_plan: plan %s now paused at %s', plan_id, plan.status)
        return plan.status

    delay = WAIT_DELAY_SECONDS if plan.status in WAITING_STATUSES else 0
    _enqueue_next(plan, delay_seconds=delay)
    return plan.status


def _record_error(
    plan: FBAShipmentPlan,
    step: str,
    message: str,
    exc_type: str,
) -> None:
    """
    Append a failure entry to plan.error_log and move the plan to 'error'.
    Uses reassignment rather than .append() so Django's JSONField dirty
    tracking catches the change.
    """
    entry = {
        'at': timezone.now().isoformat(),
        'step': step,
        'message': message,
        'type': exc_type,
    }
    plan.error_log = (plan.error_log or []) + [entry]
    plan.status = 'error'
    plan.save()


def _enqueue_next(plan: FBAShipmentPlan, delay_seconds: int = 0) -> None:
    """
    Re-enqueue `advance_plan` for this plan, optionally with a delay.

    Non-waiting states use `async_task` (fires on the next available
    worker). Waiting states use `Schedule.objects.create(ONCE, next_run=…)`
    so the qcluster picks them up after `delay_seconds` — Django-Q2's
    `async_task` doesn't support a delay kwarg directly.
    """
    try:
        from django_q.models import Schedule
        from django_q.tasks import async_task
    except ImportError:  # pragma: no cover — django_q is a hard requirement
        logger.error('django_q not installed; cannot re-enqueue plan %s', plan.id)
        return

    if delay_seconds > 0:
        Schedule.objects.create(
            func='fba_shipments.services.workflow.advance_plan',
            args=f'{plan.id}',
            schedule_type=Schedule.ONCE,
            next_run=timezone.now() + timedelta(seconds=delay_seconds),
        )
    else:
        async_task('fba_shipments.services.workflow.advance_plan', plan.id)


def kick_off(plan: FBAShipmentPlan) -> None:
    """
    Public helper for views/REST handlers: start (or resume) the workflow
    for a plan. Safe to call repeatedly — advance_plan is idempotent on
    terminal/paused states.
    """
    _enqueue_next(plan, delay_seconds=0)


# --------------------------------------------------------------------------- #
# Polling primitive                                                           #
# --------------------------------------------------------------------------- #


def _poll_op(client: FBAInboundClient, plan: FBAShipmentPlan) -> dict[str, Any]:
    """
    One-shot `getInboundOperationStatus` call. Updates `plan.last_polled_at`.
    Returns the raw payload so callers can inspect operationProblems on FAILED.
    """
    if not plan.current_operation_id:
        raise RuntimeError(
            f'Plan {plan.id} in {plan.status} has no current_operation_id to poll'
        )
    payload = client.get_operation_status(plan.current_operation_id)
    plan.last_polled_at = timezone.now()
    return payload or {}


def _op_status(payload: dict[str, Any]) -> str:
    return payload.get('operationStatus', 'IN_PROGRESS')


def _op_failed(payload: dict[str, Any], op_name: str) -> RuntimeError:
    problems = payload.get('operationProblems', []) or []
    return RuntimeError(f'{op_name} failed: {problems}')


# --------------------------------------------------------------------------- #
# Step handlers — each handles exactly ONE state transition                   #
# --------------------------------------------------------------------------- #
#
# Conventions:
#   * Handlers are named `_step_{handler_name}` where `handler_name` comes
#     from TRANSITIONS (or the pause-aware _handler_for).
#   * Handlers mutate `plan` in memory and return None. They never call
#     `plan.save()` — advance_plan does that once at the end.
#   * Handlers raise on any error. advance_plan catches it and writes to
#     plan.error_log.

# ---- PLAN CREATION -------------------------------------------------------- #


def _step_create_plan(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    items = list(plan.items.all())
    if not items:
        raise RuntimeError('Cannot create inbound plan: no items on plan')
    items_payload = [
        {
            'msku': item.msku,
            'quantity': item.quantity,
            'labelOwner': item.label_owner,
            'prepOwner': item.prep_owner,
        }
        for item in items
    ]
    body = {
        'destinationMarketplaces': [MARKETPLACE_TO_AMAZON_ID[plan.marketplace]],
        'sourceAddress': plan.ship_from_address,
        'items': items_payload,
        'name': plan.name,
    }
    payload = client.create_inbound_plan(body)
    plan.inbound_plan_id = payload.get('inboundPlanId', '')
    plan.current_operation_id = payload.get('operationId', '')
    plan.current_operation_started_at = timezone.now()
    plan.status = 'plan_creating'


def _step_wait_for_plan_creation(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    payload = _poll_op(client, plan)
    status = _op_status(payload)
    if status == 'SUCCESS':
        plan.status = 'plan_created'
        plan.current_operation_id = ''
    elif status == 'FAILED':
        raise _op_failed(payload, 'createInboundPlan')
    # IN_PROGRESS → leave unchanged; advance_plan re-enqueues with delay.


# ---- PACKING OPTIONS ------------------------------------------------------ #


def _step_generate_packing(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    payload = client.generate_packing_options(plan.inbound_plan_id)
    plan.current_operation_id = payload.get('operationId', '')
    plan.current_operation_started_at = timezone.now()
    plan.status = 'packing_generating'


def _step_wait_for_packing_generation(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    payload = _poll_op(client, plan)
    status = _op_status(payload)
    if status == 'SUCCESS':
        plan.status = 'packing_options_fetching'
        plan.current_operation_id = ''
    elif status == 'FAILED':
        raise _op_failed(payload, 'generatePackingOptions')


def _step_fetch_packing_options(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    """
    Fetch listPackingOptions. Auto-select if exactly one option; otherwise
    move to packing_options_ready and PAUSE for user confirmation.

    The state transition is the same (→ packing_options_ready) in both cases;
    the difference is whether selected_packing_option_id is set. advance_plan's
    _handler_for dispatches the next handler if it is, or pauses if it isn't.
    """
    options_payload = client.list_packing_options(plan.inbound_plan_id)
    plan.packing_options_snapshot = options_payload
    options = (options_payload or {}).get('packingOptions', []) or []
    if len(options) == 1:
        plan.selected_packing_option_id = options[0].get('packingOptionId', '')
        logger.info(
            'Plan %s: auto-selected single packing option %s',
            plan.id, plan.selected_packing_option_id,
        )
    else:
        logger.info(
            'Plan %s: %d packing options returned; pausing for user review',
            plan.id, len(options),
        )
    plan.status = 'packing_options_ready'


def _step_set_packing_info(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    packing_groups = _build_packing_groups_from_boxes(plan)
    if not packing_groups:
        raise RuntimeError(
            f'Plan {plan.id}: no boxes defined; cannot call setPackingInformation'
        )
    body = {'packageGroupings': packing_groups}
    payload = client.set_packing_information(plan.inbound_plan_id, body)
    plan.current_operation_id = payload.get('operationId', '')
    plan.current_operation_started_at = timezone.now()
    plan.status = 'packing_info_setting'


def _step_wait_for_packing_info(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    payload = _poll_op(client, plan)
    status = _op_status(payload)
    if status == 'SUCCESS':
        plan.status = 'packing_info_set'
        plan.current_operation_id = ''
    elif status == 'FAILED':
        raise _op_failed(payload, 'setPackingInformation')


def _step_confirm_packing(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    if not plan.selected_packing_option_id:
        raise RuntimeError(
            f'Plan {plan.id}: selected_packing_option_id missing; '
            'cannot call confirmPackingOption'
        )
    payload = client.confirm_packing_option(
        plan.inbound_plan_id, plan.selected_packing_option_id,
    )
    plan.current_operation_id = payload.get('operationId', '')
    plan.current_operation_started_at = timezone.now()
    plan.status = 'packing_confirming'


def _step_wait_for_packing_confirm(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    payload = _poll_op(client, plan)
    status = _op_status(payload)
    if status == 'SUCCESS':
        plan.status = 'packing_confirmed'
        plan.current_operation_id = ''
    elif status == 'FAILED':
        raise _op_failed(payload, 'confirmPackingOption')


# ---- PLACEMENT OPTIONS --------------------------------------------------- #


def _step_generate_placement(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    payload = client.generate_placement_options(plan.inbound_plan_id)
    plan.current_operation_id = payload.get('operationId', '')
    plan.current_operation_started_at = timezone.now()
    plan.status = 'placement_generating'


def _step_wait_for_placement_generation(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    payload = _poll_op(client, plan)
    status = _op_status(payload)
    if status == 'SUCCESS':
        plan.status = 'placement_options_fetching'
        plan.current_operation_id = ''
    elif status == 'FAILED':
        raise _op_failed(payload, 'generatePlacementOptions')


def _step_fetch_placement_options(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    """
    Fetch listPlacementOptions. Auto-select if exactly one option; otherwise
    PAUSE at placement_options_ready for user review (placement options may
    carry different fees, which Ben needs to see before confirming).
    """
    options_payload = client.list_placement_options(plan.inbound_plan_id)
    plan.placement_options_snapshot = options_payload
    options = (options_payload or {}).get('placementOptions', []) or []
    if len(options) == 1:
        plan.selected_placement_option_id = options[0].get('placementOptionId', '')
        logger.info(
            'Plan %s: auto-selected single placement option %s',
            plan.id, plan.selected_placement_option_id,
        )
    else:
        logger.info(
            'Plan %s: %d placement options returned; pausing for user review',
            plan.id, len(options),
        )
    plan.status = 'placement_options_ready'


def _step_confirm_placement(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    if not plan.selected_placement_option_id:
        raise RuntimeError(
            f'Plan {plan.id}: selected_placement_option_id missing; '
            'cannot call confirmPlacementOption'
        )
    payload = client.confirm_placement_option(
        plan.inbound_plan_id, plan.selected_placement_option_id,
    )
    plan.current_operation_id = payload.get('operationId', '')
    plan.current_operation_started_at = timezone.now()
    plan.status = 'placement_confirming'


def _step_wait_for_placement_confirm(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    payload = _poll_op(client, plan)
    status = _op_status(payload)
    if status == 'SUCCESS':
        plan.status = 'placement_confirmed'
        plan.current_operation_id = ''
        _materialise_shipments_from_placement(plan)
    elif status == 'FAILED':
        raise _op_failed(payload, 'confirmPlacementOption')


def _materialise_shipments_from_placement(plan: FBAShipmentPlan) -> None:
    """
    Amazon may split one plan across multiple destination FCs. Read the
    selected placement option from `plan.placement_options_snapshot` and
    create an FBAShipment row per shipment it contains. These rows are the
    downstream anchors for transportation options, labels, and dispatch.

    Idempotent: skips shipments that already exist (matched by shipment_id).
    """
    snapshot = plan.placement_options_snapshot or {}
    options = snapshot.get('placementOptions', []) or []
    selected_id = plan.selected_placement_option_id
    option = next(
        (o for o in options if o.get('placementOptionId') == selected_id),
        None,
    )
    if option is None:
        logger.warning(
            'Plan %s: selected placement option %s not in snapshot; '
            'cannot materialise shipments',
            plan.id, selected_id,
        )
        return
    existing_ids = set(plan.shipments.values_list('shipment_id', flat=True))
    for shipment_entry in option.get('shipmentIds', []) or []:
        # `shipmentIds` in the response is a list of strings per Amazon's
        # schema. If a richer structure is returned, extend this to read
        # destinationFulfillmentCenterCode etc.
        ship_id = shipment_entry if isinstance(shipment_entry, str) else \
            shipment_entry.get('shipmentId', '')
        if not ship_id or ship_id in existing_ids:
            continue
        FBAShipment.objects.create(
            plan=plan,
            shipment_id=ship_id,
            destination_fc='',  # filled later once Amazon assigns FCs
        )


# ---- TRANSPORTATION OPTIONS ---------------------------------------------- #


def _step_generate_transport(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    """
    Fire generateTransportationOptions with a minimal nPCP (non-partnered)
    configuration. For Phase 2.3 the carrier is taken from
    `settings.FBA_DEFAULT_CARRIER` (default 'OTHER'); Ben physically books
    the real carrier after the plan reaches `ready_to_ship` and captures
    the tracking number via the UI dispatch endpoint.

    NOTE: the exact schema of `shipmentTransportationConfigurations` is
    fiddly and differs by marketplace/carrier. The body below is the
    documented minimum for nPCP and may need tuning during sandbox testing.
    """
    shipments = list(plan.shipments.all())
    if not shipments:
        raise RuntimeError(
            f'Plan {plan.id}: no FBAShipment rows; '
            'confirmPlacementOption did not materialise any shipments'
        )
    default_carrier = getattr(settings, 'FBA_DEFAULT_CARRIER', 'OTHER')
    ready_start = (timezone.now() + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0,
    )
    ready_end = ready_start + timedelta(days=2)
    body = {
        'placementOptionId': plan.selected_placement_option_id,
        'shipmentTransportationConfigurations': [
            {
                'shipmentId': s.shipment_id,
                'contactInformation': {
                    'name': plan.ship_from_address.get('name', ''),
                    'phoneNumber': plan.ship_from_address.get('phoneNumber', ''),
                    'email': plan.ship_from_address.get('email', ''),
                },
                'readyToShipWindow': {
                    'start': ready_start.isoformat(),
                    'end': ready_end.isoformat(),
                },
                'freightInformation': {
                    'carrierName': default_carrier,
                },
            }
            for s in shipments
        ],
    }
    payload = client.generate_transportation_options(plan.inbound_plan_id, body)
    plan.current_operation_id = payload.get('operationId', '')
    plan.current_operation_started_at = timezone.now()
    plan.status = 'transport_generating'


def _step_wait_for_transport_generation(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    payload = _poll_op(client, plan)
    status = _op_status(payload)
    if status == 'SUCCESS':
        plan.status = 'transport_options_fetching'
        plan.current_operation_id = ''
    elif status == 'FAILED':
        raise _op_failed(payload, 'generateTransportationOptions')


def _step_fetch_transport_options(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    """
    Fetch listTransportationOptions and auto-pick. For nPCP we typically get
    exactly one option (the minimal one tied to the placement we confirmed).
    If multiple are returned we pick the first — Ben books the real carrier
    externally, so the Amazon-side choice is largely bookkeeping.
    """
    options_payload = client.list_transportation_options(
        plan.inbound_plan_id,
        placement_option_id=plan.selected_placement_option_id,
    )
    plan.transportation_options_snapshot = options_payload
    options = (options_payload or {}).get('transportationOptions', []) or []
    if not options:
        raise RuntimeError(
            f'Plan {plan.id}: listTransportationOptions returned zero options'
        )
    plan.selected_transportation_option_id = options[0].get('transportationOptionId', '')
    plan.status = 'transport_options_ready'


# ---- DELIVERY WINDOWS ----------------------------------------------------- #


def _step_generate_delivery_window(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    """
    generateDeliveryWindowOptions is per-shipment. For Phase 2.3 we fire it
    against the first shipment; multi-shipment plans need a loop. TODO revisit
    when the first real multi-FC split happens in production.
    """
    shipment = plan.shipments.first()
    if shipment is None:
        raise RuntimeError(
            f'Plan {plan.id}: no shipments available for delivery window generation'
        )
    payload = client.generate_delivery_window_options(
        plan.inbound_plan_id, shipment.shipment_id,
    )
    plan.current_operation_id = payload.get('operationId', '')
    plan.current_operation_started_at = timezone.now()
    plan.status = 'delivery_window_generating'


def _step_wait_for_delivery_window_generation(
    plan: FBAShipmentPlan, client: FBAInboundClient,
) -> None:
    payload = _poll_op(client, plan)
    status = _op_status(payload)
    if status == 'SUCCESS':
        plan.status = 'delivery_window_fetching'
        plan.current_operation_id = ''
    elif status == 'FAILED':
        raise _op_failed(payload, 'generateDeliveryWindowOptions')


def _step_fetch_delivery_window(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    """
    listDeliveryWindowOptions for the first shipment, then auto-pick the
    EARLIEST window (Phase 2.3 default). Phase 2.5 can add a manual-pick UI.
    """
    shipment = plan.shipments.first()
    if shipment is None:
        raise RuntimeError(
            f'Plan {plan.id}: no shipments available for delivery window fetch'
        )
    options_payload = client.list_delivery_window_options(
        plan.inbound_plan_id, shipment.shipment_id,
    )
    plan.delivery_window_snapshot = options_payload
    windows = (options_payload or {}).get('deliveryWindowOptions', []) or []
    if not windows:
        raise RuntimeError(
            f'Plan {plan.id}: listDeliveryWindowOptions returned zero windows'
        )
    # Pick the earliest by startDate (ISO 8601 sorts lexicographically).
    earliest = min(
        windows,
        key=lambda w: w.get('startDate', '9999-12-31T00:00:00Z'),
    )
    plan.selected_delivery_window_id = earliest.get('deliveryWindowOptionId', '')
    plan.status = 'delivery_window_ready'


# ---- CONFIRM TRANSPORT & FETCH LABELS ------------------------------------ #


def _step_confirm_transport(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    if not plan.selected_transportation_option_id:
        raise RuntimeError(
            f'Plan {plan.id}: selected_transportation_option_id missing'
        )
    body = {
        'transportationOptionIds': [plan.selected_transportation_option_id],
    }
    payload = client.confirm_transportation_options(plan.inbound_plan_id, body)
    plan.current_operation_id = payload.get('operationId', '')
    plan.current_operation_started_at = timezone.now()
    plan.status = 'transport_confirming'


def _step_wait_for_transport_confirm(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    payload = _poll_op(client, plan)
    status = _op_status(payload)
    if status == 'SUCCESS':
        plan.status = 'transport_confirmed'
        plan.current_operation_id = ''
    elif status == 'FAILED':
        raise _op_failed(payload, 'confirmTransportationOptions')


def _step_fetch_labels(plan: FBAShipmentPlan, client: FBAInboundClient) -> None:
    """
    Final step. For each materialised shipment, fetch the label URL and
    store it on the FBAShipment row. Once all shipments have URLs, the
    plan transitions to ready_to_ship.

    A single handler invocation handles ALL shipments on the plan because
    label fetch is synchronous (no operationId, no polling). This is a
    deliberate exception to the "one step per handler" rule — a plan with
    3 shipments would otherwise need 3 separate Django-Q task cycles for
    no benefit.
    """
    shipments = list(plan.shipments.all())
    if not shipments:
        raise RuntimeError(f'Plan {plan.id}: no shipments to fetch labels for')
    plan.status = 'labels_fetching'  # transient; overwritten below
    for shipment in shipments:
        ref = shipment.shipment_confirmation_id or shipment.shipment_id
        if not ref:
            logger.warning(
                'Plan %s shipment pk=%s has no confirmation_id or shipment_id; '
                'skipping labels',
                plan.id, shipment.pk,
            )
            continue
        payload = client.get_labels(ref)
        url = (payload or {}).get('downloadURL') or (payload or {}).get('url', '')
        shipment.labels_url = url or ''
        shipment.labels_fetched_at = timezone.now()
        shipment.save(update_fields=['labels_url', 'labels_fetched_at', 'updated_at'])
    plan.status = 'ready_to_ship'


# --------------------------------------------------------------------------- #
# Packing groups builder                                                      #
# --------------------------------------------------------------------------- #


def _build_packing_groups_from_boxes(plan: FBAShipmentPlan) -> list[dict[str, Any]]:
    """
    Translate internal FBABox + FBABoxItem rows into Amazon's packageGroupings
    structure for setPackingInformation.

    Schema target (v2024-03-20):

        [
          {
            "packingGroupId": "<from selected packing option>",
            "boxes": [
              {
                "boxId": "box-001",
                "dimensions": {
                    "length": 30, "width": 20, "height": 15,
                    "unitOfMeasurement": "CM"
                },
                "weight": {"value": 2.5, "unit": "KG"},
                "contentInformationSource": "BOX_CONTENT_PROVIDED",
                "items": [
                    {"msku": "ABC-123", "quantity": 5,
                     "prepOwner": "SELLER", "labelOwner": "SELLER"}
                ],
                "quantity": 1
              }
            ]
          }
        ]

    For NBNE's simple SPD workflow, all boxes belong to a single packing
    group (the one Amazon returned in listPackingOptions). Raises
    RuntimeError if the plan has zero boxes.

    All dimensions are taken from FBABox (`length_cm`, `width_cm`,
    `height_cm`, `weight_kg`). All item labels inherit
    FBAShipmentPlanItem.label_owner / prep_owner.
    """
    if not plan.selected_packing_option_id:
        raise RuntimeError(
            f'Plan {plan.id}: cannot build packing groups without a '
            'selected_packing_option_id'
        )
    boxes = list(plan.boxes.all().prefetch_related('contents__plan_item'))
    if not boxes:
        raise RuntimeError(
            f'Plan {plan.id}: no FBABox rows; add boxes in the UI before '
            'setPackingInformation'
        )
    box_payloads: list[dict[str, Any]] = []
    for box in boxes:
        items_payload: list[dict[str, Any]] = []
        for content in box.contents.all():
            plan_item = content.plan_item
            items_payload.append({
                'msku': plan_item.msku,
                'quantity': int(content.quantity),
                'prepOwner': plan_item.prep_owner,
                'labelOwner': plan_item.label_owner,
            })
        if not items_payload:
            raise RuntimeError(
                f'Plan {plan.id} box {box.box_number} has no contents'
            )
        box_payloads.append({
            'boxId': f'box-{box.box_number:03d}',
            'dimensions': {
                'length': float(box.length_cm),
                'width':  float(box.width_cm),
                'height': float(box.height_cm),
                'unitOfMeasurement': 'CM',
            },
            'weight': {
                'value': float(box.weight_kg),
                'unit': 'KG',
            },
            'contentInformationSource': 'BOX_CONTENT_PROVIDED',
            'items': items_payload,
            'quantity': 1,
        })
    return [{
        'packingGroupId': plan.selected_packing_option_id,
        'boxes': box_payloads,
    }]
