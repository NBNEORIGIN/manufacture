from rest_framework import serializers
from .models import Shipment, ShipmentItem


class ShipmentItemSerializer(serializers.ModelSerializer):
    m_number = serializers.CharField(source='product.m_number', read_only=True)
    description = serializers.CharField(source='product.description', read_only=True)

    class Meta:
        model = ShipmentItem
        fields = [
            'id', 'm_number', 'description', 'sku',
            'quantity', 'quantity_shipped', 'box_number',
            'amz_restock_quantity', 'stock_at_ship',
        ]


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
    product = serializers.CharField()  # m_number
    quantity = serializers.IntegerField()
    box_number = serializers.IntegerField(required=False)
    sku = serializers.CharField(required=False, default='')
