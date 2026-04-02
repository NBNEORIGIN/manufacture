from rest_framework import serializers
from .models import DispatchOrder


class DispatchOrderSerializer(serializers.ModelSerializer):
    m_number = serializers.CharField(source='product.m_number', read_only=True, default='')
    is_personalised = serializers.BooleanField(read_only=True)
    personalisation_text = serializers.CharField(read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.username', read_only=True, default='')
    completed_by_name = serializers.CharField(source='completed_by.username', read_only=True, default='')

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
            'created_at', 'updated_at',
        ]
        read_only_fields = ['completed_at', 'completed_by', 'completed_by_name', 'personalisation_text', 'is_personalised']
