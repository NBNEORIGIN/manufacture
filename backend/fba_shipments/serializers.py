"""
DRF serializers for the FBA Shipment Automation module.

Separation of concerns:

- List serializers are lean (no nested writes, minimal fields) so the
  plans list endpoint stays fast even with hundreds of historical plans.
- Detail serializers nest items, boxes (with contents), shipments, and
  a bounded slice of recent FBAAPICall rows — the debugging surface.
- Write serializers (item create, box create) are separate from read
  serializers so the incoming payload schema is explicit and reviewable.

Nothing here enqueues Django-Q tasks — views own the task enqueue
boundary so serializer unit tests never accidentally touch the broker.
"""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from fba_shipments.models import (
    FBAAPICall,
    FBABox,
    FBABoxItem,
    FBAShipment,
    FBAShipmentPlan,
    FBAShipmentPlanItem,
)


# --------------------------------------------------------------------------- #
# Plan items                                                                  #
# --------------------------------------------------------------------------- #


class FBAShipmentPlanItemSerializer(serializers.ModelSerializer):
    """Read serializer: plan item with resolved SKU + product details."""

    sku_code = serializers.CharField(source='sku.sku', read_only=True)
    m_number = serializers.CharField(source='sku.product.m_number', read_only=True)
    product_description = serializers.CharField(
        source='sku.product.description', read_only=True,
    )

    class Meta:
        model = FBAShipmentPlanItem
        fields = [
            'id', 'sku', 'sku_code', 'm_number', 'product_description',
            'quantity', 'msku', 'fnsku', 'label_owner', 'prep_owner',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'msku', 'fnsku', 'created_at', 'updated_at']


class FBAShipmentPlanItemCreateSerializer(serializers.Serializer):
    """Write serializer for POST /plans/{id}/items/."""

    sku_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class FBABulkItemsCreateSerializer(serializers.Serializer):
    """Write serializer for bulk add: POST /plans/{id}/items/ with {items: [...]}"""

    items = FBAShipmentPlanItemCreateSerializer(many=True)


# --------------------------------------------------------------------------- #
# Boxes                                                                       #
# --------------------------------------------------------------------------- #


class FBABoxItemSerializer(serializers.ModelSerializer):
    msku = serializers.CharField(source='plan_item.msku', read_only=True)

    class Meta:
        model = FBABoxItem
        fields = ['id', 'plan_item', 'msku', 'quantity']


class FBABoxSerializer(serializers.ModelSerializer):
    """Read serializer: box with nested contents."""

    contents = FBABoxItemSerializer(many=True, read_only=True)

    class Meta:
        model = FBABox
        fields = [
            'id', 'plan', 'shipment', 'box_number',
            'length_cm', 'width_cm', 'height_cm', 'weight_kg',
            'amazon_box_id', 'contents',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'plan', 'shipment', 'amazon_box_id',
                            'created_at', 'updated_at']


class FBABoxContentCreateSerializer(serializers.Serializer):
    plan_item_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class FBABoxCreateSerializer(serializers.Serializer):
    """Write serializer for POST /plans/{id}/boxes/."""

    box_number = serializers.IntegerField(min_value=1)
    length_cm = serializers.DecimalField(max_digits=6, decimal_places=1)
    width_cm = serializers.DecimalField(max_digits=6, decimal_places=1)
    height_cm = serializers.DecimalField(max_digits=6, decimal_places=1)
    weight_kg = serializers.DecimalField(max_digits=6, decimal_places=2)
    contents = FBABoxContentCreateSerializer(many=True)

    def validate_contents(self, value):
        if not value:
            raise serializers.ValidationError('Box must contain at least one item')
        return value


class FBABoxUpdateSerializer(serializers.Serializer):
    """Write serializer for PATCH /plans/{id}/boxes/{box_id}/."""

    box_number = serializers.IntegerField(min_value=1, required=False)
    length_cm = serializers.DecimalField(
        max_digits=6, decimal_places=1, required=False,
    )
    width_cm = serializers.DecimalField(
        max_digits=6, decimal_places=1, required=False,
    )
    height_cm = serializers.DecimalField(
        max_digits=6, decimal_places=1, required=False,
    )
    weight_kg = serializers.DecimalField(
        max_digits=6, decimal_places=2, required=False,
    )


# --------------------------------------------------------------------------- #
# Shipments                                                                   #
# --------------------------------------------------------------------------- #


class FBAShipmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = FBAShipment
        fields = [
            'id', 'shipment_id', 'shipment_confirmation_id', 'destination_fc',
            'labels_url', 'labels_fetched_at',
            'carrier_name', 'tracking_number', 'dispatched_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields  # updated via /dispatch/ endpoint only


class FBAShipmentDispatchSerializer(serializers.Serializer):
    """Write serializer for POST /plans/{id}/shipments/{shipment_id}/dispatch/."""

    carrier_name = serializers.CharField(max_length=80)
    tracking_number = serializers.CharField(max_length=120)


# --------------------------------------------------------------------------- #
# API call audit trail                                                        #
# --------------------------------------------------------------------------- #


class FBAAPICallSerializer(serializers.ModelSerializer):
    class Meta:
        model = FBAAPICall
        fields = [
            'id', 'operation_name', 'response_status', 'operation_id',
            'duration_ms', 'error_message', 'created_at',
        ]


class FBAAPICallDetailSerializer(serializers.ModelSerializer):
    """Heavier variant with full request/response bodies — used by detail endpoint."""

    class Meta:
        model = FBAAPICall
        fields = [
            'id', 'operation_name', 'request_body', 'response_status',
            'response_body', 'operation_id', 'duration_ms', 'error_message',
            'created_at',
        ]


# --------------------------------------------------------------------------- #
# Plan                                                                        #
# --------------------------------------------------------------------------- #


class FBAShipmentPlanListSerializer(serializers.ModelSerializer):
    """Lean serializer for the plans list endpoint."""

    item_count = serializers.IntegerField(read_only=True)
    box_count = serializers.IntegerField(read_only=True)
    shipment_count = serializers.IntegerField(read_only=True)
    is_paused = serializers.BooleanField(read_only=True)
    is_terminal = serializers.BooleanField(read_only=True)

    class Meta:
        model = FBAShipmentPlan
        fields = [
            'id', 'name', 'marketplace', 'status',
            'inbound_plan_id', 'item_count', 'box_count', 'shipment_count',
            'is_paused', 'is_terminal',
            'created_at', 'updated_at',
        ]


class FBAShipmentPlanDetailSerializer(serializers.ModelSerializer):
    """Heavy detail serializer with nested items, boxes, shipments, recent API calls."""

    items = FBAShipmentPlanItemSerializer(many=True, read_only=True)
    boxes = FBABoxSerializer(many=True, read_only=True)
    shipments = FBAShipmentSerializer(many=True, read_only=True)
    recent_api_calls = serializers.SerializerMethodField()
    is_paused = serializers.BooleanField(read_only=True)
    is_terminal = serializers.BooleanField(read_only=True)

    class Meta:
        model = FBAShipmentPlan
        fields = [
            'id', 'name', 'marketplace', 'ship_from_address', 'status',
            'inbound_plan_id',
            'selected_packing_option_id', 'selected_placement_option_id',
            'selected_transportation_option_id', 'selected_delivery_window_id',
            'current_operation_id', 'current_operation_started_at',
            'last_polled_at',
            'error_log',
            'packing_options_snapshot', 'placement_options_snapshot',
            'transportation_options_snapshot', 'delivery_window_snapshot',
            'items', 'boxes', 'shipments', 'recent_api_calls',
            'is_paused', 'is_terminal',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'status', 'inbound_plan_id',
            'selected_packing_option_id', 'selected_placement_option_id',
            'selected_transportation_option_id', 'selected_delivery_window_id',
            'current_operation_id', 'current_operation_started_at',
            'last_polled_at', 'error_log',
            'packing_options_snapshot', 'placement_options_snapshot',
            'transportation_options_snapshot', 'delivery_window_snapshot',
            'items', 'boxes', 'shipments', 'recent_api_calls',
            'created_at', 'updated_at',
        ]

    def get_recent_api_calls(self, obj):
        calls = obj.api_calls.all()[:10]
        return FBAAPICallSerializer(calls, many=True).data


class FBAShipmentPlanCreateSerializer(serializers.ModelSerializer):
    """
    Write serializer for POST /plans/.

    ship_from_address is optional — if omitted, we snapshot
    settings.FBA_DEFAULT_SHIP_FROM onto the plan in the view.
    """

    ship_from_address = serializers.JSONField(required=False)

    class Meta:
        model = FBAShipmentPlan
        fields = ['name', 'marketplace', 'ship_from_address']


# --------------------------------------------------------------------------- #
# Pick-option actions                                                         #
# --------------------------------------------------------------------------- #


class PickPackingOptionSerializer(serializers.Serializer):
    packing_option_id = serializers.CharField(max_length=64)


class PickPlacementOptionSerializer(serializers.Serializer):
    placement_option_id = serializers.CharField(max_length=64)
