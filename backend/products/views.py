from rest_framework import viewsets, filters
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


class SKUViewSet(viewsets.ModelViewSet):
    serializer_class = SKUSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['channel', 'active']
    search_fields = ['sku', 'asin', 'product__m_number']

    def get_queryset(self):
        return SKU.objects.select_related('product').all()
