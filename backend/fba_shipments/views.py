"""
REST API for the FBA Shipment Automation module.

All endpoints live under `/api/fba/`. The `FBAShipmentPlanViewSet` is the
main entry point and exposes both standard CRUD and the workflow-specific
actions (submit, pick options, retry, dispatch, labels).

Validation on `submit/` is the most important part of this module: it
gates the transition from draft to `items_added`, which is when the
Django-Q state machine takes over. Any problem we can detect upfront
saves debugging time during the async workflow.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from barcodes.models import ProductBarcode
from fba_shipments.models import (
    FBAAPICall,
    FBABox,
    FBABoxItem,
    FBAShipment,
    FBAShipmentPlan,
    FBAShipmentPlanItem,
)
from fba_shipments.serializers import (
    FBAAPICallDetailSerializer,
    FBABoxCreateSerializer,
    FBABoxSerializer,
    FBABoxUpdateSerializer,
    FBAShipmentDispatchSerializer,
    FBAShipmentPlanCreateSerializer,
    FBAShipmentPlanDetailSerializer,
    FBAShipmentPlanItemSerializer,
    FBAShipmentPlanListSerializer,
    FBABulkItemsCreateSerializer,
    PickPackingOptionSerializer,
    PickPlacementOptionSerializer,
)
from fba_shipments.services import workflow as wf
from products.models import SKU

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _require_status(plan: FBAShipmentPlan, allowed: set[str]) -> None:
    """Raise a DRF validation error if plan.status is not in `allowed`."""
    if plan.status not in allowed:
        from rest_framework.exceptions import ValidationError
        raise ValidationError(
            {'detail':
             f'Action not valid in status {plan.status!r}. Allowed: {sorted(allowed)}'}
        )


def _resolve_fnsku(product_id: int, marketplace: str) -> str:
    """Look up an FNSKU for a product in a marketplace. Returns '' if none."""
    row = (
        ProductBarcode.objects
        .filter(
            product_id=product_id,
            barcode_type='FNSKU',
            marketplace__in=[marketplace, 'ALL'],
        )
        .exclude(barcode_value='')
        .order_by('-updated_at')
        .first()
    )
    return row.barcode_value if row else ''


def _validate_plan_ready_for_submit(plan: FBAShipmentPlan) -> list[str]:
    """
    Return a list of human-readable validation errors for plan submission.
    Empty list == ready to submit.
    """
    errors: list[str] = []

    items = list(plan.items.select_related('sku__product').all())
    if not items:
        errors.append('Plan has no items.')
        return errors

    # 1. Every item has an FNSKU snapshotted
    for item in items:
        if not item.fnsku:
            errors.append(
                f'Item {item.msku}: no FNSKU recorded '
                f'(re-add after running barcodes FNSKU sync for {plan.marketplace}).'
            )

    # 2. Every item's Product has shipping dimensions
    dim_fields = ('shipping_length_cm', 'shipping_width_cm',
                  'shipping_height_cm', 'shipping_weight_g')
    for item in items:
        product = item.sku.product
        missing = [f for f in dim_fields
                   if not getattr(product, f, None)]
        if missing:
            errors.append(
                f'Item {item.msku} (M{product.m_number}): missing shipping '
                f'dimensions ({", ".join(missing)}).'
            )

    # 3. Boxes exist
    boxes = list(plan.boxes.prefetch_related('contents').all())
    if not boxes:
        errors.append('Plan has no boxes. Add at least one box with contents before submitting.')
        return errors

    # 4. Box contents quantities sum to item quantities
    packed_totals: dict[int, int] = {}
    for box in boxes:
        for content in box.contents.all():
            packed_totals[content.plan_item_id] = (
                packed_totals.get(content.plan_item_id, 0) + content.quantity
            )
    for item in items:
        packed = packed_totals.get(item.id, 0)
        if packed != item.quantity:
            errors.append(
                f'Item {item.msku}: quantity {item.quantity} does not match '
                f'packed total {packed}.'
            )

    return errors


# --------------------------------------------------------------------------- #
# Main viewset                                                                #
# --------------------------------------------------------------------------- #


class FBAShipmentPlanViewSet(viewsets.ModelViewSet):
    """
    CRUD + workflow actions for FBA shipment plans.

    Routes:
        GET    /api/fba/plans/                          list
        POST   /api/fba/plans/                          create draft
        GET    /api/fba/plans/{pk}/                     detail
        PATCH  /api/fba/plans/{pk}/                     update (draft only)
        DELETE /api/fba/plans/{pk}/                     cancel

        POST   /api/fba/plans/{pk}/items/               add items
        DELETE /api/fba/plans/{pk}/items/{item_id}/     remove item (draft only)

        POST   /api/fba/plans/{pk}/boxes/               add box
        PATCH  /api/fba/plans/{pk}/boxes/{box_id}/      update box
        DELETE /api/fba/plans/{pk}/boxes/{box_id}/      remove box

        POST   /api/fba/plans/{pk}/submit/              draft → items_added + enqueue
        POST   /api/fba/plans/{pk}/pick-packing-option/
        POST   /api/fba/plans/{pk}/pick-placement-option/
        POST   /api/fba/plans/{pk}/retry/               error → previous step, re-enqueue
        GET    /api/fba/plans/{pk}/labels/              proxy to Amazon PDF
        POST   /api/fba/plans/{pk}/shipments/{ship_id}/dispatch/
        GET    /api/fba/plans/{pk}/api-calls/
    """

    queryset = FBAShipmentPlan.objects.all()
    permission_classes = [AllowAny]  # matches the rest of manufacture

    # -------- Serializer dispatch ---------------------------------------- #

    def get_serializer_class(self):
        if self.action == 'list':
            return FBAShipmentPlanListSerializer
        if self.action == 'create':
            return FBAShipmentPlanCreateSerializer
        return FBAShipmentPlanDetailSerializer

    # -------- Queryset tuning -------------------------------------------- #

    def get_queryset(self):
        qs = FBAShipmentPlan.objects.all().order_by('-created_at', '-id')
        # Filters for the list endpoint
        if self.action == 'list':
            marketplace = self.request.query_params.get('marketplace')
            status_filter = self.request.query_params.get('status')
            if marketplace:
                qs = qs.filter(marketplace=marketplace)
            if status_filter:
                qs = qs.filter(status=status_filter)
            qs = qs.annotate(
                item_count=Count('items', distinct=True),
                box_count=Count('boxes', distinct=True),
                shipment_count=Count('shipments', distinct=True),
            )
        if self.action == 'retrieve':
            qs = qs.prefetch_related(
                'items__sku__product',
                'boxes__contents__plan_item',
                'shipments',
                'api_calls',
            )
        return qs

    # -------- Create with default ship_from ------------------------------ #

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if 'ship_from_address' not in data or not data['ship_from_address']:
            data['ship_from_address'] = getattr(
                settings, 'FBA_DEFAULT_SHIP_FROM', {},
            )
        plan = FBAShipmentPlan.objects.create(status='draft', **data)
        return Response(
            FBAShipmentPlanDetailSerializer(plan).data,
            status=status.HTTP_201_CREATED,
        )

    # -------- Update: only allowed in draft ------------------------------ #

    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        plan = self.get_object()
        _require_status(plan, {'draft'})
        allowed = {'name', 'ship_from_address'}
        for field, value in request.data.items():
            if field in allowed:
                setattr(plan, field, value)
        plan.save()
        return Response(FBAShipmentPlanDetailSerializer(plan).data)

    # -------- Cancel (DELETE) -------------------------------------------- #

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        """
        Cancel a plan. If Amazon has an inbound plan for it and we haven't
        passed placement_confirmed, call cancelInboundPlan via the API. We
        mark the local plan as cancelled regardless of whether the API call
        succeeds — the API error is captured in FBAAPICall for debugging.
        """
        plan = self.get_object()
        if plan.status == 'cancelled':
            return Response(status=status.HTTP_204_NO_CONTENT)

        pre_placement_confirmed = plan.status not in {
            'placement_confirmed', 'transport_generating',
            'transport_options_fetching', 'transport_options_ready',
            'delivery_window_generating', 'delivery_window_fetching',
            'delivery_window_ready', 'transport_confirming',
            'transport_confirmed', 'labels_fetching', 'ready_to_ship',
            'dispatched', 'cancelled', 'error',
        }
        if plan.inbound_plan_id and pre_placement_confirmed:
            try:
                from fba_shipments.services.sp_api_client import FBAInboundClient
                client = FBAInboundClient(
                    marketplace_code=plan.marketplace, plan=plan,
                )
                client.cancel_inbound_plan(plan.inbound_plan_id)
            except Exception:  # noqa: BLE001
                logger.exception(
                    'cancelInboundPlan failed for plan %s; marking cancelled '
                    'locally anyway',
                    plan.id,
                )

        plan.status = 'cancelled'
        plan.save()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # -------- Items sub-resource ----------------------------------------- #

    @action(detail=True, methods=['post', 'get'], url_path='items')
    def items(self, request: Request, pk: int | None = None) -> Response:
        plan = self.get_object()
        if request.method == 'GET':
            qs = plan.items.select_related('sku__product').all()
            return Response(FBAShipmentPlanItemSerializer(qs, many=True).data)

        # POST: bulk add
        _require_status(plan, {'draft'})
        serializer = FBABulkItemsCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        created: list[FBAShipmentPlanItem] = []
        with transaction.atomic():
            for entry in serializer.validated_data['items']:
                sku = get_object_or_404(SKU, pk=entry['sku_id'])
                fnsku = _resolve_fnsku(sku.product_id, plan.marketplace)
                item, was_created = FBAShipmentPlanItem.objects.update_or_create(
                    plan=plan,
                    sku=sku,
                    defaults={
                        'quantity': entry['quantity'],
                        'msku': sku.sku,
                        'fnsku': fnsku,
                        'label_owner': 'SELLER',
                        'prep_owner': 'SELLER',
                    },
                )
                created.append(item)
        return Response(
            FBAShipmentPlanItemSerializer(created, many=True).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['delete'], url_path=r'items/(?P<item_id>\d+)')
    def remove_item(self, request: Request, pk: int | None = None,
                    item_id: str | None = None) -> Response:
        plan = self.get_object()
        _require_status(plan, {'draft'})
        item = get_object_or_404(
            FBAShipmentPlanItem, pk=item_id, plan=plan,
        )
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # -------- Boxes sub-resource ----------------------------------------- #

    @action(detail=True, methods=['post', 'get'], url_path='boxes')
    def boxes(self, request: Request, pk: int | None = None) -> Response:
        plan = self.get_object()
        if request.method == 'GET':
            qs = plan.boxes.prefetch_related('contents__plan_item').all()
            return Response(FBABoxSerializer(qs, many=True).data)

        _require_status(plan, {'draft', 'packing_options_ready'})
        serializer = FBABoxCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with transaction.atomic():
            box = FBABox.objects.create(
                plan=plan,
                box_number=data['box_number'],
                length_cm=data['length_cm'],
                width_cm=data['width_cm'],
                height_cm=data['height_cm'],
                weight_kg=data['weight_kg'],
            )
            for content in data['contents']:
                plan_item = get_object_or_404(
                    FBAShipmentPlanItem, pk=content['plan_item_id'], plan=plan,
                )
                FBABoxItem.objects.create(
                    box=box,
                    plan_item=plan_item,
                    quantity=content['quantity'],
                )
        return Response(
            FBABoxSerializer(box).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['patch', 'delete'],
            url_path=r'boxes/(?P<box_id>\d+)')
    def box(self, request: Request, pk: int | None = None,
            box_id: str | None = None) -> Response:
        plan = self.get_object()
        box = get_object_or_404(FBABox, pk=box_id, plan=plan)

        if request.method == 'DELETE':
            _require_status(plan, {'draft', 'packing_options_ready'})
            box.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        # PATCH
        _require_status(plan, {'draft', 'packing_options_ready'})
        serializer = FBABoxUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(box, field, value)
        box.save()
        return Response(FBABoxSerializer(box).data)

    # -------- Submit: draft → items_added + enqueue ---------------------- #

    @action(detail=True, methods=['post'])
    def submit(self, request: Request, pk: int | None = None) -> Response:
        plan = self.get_object()
        _require_status(plan, {'draft'})
        errors = _validate_plan_ready_for_submit(plan)
        if errors:
            return Response(
                {'errors': errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        plan.status = 'items_added'
        plan.save()
        wf.kick_off(plan)
        return Response(FBAShipmentPlanDetailSerializer(plan).data)

    # -------- Pick packing option --------------------------------------- #

    @action(detail=True, methods=['post'], url_path='pick-packing-option')
    def pick_packing_option(self, request: Request, pk: int | None = None) -> Response:
        plan = self.get_object()
        _require_status(plan, {'packing_options_ready'})
        serializer = PickPackingOptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        chosen = serializer.validated_data['packing_option_id']

        # Verify the option is one the plan actually received
        snapshot = plan.packing_options_snapshot or {}
        known_ids = {
            o.get('packingOptionId', '')
            for o in snapshot.get('packingOptions', []) or []
        }
        if known_ids and chosen not in known_ids:
            return Response(
                {'detail': f'packing_option_id {chosen!r} not in snapshot. '
                           f'Known: {sorted(known_ids)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        plan.selected_packing_option_id = chosen
        plan.save()
        wf.kick_off(plan)
        return Response(FBAShipmentPlanDetailSerializer(plan).data)

    # -------- Pick placement option ------------------------------------- #

    @action(detail=True, methods=['post'], url_path='pick-placement-option')
    def pick_placement_option(self, request: Request, pk: int | None = None) -> Response:
        plan = self.get_object()
        _require_status(plan, {'placement_options_ready'})
        serializer = PickPlacementOptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        chosen = serializer.validated_data['placement_option_id']

        snapshot = plan.placement_options_snapshot or {}
        known_ids = {
            o.get('placementOptionId', '')
            for o in snapshot.get('placementOptions', []) or []
        }
        if known_ids and chosen not in known_ids:
            return Response(
                {'detail': f'placement_option_id {chosen!r} not in snapshot. '
                           f'Known: {sorted(known_ids)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        plan.selected_placement_option_id = chosen
        plan.save()
        wf.kick_off(plan)
        return Response(FBAShipmentPlanDetailSerializer(plan).data)

    # -------- Retry ------------------------------------------------------ #

    @action(detail=True, methods=['post'])
    def retry(self, request: Request, pk: int | None = None) -> Response:
        """
        Retry a plan stuck in 'error'. The user tells us which status to
        rewind to (defaulting to the last non-error status from error_log);
        we set that and re-enqueue. Rewind target is optional in the body.
        """
        plan = self.get_object()
        _require_status(plan, {'error'})

        target = request.data.get('rewind_to')
        if not target:
            # Default: rewind to the step that failed most recently
            if plan.error_log:
                target = plan.error_log[-1].get('step', 'items_added')
            else:
                target = 'items_added'

        valid_statuses = {s for s, _ in FBAShipmentPlan.STATUS_CHOICES}
        if target not in valid_statuses or target in FBAShipmentPlan.TERMINAL_STATUSES:
            return Response(
                {'detail': f'rewind_to {target!r} is not a valid non-terminal status.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        plan.status = target
        plan.save()
        wf.kick_off(plan)
        return Response(FBAShipmentPlanDetailSerializer(plan).data)

    # -------- Labels proxy ---------------------------------------------- #

    @action(detail=True, methods=['get'])
    def labels(self, request: Request, pk: int | None = None):
        """
        Proxy the first shipment's labels PDF through to the browser. If
        the plan has multiple shipments the caller can pass ?shipment_id=
        to target a specific one.
        """
        plan = self.get_object()
        shipment_id_q = request.query_params.get('shipment_id')
        shipments = plan.shipments.all()
        if shipment_id_q:
            shipments = shipments.filter(
                Q(shipment_id=shipment_id_q)
                | Q(shipment_confirmation_id=shipment_id_q),
            )
        shipment = shipments.first()
        if shipment is None or not shipment.labels_url:
            return Response(
                {'detail': 'No labels available for this plan/shipment yet.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            upstream = requests.get(shipment.labels_url, stream=True, timeout=30)
        except requests.RequestException as exc:
            logger.exception('Labels proxy fetch failed for plan %s', plan.id)
            return Response(
                {'detail': f'Labels upstream fetch failed: {exc}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        if upstream.status_code != 200:
            return Response(
                {'detail': f'Upstream returned {upstream.status_code}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        response = StreamingHttpResponse(
            upstream.iter_content(chunk_size=8192),
            content_type=upstream.headers.get('Content-Type', 'application/pdf'),
        )
        response['Content-Disposition'] = (
            f'attachment; filename="{shipment.shipment_confirmation_id or shipment.shipment_id}.pdf"'
        )
        return response

    # -------- Dispatch shipment ----------------------------------------- #

    @action(
        detail=True,
        methods=['post'],
        url_path=r'shipments/(?P<shipment_pk>\d+)/dispatch',
    )
    def dispatch_shipment(self, request: Request, pk: int | None = None,
                          shipment_pk: str | None = None) -> Response:
        """
        Record that a shipment has physically left the building. Captures
        carrier name and tracking number. If this is the last non-
        dispatched shipment on the plan, the plan status advances to
        'dispatched'.

        See the project memory note: carrier booking is manual for Phase 2 —
        Ben books with Evri/etc. externally and posts the tracking number
        here via the UI.
        """
        plan = self.get_object()
        _require_status(plan, {'ready_to_ship', 'dispatched'})
        shipment = get_object_or_404(
            FBAShipment, pk=shipment_pk, plan=plan,
        )
        serializer = FBAShipmentDispatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        shipment.carrier_name = serializer.validated_data['carrier_name']
        shipment.tracking_number = serializer.validated_data['tracking_number']
        shipment.dispatched_at = timezone.now()
        shipment.save()

        # If every shipment now has a tracking number, advance plan to 'dispatched'
        if not plan.shipments.filter(tracking_number='').exists():
            plan.status = 'dispatched'
            plan.save()

        return Response({
            'plan': FBAShipmentPlanDetailSerializer(plan).data,
        })

    # -------- API call audit log ---------------------------------------- #

    @action(detail=True, methods=['get'], url_path='api-calls')
    def api_calls(self, request: Request, pk: int | None = None) -> Response:
        plan = self.get_object()
        limit = int(request.query_params.get('limit', 50))
        limit = max(1, min(limit, 500))
        calls = plan.api_calls.order_by('-created_at', '-id')[:limit]
        return Response(
            FBAAPICallDetailSerializer(calls, many=True).data,
        )


# --------------------------------------------------------------------------- #
# Preflight endpoint                                                          #
# --------------------------------------------------------------------------- #


@api_view(['GET'])
@permission_classes([AllowAny])
def preflight(request: Request) -> Response:
    """
    JSON version of `manage.py fba_preflight_check`. Query: ?marketplace=UK.

    Returns:
        {
          "marketplace": "UK",
          "active_skus": 42,
          "with_fnsku": 38,
          "with_dims": 40,
          "fully_ready": 37,
          "ready": false,
          "missing_fnsku": [{"m_number": "...", "sku": "..."}, ...],
          "missing_dims":  [{"m_number": "...", "description": "..."}, ...],
          "prep_category_reminder": "..."
        }
    """
    marketplace = request.query_params.get('marketplace', 'UK').upper()
    from fba_shipments.models import FBA_MARKETPLACE_CHOICES
    supported = {code for code, _ in FBA_MARKETPLACE_CHOICES}
    if marketplace not in supported:
        return Response(
            {'detail': f'Unsupported marketplace {marketplace!r}. Supported: {sorted(supported)}'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    from products.models import Product, SKU

    channel_map = {'UK': {'UK'}, 'US': {'US'}, 'CA': {'CA'},
                   'AU': {'AU'}, 'DE': {'DE'}}
    channels = channel_map[marketplace]
    active_skus = list(
        SKU.objects
        .filter(channel__in=channels, active=True, product__active=True)
        .select_related('product')
    )
    total = len(active_skus)

    fnsku_product_ids = set(
        ProductBarcode.objects
        .filter(
            barcode_type='FNSKU',
            marketplace__in=[marketplace, 'ALL'],
        )
        .exclude(barcode_value='')
        .values_list('product_id', flat=True)
    )

    dim_fields = ('shipping_length_cm', 'shipping_width_cm',
                  'shipping_height_cm', 'shipping_weight_g')
    dims_filter = Q()
    for f in dim_fields:
        dims_filter &= Q(**{f'{f}__isnull': False}) & ~Q(**{f: 0})
    dims_product_ids = set(
        Product.objects.filter(dims_filter).values_list('id', flat=True)
    )

    missing_fnsku = []
    missing_dims = []
    fully_ready = 0
    for sku in active_skus:
        has_fnsku = sku.product_id in fnsku_product_ids
        has_dims = sku.product_id in dims_product_ids
        if not has_fnsku:
            missing_fnsku.append({
                'm_number': sku.product.m_number,
                'sku': sku.sku,
            })
        if not has_dims:
            missing_dims.append({
                'm_number': sku.product.m_number,
                'description': sku.product.description,
            })
        if has_fnsku and has_dims:
            fully_ready += 1

    return Response({
        'marketplace': marketplace,
        'active_skus': total,
        'with_fnsku': total - len(missing_fnsku),
        'with_dims': total - len(missing_dims),
        'fully_ready': fully_ready,
        'ready': fully_ready == total and total > 0,
        'missing_fnsku': missing_fnsku,
        'missing_dims': missing_dims,
        'prep_category_reminder': (
            'Prep category must be set per SKU in Seller Central as a one-time '
            'manual step (v2024-03-20 does not accept PrepDetailList). If '
            'createInboundPlan fails with FBA_INB_0182, check the prep category first.'
        ),
    })
