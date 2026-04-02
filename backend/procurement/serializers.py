from rest_framework import serializers
from .models import Material


class MaterialSerializer(serializers.ModelSerializer):
    needs_reorder = serializers.BooleanField(read_only=True)

    class Meta:
        model = Material
        fields = [
            'id', 'material_id', 'name', 'category', 'unit_of_measure',
            'current_stock', 'reorder_point', 'standard_order_quantity',
            'preferred_supplier', 'product_page_url', 'lead_time_days',
            'safety_stock', 'in_house_description', 'notes', 'current_price',
            'needs_reorder', 'created_at', 'updated_at',
        ]
