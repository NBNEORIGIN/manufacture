from rest_framework import serializers
from .models import Product, SKU


class SKUSerializer(serializers.ModelSerializer):
    class Meta:
        model = SKU
        fields = ['id', 'sku', 'new_sku', 'asin', 'fnsku', 'channel', 'active']


class ProductSerializer(serializers.ModelSerializer):
    skus = SKUSerializer(many=True, read_only=True)
    current_stock = serializers.IntegerField(source='stock.current_stock', read_only=True, default=0)
    stock_deficit = serializers.IntegerField(source='stock.stock_deficit', read_only=True, default=0)

    class Meta:
        model = Product
        fields = [
            'id', 'm_number', 'description', 'blank', 'material',
            'is_personalised', 'do_not_restock', 'do_not_restock_reason',
            'image_url', 'active', 'in_progress', 'skus',
            'current_stock', 'stock_deficit',
            'created_at', 'updated_at',
        ]
