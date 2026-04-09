from django.db.models import OuterRef, Subquery
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from .models import Product, SKU, ProductDesign
from .serializers import ProductSerializer, SKUSerializer


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['blank', 'active', 'do_not_restock', 'is_personalised']
    search_fields = ['m_number', 'description']
    ordering_fields = ['m_number', 'blank', 'created_at']
    ordering = ['m_number']

    def get_queryset(self):
        from production.models import ProductionOrder
        active_stage_subquery = Subquery(
            ProductionOrder.objects.filter(
                product=OuterRef('pk'),
                completed_at__isnull=True,
            ).values('simple_stage')[:1]
        )
        return (
            Product.objects
            .select_related('stock')
            .prefetch_related('skus')
            .annotate(_active_stage=active_stage_subquery)
            .all()
        )

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
        stock.save(update_fields=['current_stock', 'updated_at'])
        stock.recalculate_deficit()
        return Response({
            'current_stock': stock.current_stock,
            'stock_deficit': stock.stock_deficit,
        })

    @action(detail=False, methods=['get'], url_path='designs')
    def designs_bulk(self, request):
        designs = {d.product_id: d for d in ProductDesign.objects.all()}
        result = []
        for p in Product.objects.filter(active=True).values('id', 'm_number', 'description', 'blank'):
            d = designs.get(p['id'])
            result.append({
                'id': p['id'],
                'm_number': p['m_number'],
                'description': p['description'],
                'blank': p['blank'],
                'rolf': d.rolf if d else False,
                'mimaki': d.mimaki if d else False,
                'epson': d.epson if d else False,
                'mutoh': d.mutoh if d else False,
                'nonename': d.nonename if d else False,
            })
        return Response(result)

    @action(detail=True, methods=['get', 'patch'], url_path='design')
    def design(self, request, pk=None):
        product = self.get_object()
        design, _ = ProductDesign.objects.get_or_create(product=product)
        if request.method == 'PATCH':
            for machine in ['rolf', 'mimaki', 'epson', 'mutoh', 'nonename']:
                if machine in request.data:
                    setattr(design, machine, bool(request.data[machine]))
            design.save()
        return Response({
            'rolf': design.rolf,
            'mimaki': design.mimaki,
            'epson': design.epson,
            'mutoh': design.mutoh,
            'nonename': design.nonename,
        })

    @action(detail=False, methods=['get'], url_path='assemblies')
    def assemblies_bulk(self, request):
        products = Product.objects.filter(active=True).order_by('m_number').values(
            'id', 'm_number', 'description', 'blank', 'material', 'machine_type', 'blank_family'
        )
        return Response(list(products))

    @action(detail=True, methods=['get', 'patch'], url_path='assembly')
    def assembly(self, request, pk=None):
        product = self.get_object()
        if request.method == 'PATCH':
            changed = []
            for field in ['blank', 'material', 'machine_type', 'blank_family']:
                if field in request.data:
                    val = request.data[field]
                    if isinstance(val, str):
                        val = val.strip()
                    setattr(product, field, val)
                    changed.append(field)
            if changed:
                product.save(update_fields=changed + ['updated_at'])
        return Response({
            'id': product.id,
            'm_number': product.m_number,
            'blank': product.blank,
            'material': product.material,
            'machine_type': product.machine_type,
            'blank_family': product.blank_family,
        })


class SKUViewSet(viewsets.ModelViewSet):
    serializer_class = SKUSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['channel', 'active']
    search_fields = ['sku', 'asin', 'product__m_number']

    def get_queryset(self):
        return SKU.objects.select_related('product').all()
