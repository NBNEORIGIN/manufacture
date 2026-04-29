"""
Shipment views (Ivan review #12 rework).

Endpoints:
- POST /api/shipments/                           — create; auto-populates from Restock Rec. Qty > 0
- POST /api/shipments/{id}/add-items/            — manual add item(s)
- POST /api/shipments/{id}/mark-shipped/
- GET  /api/shipments/stats/
- PATCH  /api/shipments/items/{id}/              — update fields (machine, stock_taken, quantity_shipped, quantity, box_number)
- DELETE /api/shipments/items/{id}/              — remove single item
"""
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from products.models import Product
from stock.models import StockLevel
from .models import Shipment, ShipmentItem
from .serializers import (
    ShipmentSerializer,
    ShipmentListSerializer,
    ShipmentItemSerializer,
    ShipmentItemCreateSerializer,
)


# ── helpers ───────────────────────────────────────────────────────────────

def _default_machine_for(product: Product, required_qty: int) -> str:
    """
    Ivan review #12 item 6/7:
    - If stock >= required: machine = STOCK (user can change to UV/SUB)
    - Else: machine = '' (empty, user must choose UV/SUB)
    """
    stock = getattr(product, 'stock', None)
    current = stock.current_stock if stock else 0
    return 'STOCK' if current >= required_qty else ''


def _active_stage(product) -> str:
    """Latest incomplete ProductionOrder.simple_stage for this product."""
    if not product:
        return ''
    from production.models import ProductionOrder
    po = (
        ProductionOrder.objects
        .filter(product=product, completed_at__isnull=True)
        .order_by('-created_at').first()
    )
    return po.simple_stage if po and po.simple_stage else ''


def _active_order_id(product):
    if not product:
        return None
    from production.models import ProductionOrder
    po = (
        ProductionOrder.objects
        .filter(product=product, completed_at__isnull=True)
        .order_by('-created_at').first()
    )
    return po.id if po else None


def _resolve_product(product_ref) -> Product:
    """Accept int product_id or str m_number."""
    if isinstance(product_ref, int) or (isinstance(product_ref, str) and product_ref.isdigit()):
        return Product.objects.filter(pk=int(product_ref)).first()
    m = str(product_ref).strip().upper()
    if not m.startswith('M'):
        m = 'M' + m
    return Product.objects.filter(m_number=m).first()


def _lookup_sku(product: Product, country: str) -> str:
    """
    Return the best-matching marketplace SKU for `product` in `country`.

    Match priority:
      1. Active SKU row for the exact channel (UK/US/CA/AU/DE/FR/IT)
      2. Any active SKU row (oldest first — usually the primary listing)
      3. Empty string — caller should fall back to m_number.
    """
    if product is None:
        return ''
    from products.models import SKU
    channel_map = {'UK': 'UK', 'GB': 'UK', 'US': 'US', 'CA': 'CA',
                   'AU': 'AU', 'DE': 'DE', 'FR': 'FR', 'IT': 'IT'}
    channel = channel_map.get((country or '').upper(), (country or '').upper())
    row = (
        SKU.objects
        .filter(product=product, channel=channel, active=True)
        .order_by('id')
        .first()
    )
    if row:
        return row.sku
    row = (
        SKU.objects
        .filter(product=product, active=True)
        .order_by('id')
        .first()
    )
    return row.sku if row else ''


def _notify_ivan_uv(item: ShipmentItem) -> None:
    """
    Ivan review #12 item 8: when an item's machine is set to UV,
    create a JobAssignment for Ivan with country + M-number + qty.
    """
    from production.models_assignment import JobAssignment, JobAssignmentUser

    ivan = User.objects.filter(email='ivan@nbnesigns.com').first()
    if not ivan:
        return

    required = max(0, item.quantity - item.stock_taken)
    notes = (
        f'UV make for {item.shipment.get_country_display()} '
        f'shipment FBA-{item.shipment_id}: {item.product.m_number} x{required}'
    )
    assignment = JobAssignment.objects.create(
        product=item.product,
        assigned_by=None,
        quantity=required if required > 0 else item.quantity,
        notes=notes,
        status='pending',
    )
    JobAssignmentUser.objects.create(
        assignment=assignment, user=ivan, seen=False,
    )


# ── viewset ───────────────────────────────────────────────────────────────

class ShipmentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['country', 'status']
    search_fields = ['notes', 'items__product__m_number']
    ordering_fields = ['shipment_date', 'created_at', 'total_units']
    ordering = ['-shipment_date', '-created_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return ShipmentListSerializer
        return ShipmentSerializer

    def get_queryset(self):
        return Shipment.objects.prefetch_related('items', 'items__product', 'items__product__stock').all()

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        shipment = serializer.save(created_by=user)
        # Ivan review #12 item 2: auto-populate from Restock Rec. Qty > 0
        self._auto_populate_from_restock(shipment)

    def _auto_populate_from_restock(self, shipment: Shipment) -> None:
        """
        Pull all RestockItem rows where marketplace == shipment.country and
        newsvendor_qty > 0, create matching ShipmentItems with initial
        machine assignment based on current stock.
        """
        from restock.models import RestockItem

        marketplace = shipment.country
        # NB: some Restock marketplaces are 'GB' where shipment country is 'UK'
        if marketplace == 'UK':
            marketplace = 'GB'

        # Get the most recent restock report items for this marketplace
        latest_report_id = (
            RestockItem.objects
            .filter(marketplace=marketplace)
            .order_by('-report__created_at')
            .values_list('report_id', flat=True)
            .first()
        )
        if not latest_report_id:
            return

        items = (
            RestockItem.objects
            .filter(report_id=latest_report_id, newsvendor_qty__gt=0)
            .exclude(m_number='')
            .select_related()
        )
        with transaction.atomic():
            for ri in items:
                product = Product.objects.filter(m_number=ri.m_number).first()
                if not product:
                    continue
                # Ivan review 16: default Req qty from Actual 90d metric
                # (units_sold_90d - units_total). Fall back to newsvendor_qty
                # if 90d data is missing.
                sold_90d = ri.units_sold_90d or 0
                total = ri.units_total or 0
                qty = max(0, sold_90d - total)
                if qty <= 0 and sold_90d == 0:
                    qty = ri.newsvendor_qty or 0
                if qty <= 0:
                    continue
                stock_obj = getattr(product, 'stock', None)
                ShipmentItem.objects.create(
                    shipment=shipment,
                    product=product,
                    sku=ri.merchant_sku or '',
                    quantity=qty,
                    stock_at_ship=stock_obj.current_stock if stock_obj else 0,
                    amz_restock_quantity=ri.amazon_recommended_qty or 0,
                    machine_assignment=_default_machine_for(product, qty),
                )
            shipment.recalculate_totals()

    @action(detail=True, methods=['post'], url_path='add-items')
    def add_items(self, request, pk=None):
        shipment = self.get_object()
        items_data = request.data.get('items', [])
        if not items_data:
            return Response({'error': 'No items provided'}, status=status.HTTP_400_BAD_REQUEST)

        created = []
        errors = []
        for item in items_data:
            ser = ShipmentItemCreateSerializer(data=item)
            if not ser.is_valid():
                errors.append({'item': item, 'errors': ser.errors})
                continue

            product = _resolve_product(ser.validated_data['product'])
            if not product:
                errors.append({'item': item, 'error': f'Product {ser.validated_data["product"]} not found'})
                continue

            stock = getattr(product, 'stock', None)
            qty = ser.validated_data['quantity']
            machine = ser.validated_data.get('machine_assignment') or _default_machine_for(product, qty)
            # Ivan review 18: auto-pull the marketplace SKU for this product
            # when none was supplied. Match the shipment's country to the SKU
            # row's channel (UK/US/CA/AU/DE/FR). Falls back to any active SKU,
            # then to the M-number itself.
            requested_sku = ser.validated_data.get('sku', '') or ''
            sku = requested_sku.strip()
            if not sku:
                sku = _lookup_sku(product, shipment.country) or product.m_number
            si = ShipmentItem.objects.create(
                shipment=shipment,
                product=product,
                sku=sku,
                quantity=qty,
                box_number=ser.validated_data.get('box_number'),
                stock_at_ship=stock.current_stock if stock else 0,
                machine_assignment=machine,
            )
            if si.machine_assignment == 'UV':
                _notify_ivan_uv(si)
            created.append(si)

        shipment.recalculate_totals()
        return Response({
            'created': len(created),
            'errors': errors,
            'shipment': ShipmentSerializer(shipment).data,
        })

    @action(detail=True, methods=['post'], url_path='mark-shipped')
    def mark_shipped(self, request, pk=None):
        shipment = self.get_object()
        shipment.status = 'shipped'
        shipment.shipment_date = shipment.shipment_date or timezone.now().date()
        shipment.save(update_fields=['status', 'shipment_date', 'updated_at'])

        # Backfill quantity_shipped from quantity if not yet set
        for item in shipment.items.all():
            if not item.quantity_shipped:
                item.quantity_shipped = item.quantity
                item.save(update_fields=['quantity_shipped', 'updated_at'])

        return Response(ShipmentSerializer(shipment).data)

    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        from django.db.models import Sum, Count
        shipped = Shipment.objects.filter(status='shipped')
        planning = Shipment.objects.exclude(status='shipped')

        shipped_agg = shipped.aggregate(
            total_shipments=Count('id'),
            total_units=Sum('total_units'),
        )
        planning_agg = planning.aggregate(
            total_shipments=Count('id'),
            total_units=Sum('total_units'),
        )
        by_country = (
            shipped.values('country')
            .annotate(shipments=Count('id'), units=Sum('total_units'))
            .order_by('-units')
        )

        return Response({
            'shipped': shipped_agg,
            'in_progress': planning_agg,
            'by_country': list(by_country),
        })


class ShipmentItemViewSet(viewsets.ModelViewSet):
    """
    Individual item CRUD for shipments (Ivan review #12 items 3, 4, 6, 7, 10, 11).
    - PATCH /api/shipment-items/{id}/  — update machine_assignment, stock_taken,
                                          quantity_shipped, quantity, box_number
    - DELETE /api/shipment-items/{id}/ — remove single item
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ShipmentItemSerializer
    queryset = ShipmentItem.objects.select_related('product', 'product__stock', 'shipment').all()

    ALLOWED_UPDATE_FIELDS = {
        'machine_assignment', 'stock_taken', 'quantity_shipped',
        'quantity', 'box_number', 'item_notes',
    }

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        item = self.get_object()
        changed = []
        prev_machine = item.machine_assignment
        prev_stock_taken = item.stock_taken

        for field in self.ALLOWED_UPDATE_FIELDS:
            if field in request.data:
                val = request.data[field]
                if field in ('quantity', 'quantity_shipped', 'stock_taken'):
                    try:
                        val = int(val) if val not in (None, '') else 0
                    except (ValueError, TypeError):
                        return Response({'error': f'{field} must be integer'}, status=400)
                    if val < 0:
                        return Response({'error': f'{field} cannot be negative'}, status=400)
                elif field == 'box_number':
                    if val in (None, ''):
                        val = None
                    else:
                        try:
                            val = int(val)
                        except (ValueError, TypeError):
                            return Response({'error': 'box_number must be integer'}, status=400)
                elif field == 'item_notes':
                    val = str(val or '')
                elif field == 'machine_assignment':
                    val = (val or '').upper().strip()
                    if val not in ('', 'STOCK', 'UV', 'SUB'):
                        return Response({'error': 'machine_assignment must be STOCK/UV/SUB/empty'}, status=400)
                setattr(item, field, val)
                changed.append(field)

        if not changed:
            return Response(self.get_serializer(item).data)

        # If stock_taken increased, decrement product stock by the delta
        if 'stock_taken' in changed:
            delta = item.stock_taken - prev_stock_taken
            if delta != 0:
                stock, _ = StockLevel.objects.get_or_create(product=item.product)
                stock.current_stock = max(0, stock.current_stock - delta)
                stock.save(update_fields=['current_stock', 'updated_at'])
                stock.recalculate_deficit()

        item.save(update_fields=changed + ['updated_at'])
        item.shipment.recalculate_totals()

        # Ivan review #12 item 8: notify Ivan when machine flipped to UV
        if 'machine_assignment' in changed and item.machine_assignment == 'UV' and prev_machine != 'UV':
            _notify_ivan_uv(item)

        return Response(self.get_serializer(item).data)

    @action(detail=False, methods=['get'], url_path='production')
    def production_items(self, request):
        """
        Items that need making for FBA shipments.
        Returns non-STOCK items from active (non-shipped) shipments.
        """
        items = (
            ShipmentItem.objects
            .select_related('shipment', 'product', 'product__stock', 'product__design')
            .filter(shipment__status__in=['planning', 'packing', 'labelled'])
            .exclude(machine_assignment='STOCK')
            .exclude(machine_assignment='')
        )

        result = []
        for item in items:
            stock = 0
            if item.product and hasattr(item.product, 'stock'):
                try:
                    stock = item.product.stock.current_stock
                except Exception:
                    stock = 0
            result.append({
                'id': item.id,
                'country': item.shipment.country,
                'shipment_id': item.shipment.id,
                'm_number': item.product.m_number if item.product else '',
                'description': item.product.description if item.product else '',
                'blank': item.product.blank if item.product else '',
                'blank_family': item.product.blank_family if item.product else '',
                'sku': item.sku,
                'quantity': item.quantity,
                'machine_assignment': item.machine_assignment,
                'current_stock': stock,
                'has_design': item.product.has_design if item.product else False,
                'design_machines': item.product.design.machines_ready() if item.product and hasattr(item.product, 'design') else [],
                'production_stage': _active_stage(item.product),
                'production_order_id': _active_order_id(item.product),
            })

        return Response(result)

    def destroy(self, request, *args, **kwargs):
        item = self.get_object()
        shipment = item.shipment
        item.delete()
        shipment.recalculate_totals()
        return Response(status=status.HTTP_204_NO_CONTENT)
