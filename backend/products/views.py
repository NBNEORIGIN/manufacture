from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import Product, SKU
from .serializers import ProductSerializer, SKUSerializer


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['blank', 'active', 'do_not_restock', 'is_personalised']
    search_fields = ['m_number', 'description']
    ordering_fields = ['m_number', 'blank', 'created_at']
    ordering = ['m_number']

    def get_queryset(self):
        return Product.objects.select_related('stock').prefetch_related('skus').all()

    @action(detail=True, methods=['patch'], url_path='stock')
    def update_stock(self, request, pk=None):
        from stock.models import StockLevel
        product = self.get_object()
        new_stock = request.data.get('current_stock')
        if new_stock is None:
            return Response({'error': 'current_stock required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            new_stock = int(new_stock)
        except (ValueError, TypeError):
            return Response({'error': 'current_stock must be an integer'}, status=status.HTTP_400_BAD_REQUEST)
        stock, _ = StockLevel.objects.get_or_create(product=product)
        stock.current_stock = new_stock
        stock.recalculate_deficit()
        return Response({
            'current_stock': stock.current_stock,
            'stock_deficit': stock.stock_deficit,
        })


class SKUViewSet(viewsets.ModelViewSet):
    serializer_class = SKUSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['channel', 'active']
    search_fields = ['sku', 'asin', 'product__m_number']

    def get_queryset(self):
        return SKU.objects.select_related('product').all()
