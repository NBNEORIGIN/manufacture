"""
FBA Restock API views.

Endpoints:
  GET  /api/restock/marketplaces/         — list available marketplaces + last sync time
  POST /api/restock/sync/{marketplace}/   — trigger SP-API report download
  GET  /api/restock/{marketplace}/        — latest plan for a marketplace
  GET  /api/restock/{marketplace}/status/ — sync job status
  POST /api/restock/approve/              — approve items with quantities
  POST /api/restock/create-production/    — create production orders for approved items
  POST /api/restock/upload/              — manual CSV upload (no SP-API)
  GET  /api/restock/history/             — list all sync runs
"""
import logging
import threading
from datetime import datetime, timezone

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import RestockReport, RestockItem, RestockPlan
from .schema import MARKETPLACE_TO_REGION

logger = logging.getLogger(__name__)


def _run_spapi_sync(report: RestockReport, marketplace: str):
    """Background thread: download, parse, assemble restock plan."""
    from .spapi_client import request_report, download_report
    from .parser import parse_restock_csv
    from .assembler import assemble_restock_plan

    region = MARKETPLACE_TO_REGION.get(marketplace.upper(), 'EU')

    try:
        report.status = 'running'
        report.save(update_fields=['status'])

        report_id = request_report(marketplace)
        report.report_id = report_id
        report.save(update_fields=['report_id'])

        raw_bytes = download_report(report_id, region)
        rows = parse_restock_csv(raw_bytes, filter_marketplace=marketplace)

        assemble_restock_plan(report, rows)

        report.row_count = len(rows)
        report.status = 'complete'
        report.save(update_fields=['row_count', 'status'])

    except Exception as exc:
        logger.exception('Restock sync failed for %s', marketplace)
        report.status = 'error'
        report.error_message = str(exc)
        report.save(update_fields=['status', 'error_message'])


@api_view(['GET'])
def marketplaces_view(request):
    """List available marketplaces with last sync time and status."""
    from django.db.models import Max

    marketplaces = ['GB', 'US', 'CA', 'AU', 'DE', 'FR']
    result = []
    for mp in marketplaces:
        last = RestockReport.objects.filter(marketplace=mp).order_by('-created_at').first()
        result.append({
            'marketplace': mp,
            'region': MARKETPLACE_TO_REGION.get(mp, ''),
            'last_synced': last.created_at.isoformat() if last else None,
            'last_status': last.status if last else None,
            'last_row_count': last.row_count if last else 0,
        })
    return Response({'marketplaces': result})


@api_view(['POST'])
def sync_view(request, marketplace: str):
    """Trigger SP-API report download for a marketplace. Returns immediately."""
    marketplace = marketplace.upper()
    if marketplace not in MARKETPLACE_TO_REGION:
        return Response({'error': f'Unknown marketplace: {marketplace}'}, status=400)

    report = RestockReport.objects.create(
        marketplace=marketplace,
        region=MARKETPLACE_TO_REGION[marketplace],
        status='pending',
        source='spapi',
    )

    t = threading.Thread(target=_run_spapi_sync, args=(report, marketplace), daemon=True)
    t.start()

    return Response({
        'report_id': report.id,
        'marketplace': marketplace,
        'status': 'started',
        'message': 'SP-API report requested. Poll /api/restock/{marketplace}/status/ for progress.',
    })


@api_view(['GET'])
def status_view(request, marketplace: str):
    """Job status for the most recent sync of a marketplace."""
    report = (
        RestockReport.objects
        .filter(marketplace=marketplace.upper())
        .order_by('-created_at')
        .first()
    )
    if not report:
        return Response({'status': 'no_sync', 'marketplace': marketplace})

    return Response({
        'report_id': report.id,
        'marketplace': marketplace,
        'status': report.status,
        'row_count': report.row_count,
        'error_message': report.error_message,
        'created_at': report.created_at.isoformat(),
    })


@api_view(['GET'])
def plan_view(request, marketplace: str):
    """
    Latest restock plan for a marketplace.
    Supports ?alert=out_of_stock&search=M0616 filtering.
    """
    marketplace = marketplace.upper()
    report = (
        RestockReport.objects
        .filter(marketplace=marketplace, status='complete')
        .order_by('-created_at')
        .first()
    )
    if not report:
        return Response({
            'marketplace': marketplace,
            'report': None,
            'items': [],
            'summary': None,
        })

    qs = RestockItem.objects.filter(report=report)

    alert_filter = request.query_params.get('alert')
    if alert_filter == 'action':
        qs = qs.filter(alert__in=['out_of_stock', 'reorder_now'])

    search = request.query_params.get('search', '').strip()
    if search:
        qs = qs.filter(merchant_sku__icontains=search) | qs.filter(m_number__icontains=search)

    items = list(qs.values(
        'id', 'merchant_sku', 'asin', 'm_number', 'product_name',
        'units_available', 'units_inbound', 'units_total',
        'days_of_supply_amazon', 'units_sold_30d', 'alert',
        'amazon_recommended_qty', 'newsvendor_qty', 'newsvendor_confidence',
        'newsvendor_notes', 'approved_qty', 'production_order_id',
    ))

    total_items = RestockItem.objects.filter(report=report).count()
    action_items = RestockItem.objects.filter(
        report=report, alert__in=['out_of_stock', 'reorder_now']
    ).count()
    newsvendor_units = sum(
        i['newsvendor_qty'] or 0
        for i in items
        if i['newsvendor_qty']
    )

    return Response({
        'marketplace': marketplace,
        'report': {
            'id': report.id,
            'created_at': report.created_at.isoformat(),
            'row_count': report.row_count,
        },
        'items': items,
        'summary': {
            'total_items': total_items,
            'action_items': action_items,
            'newsvendor_total_units': newsvendor_units,
            'filtered_count': len(items),
        },
    })


