from rest_framework import serializers
from django.db.models import OuterRef, Subquery
from .models import Shipment, ShipmentItem


class ShipmentItemSerializer(serializers.ModelSerializer):
    m_number = serializers.CharField(source='product.m_number', read_only=True)
    description = serializers.CharField(source='product.description', read_only=True)
    blank_family = serializers.CharField(source='product.blank_family', read_only=True)
    current_stock = serializers.SerializerMethodField()
    production_stage = serializers.SerializerMethodField()

    class Meta:
        model = ShipmentItem
        fields = [
            'id', 'product', 'm_number', 'description', 'sku',
            'quantity', 'quantity_shipped', 'box_number',
            'amz_restock_quantity', 'stock_at_ship',
            'machine_assignment', 'stock_taken', 'item_notes',
            'current_stock', 'production_stage', 'blank_family',
        ]
        read_only_fields = ['stock_at_ship']

    def get_current_stock(self, obj) -> int:
        stock = getattr(obj.product, 'stock', None)
        return stock.current_stock if stock else 0

    def get_production_stage(self, obj) -> str:
        """Latest incomplete ProductionOrder.simple_stage for this product."""
        from production.models import ProductionOrder
        po = (
            ProductionOrder.objects
            .filter(product=obj.product, completed_at__isnull=True)
            .order_by('-created_at')
            .first()
        )
        return po.simple_stage if po and po.simple_stage else ''


class ShipmentSerializer(serializers.ModelSerializer):
    items = ShipmentItemSerializer(many=True, read_only=True)
    item_count = serializers.IntegerField(source='items.count', read_only=True)

    class Meta:
        model = Shipment
        fields = [
            'id', 'country', 'status', 'shipment_date',
            'total_units', 'box_count', 'notes',
            'item_count', 'items',
            'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_by', 'total_units', 'box_count']


class ShipmentListSerializer(serializers.ModelSerializer):
    item_count = serializers.IntegerField(source='items.count', read_only=True)

    class Meta:
        model = Shipment
        fields = [
            'id', 'country', 'status', 'shipment_date',
            'total_units', 'box_count', 'notes',
            'item_count', 'created_at',
        ]


class ShipmentItemCreateSerializer(serializers.Serializer):
    """Accepts either product_id (int) or product m_number (string)."""
    product = serializers.CharField()
    quantity = serializers.IntegerField()
    box_number = serializers.IntegerField(required=False, allow_null=True)
    sku = serializers.CharField(required=False, default='', allow_blank=True)
    machine_assignment = serializers.CharField(required=False, default='', allow_blank=True)
