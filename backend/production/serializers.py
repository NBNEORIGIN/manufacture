from rest_framework import serializers
from products.models import Product
from .models import ProductionOrder, ProductionStage


class ProductionStageSerializer(serializers.ModelSerializer):
    completed_by_name = serializers.CharField(
        source='completed_by.username', read_only=True, default=''
    )

    class Meta:
        model = ProductionStage
        fields = ['id', 'stage', 'completed', 'completed_at', 'completed_by', 'completed_by_name']
        read_only_fields = ['completed_at', 'completed_by', 'completed_by_name']


class ProductionOrderSerializer(serializers.ModelSerializer):
    stages = ProductionStageSerializer(many=True, read_only=True)
    m_number = serializers.CharField(source='product.m_number', read_only=True)
    description = serializers.CharField(source='product.description', read_only=True)
    blank = serializers.CharField(source='product.blank', read_only=True)
    current_stage = serializers.CharField(read_only=True)

    class Meta:
        model = ProductionOrder
        fields = [
            'id', 'm_number', 'description', 'blank',
            'quantity', 'priority', 'machine', 'notes',
            'current_stage', 'simple_stage', 'stages',
            'created_by', 'created_at', 'completed_at',
        ]
        read_only_fields = ['created_by', 'current_stage']


class ProductionOrderCreateSerializer(serializers.Serializer):
    product = serializers.CharField()  # accepts m_number
    quantity = serializers.IntegerField()
    priority = serializers.IntegerField(default=0)
    machine = serializers.CharField(required=False, default='')
    notes = serializers.CharField(required=False, default='')

    def validate_product(self, value):
        try:
            return Product.objects.get(m_number=value)
        except Product.DoesNotExist:
            raise serializers.ValidationError(f'Product {value} not found')

    def create(self, validated_data):
        return ProductionOrder.objects.create(
            product=validated_data['product'],
            quantity=validated_data['quantity'],
            priority=validated_data['priority'],
            machine=validated_data.get('machine', ''),
            notes=validated_data.get('notes', ''),
            created_by=validated_data.get('created_by'),
        )
