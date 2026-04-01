from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import StockLevel
from .serializers import StockLevelSerializer


class StockLevelViewSet(viewsets.ModelViewSet):
    serializer_class = StockLevelSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['product__blank', 'product__active']
    search_fields = ['product__m_number', 'product__description']
    ordering_fields = ['stock_deficit', 'sixty_day_sales', 'current_stock']
    ordering = ['-stock_deficit']

    def get_queryset(self):
        return StockLevel.objects.select_related('product').all()
