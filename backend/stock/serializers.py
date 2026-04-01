from rest_framework import serializers
from .models import StockLevel


class StockLevelSerializer(serializers.ModelSerializer):
    m_number = serializers.CharField(source='product.m_number', read_only=True)
    description = serializers.CharField(source='product.description', read_only=True)
    blank = serializers.CharField(source='product.blank', read_only=True)

    class Meta:
        model = StockLevel
        fields = [
            'id', 'm_number', 'description', 'blank',
            'current_stock', 'fba_stock', 'sixty_day_sales', 'thirty_day_sales',
            'optimal_stock_30d', 'stock_deficit', 'last_count_date',
            'updated_at',
        ]
        read_only_fields = ['stock_deficit']
