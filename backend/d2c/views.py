from django.db import transaction
from django.db.models import Count, Q
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
        qs = (
            DispatchOrder.objects
            .select_related('product', 'product__stock', 'assigned_to', 'completed_by')
            .all()
        )
        # `?status__in=pending,in_progress,made` — multi-status filter so the
        # dispatch UI can load every non-dispatched order in one call.
        status_in = self.request.query_params.get('status__in') if hasattr(self, 'request') and self.request else None
        if status_in:
            statuses = [s.strip() for s in status_in.split(',') if s.strip()]
            if statuses:
                qs = qs.filter(status__in=statuses)
        return qs

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
        """
        Mark an order dispatched. For non-personalised generics whose stock has
        not already been decremented (e.g. the 'made → dispatched' flow that
        bypasses fulfil-from-stock), deduct the stock atomically here so we
        never dispatch without updating the ledger.
        """
        from stock.models import StockLevel

        order = self.get_object()
        user = request.user if request.user.is_authenticated else None
        now = timezone.now()

        should_deduct = (
            order.product
            and not order.product.is_personalised
            and not order.stock_updated
        )

        if should_deduct:
            with transaction.atomic():
                # Auto-create a StockLevel at 0 if the product has none — the
                # order was already made (or bypassed stock), so we record the
                # dispatch and keep the ledger consistent at zero rather than
                # blocking the user.
                stock = (
                    StockLevel.objects
                    .select_for_update()
                    .filter(product=order.product)
                    .first()
                )
                if stock is None:
                    stock, _ = StockLevel.objects.get_or_create(product=order.product)
                    stock = StockLevel.objects.select_for_update().get(pk=stock.pk)

                # If the order was already made, we know stock was set aside
                # for it elsewhere — clamp the deduction to what's available
                # rather than rejecting the dispatch.
                deduct = min(order.quantity, stock.current_stock)
                if deduct > 0:
                    stock.current_stock -= deduct
                    stock.save(update_fields=['current_stock', 'updated_at'])
                    stock.recalculate_deficit()

                order.status = 'dispatched'
                order.stock_updated = True
                # Preserve original completed_at if already set when marked-made
                if not order.completed_at:
                    order.completed_at = now
                    order.completed_by = user
                order.save(update_fields=[
                    'status', 'stock_updated', 'completed_at', 'completed_by', 'updated_at',
                ])
        else:
            order.status = 'dispatched'
            if not order.completed_at:
                order.completed_at = now
                order.completed_by = user
                order.save(update_fields=['status', 'completed_at', 'completed_by', 'updated_at'])
            else:
                order.save(update_fields=['status', 'updated_at'])

        order.refresh_from_db()
        return Response(DispatchOrderSerializer(order).data)

    @action(detail=True, methods=['post'], url_path='fulfil-from-stock')
    def fulfil_from_stock(self, request, pk=None):
        """
        Fulfil a single order from existing stock.
        Atomically deducts stock, marks order dispatched, recalculates deficit.
        """
        order = self.get_object()
        user = request.user if request.user.is_authenticated else None

        # Validate order state — allow pending/in_progress and 'made' (made
        # orders still need stock deduction + dispatch on the same action).
        if order.status not in ('pending', 'in_progress', 'made'):
            return Response(
                {'error': f'Cannot fulfil order with status "{order.status}"'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not order.product:
            return Response(
                {'error': 'Order has no linked product'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if order.product.is_personalised:
            return Response(
                {'error': 'Cannot fulfil personalised orders from stock'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = self._deduct_stock_and_dispatch(order, user)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(DispatchOrderSerializer(result).data)

    @action(detail=False, methods=['post'], url_path='bulk-fulfil')
    def bulk_fulfil(self, request):
        """
        Fulfil multiple orders from stock in a single transaction.
        Body: {"ids": [1, 2, 3]}
        Returns: {"fulfilled": [...], "failed": [...]}
        """
        ids = request.data.get('ids', [])
        if not ids:
            return Response(
                {'error': 'No order IDs provided'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user if request.user.is_authenticated else None
        fulfilled = []
        failed = []

        with transaction.atomic():
            orders = (
                DispatchOrder.objects
                .select_related('product', 'product__stock')
                .filter(id__in=ids)
            )
            for order in orders:
                if order.status not in ('pending', 'in_progress', 'made'):
                    failed.append({'id': order.id, 'order_id': order.order_id, 'reason': f'Status is "{order.status}"'})
                    continue
                if not order.product:
                    failed.append({'id': order.id, 'order_id': order.order_id, 'reason': 'No linked product'})
                    continue
                if order.product.is_personalised:
                    failed.append({'id': order.id, 'order_id': order.order_id, 'reason': 'Personalised product'})
                    continue
                try:
                    result = self._deduct_stock_and_dispatch(order, user)
                    fulfilled.append(DispatchOrderSerializer(result).data)
                except ValueError as e:
                    failed.append({'id': order.id, 'order_id': order.order_id, 'reason': str(e)})

        return Response({'fulfilled': fulfilled, 'failed': failed})

    def _deduct_stock_and_dispatch(self, order, user):
        """
        Atomically deduct stock and mark order dispatched.
        Uses select_for_update to prevent concurrent over-deduction.
        Raises ValueError if insufficient stock.
        Skips deduction (but still dispatches) if order.stock_updated is already True,
        which guards against double-decrementing when a made order is bulk-fulfilled.
        """
        from stock.models import StockLevel

        with transaction.atomic():
            if not order.stock_updated:
                try:
                    stock = StockLevel.objects.select_for_update().get(product=order.product)
                except StockLevel.DoesNotExist:
                    raise ValueError(f'No stock record for {order.product.m_number}')

                if stock.current_stock < order.quantity:
                    raise ValueError(
                        f'Insufficient stock for {order.product.m_number}: '
                        f'have {stock.current_stock}, need {order.quantity}'
                    )

                stock.current_stock -= order.quantity
                stock.save(update_fields=['current_stock', 'updated_at'])
                stock.recalculate_deficit()

            order.status = 'dispatched'
            order.stock_updated = True
            # Preserve the original completed_at (set when marked-made) if present.
            if not order.completed_at:
                order.completed_at = timezone.now()
                order.completed_by = user
            order.save(update_fields=[
                'status', 'stock_updated', 'completed_at', 'completed_by', 'updated_at',
            ])

        # Refresh to pick up updated stock for serializer
        order.refresh_from_db()
        return order

    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        by_status = dict(
            DispatchOrder.objects.values_list('status')
            .annotate(count=Count('id'))
            .values_list('status', 'count')
        )

        # Count fulfillable orders: pending + has product + not personalised + stock >= qty
        fulfillable = (
            DispatchOrder.objects
            .filter(
                status__in=['pending', 'in_progress'],
                product__isnull=False,
                product__is_personalised=False,
            )
            .select_related('product__stock')
            .all()
        )
        fulfillable_count = sum(
            1 for o in fulfillable
            if hasattr(o.product, 'stock') and o.product.stock.current_stock >= o.quantity
        )

        return Response({
            'pending': by_status.get('pending', 0),
            'in_progress': by_status.get('in_progress', 0),
            'made': by_status.get('made', 0),
            'dispatched': by_status.get('dispatched', 0),
            'total': sum(by_status.values()),
            'fulfillable': fulfillable_count,
        })
