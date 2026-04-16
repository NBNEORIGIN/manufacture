from rest_framework import serializers
from .models import Product, SKU, BlankType


class SKUSerializer(serializers.ModelSerializer):
    class Meta:
        model = SKU
        fields = ['id', 'sku', 'new_sku', 'asin', 'fnsku', 'channel', 'active']


class BlankTypeSerializer(serializers.ModelSerializer):
    product_count = serializers.SerializerMethodField()

    def get_product_count(self, obj):
        count = getattr(obj, '_product_count', None)
        if count is not None:
            return count
        return obj.products.count()

    class Meta:
        model = BlankType
        fields = [
            'id', 'name',
            'length_cm', 'width_cm', 'height_cm', 'weight_g',
            'notes', 'product_count',
            'created_at', 'updated_at',
        ]


class ProductSerializer(serializers.ModelSerializer):
    skus = SKUSerializer(many=True, read_only=True)
    current_stock = serializers.IntegerField(source='stock.current_stock', read_only=True, default=0)
    stock_deficit = serializers.IntegerField(source='stock.stock_deficit', read_only=True, default=0)
    ninety_day_sales = serializers.SerializerMethodField()
    design_machines = serializers.SerializerMethodField()
    production_stage = serializers.SerializerMethodField()
    blank_type_name = serializers.CharField(source='blank_type.name', read_only=True, default=None)

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

    production_order_id = serializers.SerializerMethodField()

    def get_production_order_id(self, obj):
        return getattr(obj, '_active_order_id', None)

    class Meta:
        model = Product
        fields = [
            'id', 'm_number', 'description', 'blank', 'material',
            'is_personalised', 'do_not_restock', 'do_not_restock_reason',
            'image_url', 'active', 'in_progress', 'has_design',
            'machine_type', 'blank_family', 'skus',
            'current_stock', 'stock_deficit', 'ninety_day_sales',
            'design_machines', 'production_stage', 'production_order_id',
            'shipping_length_cm', 'shipping_width_cm', 'shipping_height_cm',
            'shipping_weight_g', 'shipping_dims_overridden',
            'blank_type', 'blank_type_name',
            'created_at', 'updated_at',
        ]
