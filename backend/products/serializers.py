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
    ninety_day_sales = serializers.SerializerMethodField()
    design_machines = serializers.SerializerMethodField()
    production_stage = serializers.SerializerMethodField()

    def get_ninety_day_sales(self, obj):
        try:
            return (obj.stock.thirty_day_sales or 0) * 3
        except Exception:
            return 0

    def get_design_machines(self, obj):
        try:
            return obj.design.machines_ready()
        except Exception:
            return []

    def get_production_stage(self, obj):
        # Uses annotation injected by viewset (single subquery, no N+1)
        return getattr(obj, '_active_stage', None)

    class Meta:
        model = Product
        fields = [
            'id', 'm_number', 'description', 'blank', 'material',
            'is_personalised', 'do_not_restock', 'do_not_restock_reason',
            'image_url', 'active', 'in_progress', 'has_design',
            'machine_type', 'blank_family', 'skus',
            'current_stock', 'stock_deficit', 'ninety_day_sales',
            'design_machines', 'production_stage',
            'created_at', 'updated_at',
        ]
