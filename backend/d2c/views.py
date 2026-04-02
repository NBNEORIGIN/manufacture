from django.utils import timezone
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from products.models import Product
from .models import DispatchOrder
from .serializers import DispatchOrderSerializer


class DispatchOrderViewSet(viewsets.ModelViewSet):
    serializer_class = DispatchOrderSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'channel']
    search_fields = ['order_id', 'sku', 'description', 'flags', 'customer_name', 'product__m_number', 'line1']
    ordering_fields = ['order_date', 'created_at', 'status']
    ordering = ['-order_date', '-created_at']

    def get_queryset(self):
        return DispatchOrder.objects.select_related('product', 'assigned_to', 'completed_by').all()

    def perform_create(self, serializer):
        m_number = self.request.data.get('m_number', '')
        product = None
        if m_number:
            product = Product.objects.filter(m_number=m_number).first()
        serializer.save(product=product)

    @action(detail=True, methods=['post'], url_path='mark-made')
    def mark_made(self, request, pk=None):
        order = self.get_object()
        user = request.user if request.user.is_authenticated else None
        order.status = 'made'
        order.completed_at = timezone.now()
        order.completed_by = user
        order.save(update_fields=['status', 'completed_at', 'completed_by', 'updated_at'])
        return Response(DispatchOrderSerializer(order).data)

    @action(detail=True, methods=['post'], url_path='mark-dispatched')
    def mark_dispatched(self, request, pk=None):
        order = self.get_object()
        order.status = 'dispatched'
        order.save(update_fields=['status', 'updated_at'])
        return Response(DispatchOrderSerializer(order).data)

    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        from django.db.models import Count
        by_status = dict(
            DispatchOrder.objects.values_list('status')
            .annotate(count=Count('id'))
            .values_list('status', 'count')
        )
        return Response({
            'pending': by_status.get('pending', 0),
            'in_progress': by_status.get('in_progress', 0),
            'made': by_status.get('made', 0),
            'dispatched': by_status.get('dispatched', 0),
            'total': sum(by_status.values()),
        })
