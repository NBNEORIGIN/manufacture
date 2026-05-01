from rest_framework import serializers
from django.db.models import OuterRef, Subquery
from .models import Shipment, ShipmentItem


class ShipmentItemSerializer(serializers.ModelSerializer):
    m_number = serializers.CharField(source='product.m_number', read_only=True)
    description = serializers.CharField(source='product.description', read_only=True)
    blank_family = serializers.CharField(source='product.blank_family', read_only=True)
    current_stock = serializers.SerializerMethodField()
    production_stage = serializers.SerializerMethodField()

    # Ivan review #20: for the per-shipment Simple column. Simple = max(0,
    # units_sold_90d − fba_stock). We expose the inputs rather than the
    # computed value so the frontend can recompute live alongside the
    # existing Restock-tab logic and stay consistent.
    units_sold_90d = serializers.SerializerMethodField()
    fba_stock = serializers.SerializerMethodField()

    # Ivan review #20: per-row "print barcode" button needs the
    # ProductBarcode id for this (product, marketplace) pair. Marketplace
    # comes from the parent Shipment.country.
    barcode_id = serializers.SerializerMethodField()

    class Meta:
        model = ShipmentItem
        fields = [
            'id', 'product', 'm_number', 'description', 'sku',
            'quantity', 'quantity_shipped', 'box_number',
            'amz_restock_quantity', 'stock_at_ship',
            'machine_assignment', 'stock_taken', 'item_notes',
            'current_stock', 'production_stage', 'blank_family',
            'units_sold_90d', 'fba_stock', 'barcode_id',
        ]
        read_only_fields = ['stock_at_ship']

    def get_current_stock(self, obj) -> int:
        stock = getattr(obj.product, 'stock', None)
        return stock.current_stock if stock else 0

    def get_production_stage(self, obj) -> str:
        """Latest incomplete ProductionOrder.simple_stage for this product."""
        from production.models import ProductionOrder
        po = (
            ProductionOrder.objects
            .filter(product=obj.product, completed_at__isnull=True)
            .order_by('-created_at')
            .first()
        )
        return po.simple_stage if po and po.simple_stage else ''

    def _shipment_marketplace(self, obj) -> str:
        """
        Return the marketplace code for this item's shipment, with the
        UK→GB alias applied. Shipment.country uses 'UK' (Manufacture's
        internal code), but downstream tables (RestockItem populated
        from the SP-API pipeline, ami_orders, ProductBarcode) store the
        Amazon-side 'GB'. Using 'UK' here returns zero rows silently.
        """
        if not obj.shipment_id:
            return ''
        country = (obj.shipment.country or '').upper()
        return 'GB' if country == 'UK' else country

    def _restock_for(self, obj):
        """Latest RestockItem for this (m_number, shipment marketplace)."""
        from restock.models import RestockItem
        marketplace = self._shipment_marketplace(obj)
        if not marketplace or not obj.product_id:
            return None
        # RestockItem keys by m_number (CharField), not by Product FK.
        m_number = (obj.product.m_number or '').strip()
        if not m_number:
            return None
        return (
            RestockItem.objects
            .filter(m_number=m_number, marketplace=marketplace)
            .order_by('-updated_at')
            .first()
        )

    def get_units_sold_90d(self, obj) -> int:
        try:
            ri = self._restock_for(obj)
            return ri.units_sold_90d if ri else 0
        except Exception:
            # Never let this block the shipment detail view from rendering.
            return 0

    def get_fba_stock(self, obj) -> int:
        # FBA stock for the simple metric is "everything Amazon has against
        # this SKU in this marketplace": available + inbound + reserved.
        # That's what RestockItem.units_total holds.
        try:
            ri = self._restock_for(obj)
            return ri.units_total if ri else 0
        except Exception:
            return 0

    def get_barcode_id(self, obj):
        try:
            from barcodes.models import ProductBarcode
            marketplace = self._shipment_marketplace(obj)
            if not marketplace or not obj.product_id:
                return None
            bc = (
                ProductBarcode.objects
                .filter(product=obj.product, marketplace=marketplace)
                .order_by('-updated_at')
                .first()
            )
            return bc.id if bc else None
        except Exception:
            return None


class ShipmentSerializer(serializers.ModelSerializer):
    items = ShipmentItemSerializer(many=True, read_only=True)
    item_count = serializers.IntegerField(source='items.count', read_only=True)

    class Meta:
        model = Shipment
        fields = [
            'id', 'country', 'status', 'shipment_date',
            'total_units', 'box_count', 'notes',
            'item_count', 'items',
            'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_by', 'total_units', 'box_count']


class ShipmentListSerializer(serializers.ModelSerializer):
    item_count = serializers.IntegerField(source='items.count', read_only=True)

    class Meta:
        model = Shipment
        fields = [
            'id', 'country', 'status', 'shipment_date',
            'total_units', 'box_count', 'notes',
            'item_count', 'created_at',
        ]


class ShipmentItemCreateSerializer(serializers.Serializer):
    """Accepts either product_id (int) or product m_number (string)."""
    product = serializers.CharField()
    quantity = serializers.IntegerField()
    box_number = serializers.IntegerField(required=False, allow_null=True)
    sku = serializers.CharField(required=False, default='', allow_blank=True)
    machine_assignment = serializers.CharField(required=False, default='', allow_blank=True)
