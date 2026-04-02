from django.db import models
from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import Material
from .serializers import MaterialSerializer


class MaterialViewSet(viewsets.ModelViewSet):
    serializer_class = MaterialSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category']
    search_fields = ['name', 'material_id', 'in_house_description', 'preferred_supplier']
    ordering_fields = ['name', 'current_stock', 'current_price']
    ordering = ['name']

    def get_queryset(self):
        qs = Material.objects.all()
        needs_reorder = self.request.query_params.get('needs_reorder', '').lower()
        if needs_reorder == 'true':
            qs = qs.filter(current_stock__lte=models.F('reorder_point'))
        return qs

    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        from django.db.models import Sum, Count, F
        total = Material.objects.count()
        needing_reorder = Material.objects.filter(current_stock__lte=F('reorder_point')).count()
        total_value = Material.objects.aggregate(
            value=Sum(models.F('current_stock') * models.F('current_price'))
        )['value'] or 0
        categories = list(
            Material.objects.values('category')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        return Response({
            'total_materials': total,
            'needs_reorder': needing_reorder,
            'total_stock_value': float(total_value),
            'categories': categories,
        })
