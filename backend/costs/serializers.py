from rest_framework import serializers

from .models import BlankCost, CostConfig, MNumberCostOverride


class BlankCostSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlankCost
        fields = [
            'id', 'normalized_name', 'display_name',
            'material_cost_gbp', 'labour_minutes',
            'is_composite', 'sample_raw_blank',
            'product_count', 'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'normalized_name', 'is_composite',
                            'sample_raw_blank', 'product_count',
                            'created_at', 'updated_at']


class MNumberCostOverrideSerializer(serializers.ModelSerializer):
    m_number = serializers.CharField(source='product.m_number', read_only=True)
    description = serializers.CharField(source='product.description', read_only=True)
    blank_raw = serializers.CharField(source='product.blank', read_only=True)

    class Meta:
        model = MNumberCostOverride
        fields = [
            'id', 'product', 'm_number', 'description', 'blank_raw',
            'cost_price_gbp', 'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'm_number', 'description', 'blank_raw',
                            'created_at', 'updated_at']


class CostConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = CostConfig
        fields = [
            'labour_rate_gbp_per_hour',
            'overhead_per_unit_gbp',
            'default_material_gbp',
            'vat_rate_uk',
            'updated_at',
        ]
        read_only_fields = ['updated_at']
