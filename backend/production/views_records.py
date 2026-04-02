from django.db import models as db_models
from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from products.models import Product
from .models_records import ProductionRecord
from .serializers_records import ProductionRecordSerializer


class ProductionRecordViewSet(viewsets.ModelViewSet):
    serializer_class = ProductionRecordSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['machine']
    search_fields = ['sku', 'product__m_number', 'failure_reason', 'machine']
    ordering_fields = ['date', 'errors', 'number_printed']
    ordering = ['-date']

    def get_queryset(self):
        qs = ProductionRecord.objects.select_related('product').all()
        errors_only = self.request.query_params.get('errors_only', '').lower()
        if errors_only == 'true':
            qs = qs.filter(errors__gt=0)
        return qs

    def perform_create(self, serializer):
        m_number = self.request.data.get('m_number', '')
        product = None
        if m_number:
            product = Product.objects.filter(m_number=m_number).first()
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(product=product, recorded_by=user)

    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        total = ProductionRecord.objects.count()
        total_printed = ProductionRecord.objects.aggregate(s=db_models.Sum('number_printed'))['s'] or 0
        total_errors = ProductionRecord.objects.aggregate(s=db_models.Sum('errors'))['s'] or 0
        error_rate = round(total_errors / total_printed * 100, 2) if total_printed else 0

        by_machine = list(
            ProductionRecord.objects.values('machine')
            .annotate(
                records=db_models.Count('id'),
                printed=db_models.Sum('number_printed'),
                errors=db_models.Sum('errors'),
            )
            .order_by('-printed')
        )

        top_reasons = list(
            ProductionRecord.objects.filter(errors__gt=0)
            .exclude(failure_reason='')
            .values('failure_reason')
            .annotate(count=db_models.Count('id'), total_errors=db_models.Sum('errors'))
            .order_by('-total_errors')[:10]
        )

        return Response({
            'total_records': total,
            'total_printed': total_printed,
            'total_errors': total_errors,
            'error_rate_pct': error_rate,
            'by_machine': by_machine,
            'top_failure_reasons': top_reasons,
        })
