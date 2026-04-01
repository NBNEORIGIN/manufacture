from django.utils import timezone
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
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


class ShipmentViewSet(viewsets.ModelViewSet):
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
        return Shipment.objects.prefetch_related('items', 'items__product').all()

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(created_by=user)

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

            try:
                product = Product.objects.get(m_number=ser.validated_data['product'])
            except Product.DoesNotExist:
                errors.append({'item': item, 'error': f'Product {ser.validated_data["product"]} not found'})
                continue

            stock = getattr(product, 'stock', None)
            si = ShipmentItem.objects.create(
                shipment=shipment,
                product=product,
                sku=ser.validated_data.get('sku', ''),
                quantity=ser.validated_data['quantity'],
                box_number=ser.validated_data.get('box_number'),
                stock_at_ship=stock.current_stock if stock else 0,
            )
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

        # Update shipped quantities
        for item in shipment.items.all():
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
