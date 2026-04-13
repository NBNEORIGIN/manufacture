"""
DRF views + function endpoints backing the Sales Velocity tab UI.

All endpoints require authentication (session cookie) per the
manufacture-app convention. The existing DRF default permissions
are IsAuthenticated.

Endpoints:
- GET    /api/sales-velocity/status/           — top-panel status pills
- GET    /api/sales-velocity/history/          — main velocity table
- GET    /api/sales-velocity/unmatched/        — unmatched SKU panel
- POST   /api/sales-velocity/unmatched/{id}/ignore/
- POST   /api/sales-velocity/unmatched/{id}/map/ {product_id}
- GET    /api/sales-velocity/manual-sales/     — footfall list
- POST   /api/sales-velocity/manual-sales/     — footfall create
- DELETE /api/sales-velocity/manual-sales/{id}/
- GET    /api/sales-velocity/drift-alerts/
- POST   /api/sales-velocity/drift-alerts/{id}/acknowledge/
- GET    /api/sales-velocity/shadow-diff/      — shadow/live comparison
- POST   /api/sales-velocity/refresh/          — trigger async refresh
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.conf import settings
from django.db.models import Count, F, Max, Q, Subquery, Sum, Value, OuterRef
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from sales_velocity.models import (
    CHANNEL_CHOICES,
    DriftAlert,
    ManualSale,
    SalesVelocityAPICall,
    SalesVelocityHistory,
    UnmatchedSKU,
)


# ── Serializers ──────────────────────────────────────────────────────────────

class SalesVelocityHistorySerializer(serializers.ModelSerializer):
    m_number = serializers.CharField(source='product.m_number', read_only=True)
    description = serializers.CharField(source='product.description', read_only=True)

    class Meta:
        model = SalesVelocityHistory
        fields = [
            'id', 'product', 'm_number', 'description', 'channel',
            'snapshot_date', 'units_sold_30d',
        ]


class UnmatchedSKUSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnmatchedSKU
        fields = [
            'id', 'channel', 'external_sku', 'title',
            'units_sold_30d', 'first_seen', 'last_seen',
            'ignored', 'resolved_to',
        ]


class ManualSaleSerializer(serializers.ModelSerializer):
    m_number = serializers.CharField(source='product.m_number', read_only=True)
    entered_by_username = serializers.CharField(
        source='entered_by.username', read_only=True,
    )

    class Meta:
        model = ManualSale
        fields = [
            'id', 'product', 'm_number', 'quantity', 'sale_date',
            'channel', 'notes', 'entered_by', 'entered_by_username',
            'created_at',
        ]
        read_only_fields = ['entered_by', 'created_at']


class DriftAlertSerializer(serializers.ModelSerializer):
    m_number = serializers.CharField(source='product.m_number', read_only=True)

    class Meta:
        model = DriftAlert
        fields = [
            'id', 'product', 'm_number', 'detected_at',
            'current_velocity', 'rolling_avg_velocity', 'variance_pct',
            'acknowledged', 'acknowledged_at',
        ]


# ── ViewSets ─────────────────────────────────────────────────────────────────

class SalesVelocityHistoryViewSet(
    mixins.ListModelMixin, viewsets.GenericViewSet,
):
    """
    Main velocity table. Supports ?snapshot_date=<date> (default today)
    and ?channel=<code> filters. Defaults to latest snapshot per product
    when no filter is given.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = SalesVelocityHistorySerializer

    def get_queryset(self):
        qs = SalesVelocityHistory.objects.select_related('product')
        snap = self.request.query_params.get('snapshot_date')
        channel = self.request.query_params.get('channel')
        if snap:
            qs = qs.filter(snapshot_date=snap)
        else:
            latest = qs.aggregate(m=Max('snapshot_date'))['m']
            if latest:
                qs = qs.filter(snapshot_date=latest)
        if channel:
            qs = qs.filter(channel=channel)
        return qs.order_by('product__m_number', 'channel')


class UnmatchedSKUViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]
    serializer_class = UnmatchedSKUSerializer
    queryset = UnmatchedSKU.objects.filter(ignored=False).order_by('-units_sold_30d')

    @action(detail=True, methods=['post'])
    def ignore(self, request, pk=None):
        obj = self.get_object()
        obj.ignored = True
        obj.save(update_fields=['ignored'])
        return Response({'ok': True, 'ignored': True})

    @action(detail=True, methods=['post'])
    def map(self, request, pk=None):
        """Resolve an unmatched SKU to an existing Product."""
        from products.models import Product, SKU
        obj = self.get_object()
        product_id = request.data.get('product_id')
        if not product_id:
            return Response(
                {'error': 'product_id required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            product = Product.objects.get(pk=product_id)
        except Product.DoesNotExist:
            return Response(
                {'error': f'Product {product_id} not found'},
                status=status.HTTP_404_NOT_FOUND,
            )
        # Create the SKU row so future aggregator runs pick it up.
        sku_channel_value = request.data.get('sku_channel', obj.channel)
        SKU.objects.get_or_create(
            sku=obj.external_sku,
            channel=sku_channel_value,
            defaults={'product': product},
        )
        obj.resolved_to = product
        obj.save(update_fields=['resolved_to'])
        return Response({'ok': True, 'resolved_to': product.m_number})


class ManualSaleViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ManualSaleSerializer
    queryset = ManualSale.objects.select_related('product', 'entered_by')

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(entered_by=user)


class DriftAlertViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]
    serializer_class = DriftAlertSerializer
    queryset = DriftAlert.objects.select_related('product')

    def get_queryset(self):
        qs = super().get_queryset()
        show_ack = self.request.query_params.get('include_acknowledged', 'false')
        if show_ack.lower() not in ('true', '1', 'yes'):
            qs = qs.filter(acknowledged=False)
        return qs

    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        obj = self.get_object()
        obj.acknowledged = True
        obj.acknowledged_by = request.user if request.user.is_authenticated else None
        obj.acknowledged_at = timezone.now()
        obj.save(update_fields=[
            'acknowledged', 'acknowledged_by', 'acknowledged_at',
        ])
        return Response({'ok': True})


# ── Function views ───────────────────────────────────────────────────────────

@api_view(['GET'])
def status_view(request):
    """
    Top-panel status for the Sales Velocity tab:
    - last sync timestamp per channel
    - per-channel error/success pills
    - shadow-mode flag
    - unacknowledged drift alert count
    - eBay OAuth credential presence
    """
    from sales_velocity.models import OAuthCredential

    # Per-channel last sync + last error
    channel_status: dict[str, dict[str, Any]] = {}
    for code, _label in CHANNEL_CHOICES:
        last_ok = SalesVelocityAPICall.objects.filter(
            channel=code, response_status=200,
        ).order_by('-created_at').first()
        last_err = SalesVelocityAPICall.objects.filter(
            channel=code,
        ).exclude(response_status=200).order_by('-created_at').first()
        channel_status[code] = {
            'last_success_at': last_ok.created_at.isoformat() if last_ok else None,
            'last_error_at': last_err.created_at.isoformat() if last_err else None,
            'last_error_message': (
                last_err.error_message[:200] if last_err else ''
            ),
        }

    ebay_cred = OAuthCredential.objects.filter(provider='ebay').first()
    ebay_status = {
        'connected': bool(ebay_cred and ebay_cred.access_token),
        'expires_at': (
            ebay_cred.access_token_expires_at.isoformat()
            if ebay_cred and ebay_cred.access_token_expires_at else None
        ),
    }

    return Response({
        'shadow_mode_enabled': not bool(
            getattr(settings, 'SALES_VELOCITY_WRITE_ENABLED', False)
        ),
        'write_enabled': bool(
            getattr(settings, 'SALES_VELOCITY_WRITE_ENABLED', False)
        ),
        'channel_status': channel_status,
        'unacknowledged_drift_count': DriftAlert.objects.filter(
            acknowledged=False,
        ).count(),
        'unmatched_sku_count': UnmatchedSKU.objects.filter(ignored=False).count(),
        'latest_snapshot_date': SalesVelocityHistory.objects.aggregate(
            m=Max('snapshot_date'),
        )['m'],
        'ebay_oauth': ebay_status,
    })


@api_view(['GET'])
def shadow_diff_view(request):
    """
    Per-M-number comparison of the latest SalesVelocityHistory aggregate
    vs current StockLevel.sixty_day_sales. Used by the Shadow/Live diff
    panel during shadow mode.
    """
    from products.models import Product
    from stock.models import StockLevel

    latest_date = SalesVelocityHistory.objects.aggregate(
        m=Max('snapshot_date'),
    )['m']
    if latest_date is None:
        return Response({'rows': [], 'snapshot_date': None})

    # Sum SalesVelocityHistory by product for the latest snapshot
    by_product = (
        SalesVelocityHistory.objects
        .filter(snapshot_date=latest_date)
        .values('product_id', 'product__m_number')
        .annotate(total_30d=Sum('units_sold_30d'))
        .order_by('product__m_number')
    )

    product_ids = [row['product_id'] for row in by_product]
    stock_by_product = dict(
        StockLevel.objects
        .filter(product_id__in=product_ids)
        .values_list('product_id', 'sixty_day_sales')
    )

    rows = []
    for row in by_product:
        api_60 = (row['total_30d'] or 0) * 2
        current_stock_60 = stock_by_product.get(row['product_id']) or 0
        variance = 0.0
        if current_stock_60:
            variance = round(
                (api_60 - current_stock_60) / current_stock_60 * 100, 2,
            )
        rows.append({
            'product_id': row['product_id'],
            'm_number': row['product__m_number'],
            'current_stock_sixty_day_sales': current_stock_60,
            'api_30d_times_2': api_60,
            'variance_pct': variance,
        })

    return Response({
        'rows': rows,
        'snapshot_date': latest_date.isoformat(),
        'shadow_mode_enabled': not bool(
            getattr(settings, 'SALES_VELOCITY_WRITE_ENABLED', False)
        ),
    })


@api_view(['POST'])
def refresh_view(request):
    """
    Trigger an async refresh via Django-Q. The request returns
    immediately with the task ID; the UI polls /status/ to see
    when the new snapshot lands.
    """
    try:
        from django_q.tasks import async_task
        task_id = async_task(
            'sales_velocity.services.aggregator.run_daily_aggregation',
        )
        return Response({'ok': True, 'task_id': task_id})
    except ImportError:
        return Response(
            {'error': 'Django-Q not available'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


# ── Tier 1+2: Ivan-parity table + summary header ────────────────────────────

@api_view(['GET'])
def table_view(request):
    """
    Ivan-parity velocity table: one row per product with stock, deficit,
    blank, material, velocity, compact channel breakdown, and WIP count.

    Query params:
      ?status=out_of_stock|low|ok|surplus  — filter by computed status
      ?blank=DONALD,DICK,...               — CSV filter on Product.blank
      ?search=M0001 or partial description
      ?sort=deficit|velocity|m_number      — default: deficit desc
      ?limit=100&offset=0                  — pagination
    """
    from products.models import Product
    from production.models import ProductionOrder
    from stock.models import StockLevel

    # Latest snapshot date
    latest = SalesVelocityHistory.objects.aggregate(m=Max('snapshot_date'))['m']

    # Base queryset: all products with a stock level
    qs = (
        Product.objects
        .filter(active=True)
        .select_related()
        .annotate(
            current_stock=Coalesce(
                Subquery(
                    StockLevel.objects
                    .filter(product_id=OuterRef('pk'))
                    .values('current_stock')[:1]
                ),
                Value(0),
            ),
            sixty_day_sales=Coalesce(
                Subquery(
                    StockLevel.objects
                    .filter(product_id=OuterRef('pk'))
                    .values('sixty_day_sales')[:1]
                ),
                Value(0),
            ),
        )
    )

    # Add velocity from latest snapshot (sum across channels)
    if latest:
        qs = qs.annotate(
            velocity_30d=Coalesce(
                Subquery(
                    SalesVelocityHistory.objects
                    .filter(product_id=OuterRef('pk'), snapshot_date=latest)
                    .values('product_id')
                    .annotate(total=Sum('units_sold_30d'))
                    .values('total')[:1]
                ),
                Value(0),
            ),
        )
    else:
        qs = qs.annotate(velocity_30d=Value(0))

    # Add WIP count (active production orders)
    qs = qs.annotate(
        wip_count=Coalesce(
            Subquery(
                ProductionOrder.objects
                .filter(product_id=OuterRef('pk'), completed_at__isnull=True)
                .values('product_id')
                .annotate(c=Count('id'))
                .values('c')[:1]
            ),
            Value(0),
        ),
    )

    # Search filter
    search = request.query_params.get('search', '').strip()
    if search:
        qs = qs.filter(
            Q(m_number__icontains=search) | Q(description__icontains=search)
        )

    # Blank filter
    blank_filter = request.query_params.get('blank', '').strip()
    if blank_filter:
        blanks = [b.strip().upper() for b in blank_filter.split(',') if b.strip()]
        if blanks:
            qs = qs.filter(blank__in=blanks)

    # Sorting
    sort = request.query_params.get('sort', 'deficit')
    if sort == 'velocity':
        qs = qs.order_by('-velocity_30d', 'deficit_computed')
    elif sort == 'm_number':
        qs = qs.order_by('m_number')
    else:
        # Default: highest deficit first (most urgent to make)
        qs = qs.order_by(
            (F('sixty_day_sales') - F('current_stock')).desc(),
            'm_number',
        )

    # Pagination
    limit = min(int(request.query_params.get('limit', 200)), 500)
    offset = int(request.query_params.get('offset', 0))
    total_count = qs.count()
    page = list(qs[offset:offset + limit])

    # Per-product channel breakdown from SVHistory
    product_ids = [p.pk for p in page]
    channel_map: dict[int, dict[str, int]] = {}
    if latest and product_ids:
        for row in (
            SalesVelocityHistory.objects
            .filter(product_id__in=product_ids, snapshot_date=latest)
            .values('product_id', 'channel', 'units_sold_30d')
        ):
            pid = row['product_id']
            channel_map.setdefault(pid, {})[row['channel']] = row['units_sold_30d']

    rows = []
    for p in page:
        stock = getattr(p, 'current_stock', 0) or 0
        target = getattr(p, 'sixty_day_sales', 0) or 0
        deficit = target - stock
        vel = getattr(p, 'velocity_30d', 0) or 0
        wip = getattr(p, 'wip_count', 0) or 0

        # Status badge
        if stock == 0 and target > 0:
            badge = 'OUT_OF_STOCK'
        elif deficit > 0:
            badge = 'LOW'
        elif deficit < -20:
            badge = 'SURPLUS'
        else:
            badge = 'OK'

        # Compact channel string: "UK 15 · DE 3 · ETSY 2"
        ch = channel_map.get(p.pk, {})
        channel_parts = sorted(ch.items(), key=lambda x: -x[1])
        channel_str = ' · '.join(
            f'{code.replace("amazon_", "").upper()} {qty}'
            for code, qty in channel_parts if qty > 0
        )

        rows.append({
            'product_id': p.pk,
            'm_number': p.m_number,
            'description': p.description,
            'blank': p.blank,
            'material': p.material,
            'current_stock': stock,
            'sixty_day_target': target,
            'deficit': deficit,
            'velocity_30d': vel,
            'velocity_60d_est': vel * 2,
            'status': badge,
            'channels': channel_str,
            'channel_detail': ch,
            'wip_count': wip,
            'image_url': p.image_url or '',
        })

    # Status filter (post-computed because it's derived)
    status_filter = request.query_params.get('status', '').strip().upper()
    if status_filter:
        rows = [r for r in rows if r['status'] == status_filter]

    return Response({
        'rows': rows,
        'total_count': total_count,
        'snapshot_date': latest.isoformat() if latest else None,
        'limit': limit,
        'offset': offset,
    })


@api_view(['GET'])
def summary_view(request):
    """
    Dashboard summary header — the numbers Ivan had at the top of his sheet.
    """
    from stock.models import StockLevel

    # Aggregate across all StockLevel rows
    agg = StockLevel.objects.aggregate(
        total_stock=Coalesce(Sum('current_stock'), Value(0)),
        total_sixty_day=Coalesce(Sum('sixty_day_sales'), Value(0)),
        products_with_stock=Count('id', filter=Q(current_stock__gt=0)),
    )
    total_stock = agg['total_stock']
    total_sixty = agg['total_sixty_day']
    coverage_pct = round(total_stock / total_sixty * 100, 1) if total_sixty else 0

    # Deficit breakdown
    deficit_positive = StockLevel.objects.filter(
        sixty_day_sales__gt=F('current_stock'),
    ).count()
    out_of_stock = StockLevel.objects.filter(
        current_stock=0, sixty_day_sales__gt=0,
    ).count()
    surplus = StockLevel.objects.filter(
        current_stock__gt=F('sixty_day_sales') + 20,
    ).count()

    # Latest snapshot
    latest = SalesVelocityHistory.objects.aggregate(m=Max('snapshot_date'))['m']
    last_success = SalesVelocityAPICall.objects.filter(
        response_status=200,
    ).order_by('-created_at').first()

    return Response({
        'total_units_on_hand': total_stock,
        'total_sixty_day_target': total_sixty,
        'coverage_pct': coverage_pct,
        'products_need_making': deficit_positive,
        'out_of_stock_count': out_of_stock,
        'surplus_count': surplus,
        'latest_snapshot_date': latest.isoformat() if latest else None,
        'last_sync_at': (
            last_success.created_at.isoformat() if last_success else None
        ),
        'shadow_mode_enabled': not bool(
            getattr(settings, 'SALES_VELOCITY_WRITE_ENABLED', False)
        ),
    })
