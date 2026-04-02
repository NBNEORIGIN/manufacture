from rest_framework import serializers
from .models_records import ProductionRecord


class ProductionRecordSerializer(serializers.ModelSerializer):
    m_number = serializers.CharField(source='product.m_number', read_only=True, default='')
    error_rate = serializers.FloatField(read_only=True)

    class Meta:
        model = ProductionRecord
        fields = [
            'id', 'date', 'week_number', 'm_number', 'sku',
            'number_printed', 'errors', 'total_made', 'error_rate',
            'machine', 'failure_reason', 'correction',
            'recorded_by', 'created_at',
        ]
