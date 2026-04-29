from rest_framework import serializers
from .models import ProductBarcode, PrintJob


class ProductBarcodeSerializer(serializers.ModelSerializer):
    m_number = serializers.CharField(source='product.m_number', read_only=True)

    class Meta:
        model = ProductBarcode
        fields = [
            'id', 'm_number', 'product', 'marketplace', 'barcode_type',
            'barcode_value', 'label_title', 'condition', 'source',
            'last_synced_at', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class PrintJobSerializer(serializers.ModelSerializer):
    m_number = serializers.CharField(source='barcode.product.m_number', read_only=True)
    marketplace = serializers.CharField(source='barcode.marketplace', read_only=True)
    barcode_value = serializers.CharField(source='barcode.barcode_value', read_only=True)
    printer_name = serializers.CharField(source='printer.name', read_only=True, default='')
    printer_slug = serializers.CharField(source='printer.slug', read_only=True, default='')

    class Meta:
        model = PrintJob
        fields = [
            'id', 'barcode', 'm_number', 'marketplace', 'barcode_value',
            'quantity', 'command_language', 'command_payload',
            'status', 'agent_id',
            'claimed_at', 'printed_at', 'error_message', 'retry_count',
            'requested_by', 'printer', 'printer_name', 'printer_slug',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'command_language', 'command_payload', 'status', 'agent_id',
            'claimed_at', 'printed_at', 'error_message', 'retry_count',
            'created_at', 'updated_at', 'printer_name', 'printer_slug',
        ]


class PrintJobAgentSerializer(serializers.ModelSerializer):
    """Serializer for the agent — includes command_payload."""

    class Meta:
        model = PrintJob
        fields = ['id', 'barcode_id', 'quantity', 'command_payload', 'command_language']
