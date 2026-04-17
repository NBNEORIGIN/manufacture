from rest_framework import serializers
from .models import DispatchOrder


class DispatchOrderSerializer(serializers.ModelSerializer):
    m_number = serializers.CharField(source='product.m_number', read_only=True, default='')
    is_personalised = serializers.BooleanField(read_only=True)
    personalisation_text = serializers.CharField(read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.username', read_only=True, default='')
    completed_by_name = serializers.CharField(source='completed_by.username', read_only=True, default='')

    # Stock-aware fields (Phase 5)
    current_stock = serializers.SerializerMethodField()
    product_is_personalised = serializers.SerializerMethodField()
    can_fulfil_from_stock = serializers.SerializerMethodField()
    blank = serializers.CharField(source='product.blank', read_only=True, default='')
    blank_family = serializers.CharField(source='product.blank_family', read_only=True, default='')

    class Meta:
        model = DispatchOrder
        fields = [
            'id', 'order_id', 'channel', 'order_date', 'status',
            'm_number', 'sku', 'description', 'quantity',
            'customer_name', 'flags',
            'is_personalised', 'personalisation_text',
            'line1', 'line2', 'line3', 'line4', 'line5', 'line6', 'line7', 'graphic',
            'assigned_to', 'assigned_to_name',
            'completed_at', 'completed_by', 'completed_by_name',
            'stock_updated', 'notes',
            'current_stock', 'product_is_personalised', 'can_fulfil_from_stock',
            'blank', 'blank_family',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['completed_at', 'completed_by', 'completed_by_name', 'personalisation_text', 'is_personalised']

    def _get_stock(self, obj):
        """Return the StockLevel.current_stock for this order's product, or 0."""
        if obj.product_id and hasattr(obj.product, 'stock'):
            return obj.product.stock.current_stock
        return 0

    def get_current_stock(self, obj):
        return self._get_stock(obj)

    def get_product_is_personalised(self, obj):
        if obj.product_id:
            return obj.product.is_personalised
        return False

    def get_can_fulfil_from_stock(self, obj):
        if not obj.product_id:
            return False
        if obj.product.is_personalised:
            return False
        return self._get_stock(obj) >= obj.quantity