@api_view(['POST'])
def approve_view(request):
    """
    Approve selected items with quantities.
    Body: {items: [{id: int, approved_qty: int}, ...]}
    """
    items_data = request.data.get('items', [])
    if not items_data:
        return Response({'error': 'No items provided'}, status=400)

    user_name = request.user.get_full_name() or request.user.email if request.user.is_authenticated else 'unknown'
    now = datetime.now(timezone.utc)

    updated = 0
    for item_data in items_data:
        item_id = item_data.get('id')
        qty = item_data.get('approved_qty', 0)
        if item_id is None:
            continue
        rows = RestockItem.objects.filter(id=item_id).update(
            approved_qty=qty,
            approved_by=user_name,
            approved_at=now,
        )
        updated += rows

    return Response({'updated': updated})


@api_view(['POST'])
def create_production_view(request):
    """
    Create production orders for all approved items in a report.
    Body: {report_id: int} or {marketplace: str} (uses latest complete report).
    """
    from production.models import ProductionOrder, ProductionStage
    from products.models import Product

    report_id = request.data.get('report_id')
    marketplace = request.data.get('marketplace', '').upper()

    if report_id:
        report = RestockReport.objects.filter(id=report_id).first()
    elif marketplace:
        report = (
            RestockReport.objects
            .filter(marketplace=marketplace, status='complete')
            .order_by('-created_at')
            .first()
        )
    else:
        return Response({'error': 'Provide report_id or marketplace'}, status=400)

    if not report:
        return Response({'error': 'Report not found'}, status=404)

    approved_items = RestockItem.objects.filter(
        report=report,
        approved_qty__gt=0,
        production_order_id__isnull=True,
    )

    created_count = 0
    skipped_count = 0
    user = request.user if request.user.is_authenticated else None

    for item in approved_items:
        if not item.m_number:
            skipped_count += 1
            continue
        product = Product.objects.filter(m_number=item.m_number, active=True).first()
        if not product:
            skipped_count += 1
            continue

        order = ProductionOrder.objects.create(
            product=product,
            quantity=item.approved_qty,
            priority=100 if item.alert == 'out_of_stock' else 50,
            created_by=user,
            notes=f'FBA restock — {item.marketplace} — auto from restock plan',
        )

        # Create pipeline stages for this order
        stages = ['designed', 'printed', 'processed', 'cut', 'labelled', 'packed', 'shipped']
        ProductionStage.objects.bulk_create([
            ProductionStage(order=order, stage=s)
            for s in stages
        ])

        item.production_order_id = order.id
        item.save(update_fields=['production_order_id'])
        created_count += 1

    return Response({
        'created': created_count,
        'skipped': skipped_count,
        'message': f'Created {created_count} production orders',
    })


@csrf_exempt
@api_view(['POST'])
def upload_view(request):
    """Manual CSV upload — bypasses SP-API for testing or offline use."""
    from .parser import parse_restock_csv
    from .assembler import assemble_restock_plan

    marketplace = request.data.get('marketplace', '').upper()
    if not marketplace:
        return Response({'error': 'marketplace required'}, status=400)

    uploaded = request.FILES.get('file')
    if not uploaded:
        return Response({'error': 'file required'}, status=400)

    content = uploaded.read()
    rows = parse_restock_csv(content, filter_marketplace=marketplace)

    report = RestockReport.objects.create(
        marketplace=marketplace,
        region=MARKETPLACE_TO_REGION.get(marketplace, 'EU'),
        status='running',
        source='manual',
    )

    assemble_restock_plan(report, rows)

    report.row_count = len(rows)
    report.status = 'complete'
    report.save(update_fields=['row_count', 'status'])

    return Response({
        'report_id': report.id,
        'marketplace': marketplace,
        'row_count': len(rows),
        'status': 'complete',
    })


@api_view(['GET'])
def history_view(request):
    """List all sync runs."""
    reports = RestockReport.objects.all()[:50]
    return Response({
        'reports': [
            {
                'id': r.id,
                'marketplace': r.marketplace,
                'status': r.status,
                'source': r.source,
                'row_count': r.row_count,
                'created_at': r.created_at.isoformat(),
                'error_message': r.error_message,
            }
            for r in reports
        ]
    })
