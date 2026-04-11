from decimal import Decimal, InvalidOperation
from django.db.models import Count, OuterRef, Subquery
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from .models import Product, SKU, ProductDesign, BlankType
from .serializers import ProductSerializer, SKUSerializer, BlankTypeSerializer


class LargeResultsPagination(PageNumberPagination):
    """Allows callers to request a larger page size via ?page_size=. Capped at 10000."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 10000


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    pagination_class = LargeResultsPagination
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
                'mao': d.mao if d else False,
            })
        return Response(result)

    @action(detail=True, methods=['get', 'patch'], url_path='design')
    def design(self, request, pk=None):
        product = self.get_object()
        design, _ = ProductDesign.objects.get_or_create(product=product)
        if request.method == 'PATCH':
            for machine in ['rolf', 'mimaki', 'epson', 'mutoh', 'mao']:
                if machine in request.data:
                    setattr(design, machine, bool(request.data[machine]))
            design.save()
        return Response({
            'rolf': design.rolf,
            'mimaki': design.mimaki,
            'epson': design.epson,
            'mutoh': design.mutoh,
            'mao': design.mao,
        })

    @action(detail=False, methods=['get'], url_path='assemblies')
    def assemblies_bulk(self, request):
        products = Product.objects.filter(active=True).order_by('m_number').values(
            'id', 'm_number', 'description', 'blank', 'material', 'machine_type', 'blank_family'
        )
        return Response(list(products))

    @action(detail=True, methods=['patch'], url_path='shipping-dims')
    def shipping_dims(self, request, pk=None):
        """
        Set or clear a per-product shipping dimension override.

        Body: { length_cm, width_cm, height_cm, weight_g }  — all optional
        Any field provided is saved. Setting any field marks
        shipping_dims_overridden=True so subsequent BlankType.apply_to_products()
        calls will not clobber it.

        Pass { "clear": true } to wipe the override and let the blank_type
        re-populate on next apply.
        """
        product = self.get_object()

        if request.data.get('clear'):
            product.shipping_length_cm = None
            product.shipping_width_cm = None
            product.shipping_height_cm = None
            product.shipping_weight_g = None
            product.shipping_dims_overridden = False
            product.save(update_fields=[
                'shipping_length_cm', 'shipping_width_cm', 'shipping_height_cm',
                'shipping_weight_g', 'shipping_dims_overridden', 'updated_at',
            ])
            return Response(ProductSerializer(product).data)

        changed = []
        for field_name, caster in [
            ('shipping_length_cm', Decimal),
            ('shipping_width_cm', Decimal),
            ('shipping_height_cm', Decimal),
            ('shipping_weight_g', int),
        ]:
            key = field_name.removeprefix('shipping_')
            if key in request.data:
                raw = request.data[key]
                if raw in (None, ''):
                    setattr(product, field_name, None)
                    changed.append(field_name)
                    continue
                try:
                    setattr(product, field_name, caster(raw))
                except (ValueError, InvalidOperation, TypeError):
                    return Response(
                        {'error': f'{key} must be numeric'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                changed.append(field_name)

        if changed:
            product.shipping_dims_overridden = True
            changed.append('shipping_dims_overridden')
            product.save(update_fields=changed + ['updated_at'])

        return Response(ProductSerializer(product).data)

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


class BlankTypeViewSet(viewsets.ModelViewSet):
    """
    CRUD for BlankType rows plus link/unlink actions and apply-to-products.

    Product.shipping_* are the authoritative values read by FBA preflight
    and setPackingInformation; this viewset is an efficient way to edit
    50-ish canonical blanks instead of 1869 products.
    """
    serializer_class = BlankTypeSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name']
    ordering_fields = ['name', 'weight_g']
    ordering = ['name']
    pagination_class = None  # Small table, don't bother paginating

    def get_queryset(self):
        return BlankType.objects.annotate(_product_count=Count('products'))

    @action(detail=True, methods=['post'], url_path='apply-to-products')
    def apply_to_products(self, request, pk=None):
        """
        Copy this blank type's dimensions onto every linked product's
        shipping_* fields. Skips products with shipping_dims_overridden=True
        unless the request body contains { "force": true }.
        """
        blank_type = self.get_object()
        force = bool(request.data.get('force'))
        updated = blank_type.apply_to_products(force=force)
        return Response({
            'blank_type_id': blank_type.id,
            'blank_type_name': blank_type.name,
            'products_updated': updated,
            'force': force,
        })

    @action(detail=True, methods=['get'], url_path='products')
    def list_products(self, request, pk=None):
        """List the products currently linked to this blank type (id, m_number, description, override flag)."""
        blank_type = self.get_object()
        data = list(
            blank_type.products
            .order_by('m_number')
            .values('id', 'm_number', 'description', 'blank', 'shipping_dims_overridden')
        )
        return Response(data)

    @action(detail=True, methods=['post'], url_path='link')
    def link_products(self, request, pk=None):
        """
        Link a set of products to this blank type.

        Body: { "product_ids": [1,2,3] }
        or:   { "match_blank": "SAVILLE" }  — link every product whose .blank
               matches case-insensitively (handy for one-click first-pass assignment)
        """
        blank_type = self.get_object()

        if 'product_ids' in request.data:
            ids = request.data.get('product_ids') or []
            if not isinstance(ids, list):
                return Response({'error': 'product_ids must be a list'}, status=400)
            count = Product.objects.filter(id__in=ids).update(blank_type=blank_type)
            return Response({'linked': count})

        if 'match_blank' in request.data:
            pattern = str(request.data['match_blank']).strip()
            if not pattern:
                return Response({'error': 'match_blank cannot be empty'}, status=400)
            count = (
                Product.objects
                .filter(blank__iexact=pattern)
                .update(blank_type=blank_type)
            )
            return Response({'linked': count, 'matched': pattern})

        return Response(
            {'error': 'Provide product_ids (list) or match_blank (string)'},
            status=400,
        )

    @action(detail=True, methods=['post'], url_path='unlink')
    def unlink_products(self, request, pk=None):
        """Unlink a set of products from this blank type. Body: { "product_ids": [1,2,3] }"""
        blank_type = self.get_object()
        ids = request.data.get('product_ids') or []
        if not isinstance(ids, list):
            return Response({'error': 'product_ids must be a list'}, status=400)
        count = (
            Product.objects
            .filter(id__in=ids, blank_type=blank_type)
            .update(blank_type=None)
        )
        return Response({'unlinked': count})

    @action(detail=False, methods=['get'], url_path='unassigned-products')
    def unassigned_products(self, request):
        """
        List active products that have no blank_type assigned, grouped by the
        raw .blank string so the UI can offer one-click bulk link per group.
        """
        rows = (
            Product.objects
            .filter(active=True, blank_type__isnull=True)
            .values('blank')
            .annotate(count=Count('id'))
            .order_by('-count', 'blank')
        )
        return Response(list(rows))
