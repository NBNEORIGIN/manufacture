from rest_framework import serializers
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
            'current_stage', 'stages',
            'created_by', 'created_at', 'completed_at',
        ]
        read_only_fields = ['created_by', 'current_stage']
