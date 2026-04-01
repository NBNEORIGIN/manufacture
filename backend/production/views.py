from django.utils import timezone
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend

from products.models import Product
from stock.models import StockLevel
from .models import ProductionOrder, ProductionStage
from .serializers import ProductionOrderSerializer, ProductionStageSerializer
from .services.make_list import get_make_list


class MakeListView(APIView):
    def get(self, request):
        group_by_blank = request.query_params.get('group_by_blank', '').lower() == 'true'
        items = get_make_list(group_by_blank=group_by_blank)
        return Response(items)


class ProductionOrderViewSet(viewsets.ModelViewSet):
    serializer_class = ProductionOrderSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['machine', 'product__blank']
    search_fields = ['product__m_number', 'product__description']
    ordering_fields = ['priority', 'created_at']
    ordering = ['-priority', '-created_at']

    def get_queryset(self):
        qs = ProductionOrder.objects.select_related('product', 'created_by').prefetch_related(
            'stages', 'stages__completed_by'
        )
        active_only = self.request.query_params.get('active', '').lower()
        if active_only == 'true':
            qs = qs.filter(completed_at__isnull=True)
        return qs

    def perform_create(self, serializer):
        order = serializer.save(created_by=self.request.user)
        default_stages = ['designed', 'printed', 'processed', 'cut', 'labelled', 'packed', 'shipped']
        ProductionStage.objects.bulk_create([
            ProductionStage(order=order, stage=s) for s in default_stages
        ])

    @action(detail=True, methods=['patch'], url_path='stages/(?P<stage>[a-z_]+)')
    def advance_stage(self, request, pk=None, stage=None):
        order = self.get_object()
        try:
            ps = order.stages.get(stage=stage)
        except ProductionStage.DoesNotExist:
            return Response({'error': f'Stage "{stage}" not found'}, status=status.HTTP_404_NOT_FOUND)

        ps.completed = True
        ps.completed_at = timezone.now()
        ps.completed_by = request.user
        ps.save()

        if stage == 'packed':
            return Response({
                'stage': ProductionStageSerializer(ps).data,
                'prompt_stock_update': True,
                'message': f'Confirm stock update: add {order.quantity} to {order.product.m_number}?',
            })

        return Response(ProductionStageSerializer(ps).data)

    @action(detail=True, methods=['post'], url_path='confirm-stock')
    def confirm_stock_update(self, request, pk=None):
        order = self.get_object()
        stock, _ = StockLevel.objects.get_or_create(product=order.product)
        stock.current_stock += order.quantity
        stock.recalculate_deficit()
        order.completed_at = timezone.now()
        order.save(update_fields=['completed_at', 'updated_at'])
        return Response({
            'message': f'Stock updated: {order.product.m_number} now has {stock.current_stock} units',
            'new_stock': stock.current_stock,
            'new_deficit': stock.stock_deficit,
        })
