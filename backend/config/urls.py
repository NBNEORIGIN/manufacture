from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.decorators import api_view
from rest_framework.response import Response

from products.views import ProductViewSet, SKUViewSet, BlankTypeViewSet
from stock.views import StockLevelViewSet
from production.views import ProductionOrderViewSet, MakeListView
from shipments.views import ShipmentViewSet, ShipmentItemViewSet
from d2c.views import DispatchOrderViewSet
from d2c.views_personalised import personalised_stats, set_product_type_blanks, set_colour_blanks, personalised_m_numbers
from procurement.views import MaterialViewSet
from production.views_records import ProductionRecordViewSet
from production.views_assignment import JobAssignmentViewSet
from production.views_job import JobViewSet
from core.auth_views import login_view, logout_view, me_view, users_list_view
from core.views_bugreport import bugreport_view
from core.cairn_views import (
    cairn_snapshot,
    cairn_quartile_brief,
    cairn_ads_sync,
    cairn_opportunities,
    cairn_margin_per_sku,
    cairn_etsy_margin_per_sku,
    cairn_ebay_margin_per_sku,
    cairn_etsy_listings_lookup,
    cairn_etsy_ad_spend_ingest,
    cairn_cogs_override,
)
from sales_velocity.views_xero import xero_invoices_view, xero_health_view

router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='product')
router.register(r'skus', SKUViewSet, basename='sku')
router.register(r'blanks', BlankTypeViewSet, basename='blank')
router.register(r'stock', StockLevelViewSet, basename='stock')
router.register(r'production-orders', ProductionOrderViewSet, basename='production-order')
router.register(r'shipments', ShipmentViewSet, basename='shipment')
router.register(r'shipment-items', ShipmentItemViewSet, basename='shipment-item')
router.register(r'dispatch', DispatchOrderViewSet, basename='dispatch')
router.register(r'materials', MaterialViewSet, basename='material')
router.register(r'records', ProductionRecordViewSet, basename='record')
router.register(r'assignments', JobAssignmentViewSet, basename='assignment')
router.register(r'jobs', JobViewSet, basename='job')


@api_view(['GET'])
def api_index(request):
    return Response({
        'app': 'NBNE Manufacture',
        'version': '0.1.0',
        'endpoints': {
            'products': '/api/products/',
            'skus': '/api/skus/',
            'stock': '/api/stock/',
            'make-list': '/api/make-list/',
            'production-orders': '/api/production-orders/',
            'shipments': '/api/shipments/',
            'dispatch': '/api/dispatch/',
            'materials': '/api/materials/',
        }
    })


urlpatterns = [
    path('', api_index),
    # eBay OAuth consent flow (must be before admin/ catch-all)
    path('', include('sales_velocity.urls')),
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),
    path('api/auth/login/', login_view, name='login'),
    path('api/auth/logout/', logout_view, name='logout'),
    path('api/auth/me/', me_view, name='me'),
    path('api/auth/users/', users_list_view, name='users-list'),
    path('api/make-list/', MakeListView.as_view(), name='make-list'),
    path('api/bugreport/', bugreport_view, name='bugreport'),
    path('api/d2c/personalised/stats/', personalised_stats, name='d2c-personalised-stats'),
    path('api/d2c/personalised/blanks/', set_product_type_blanks, name='d2c-set-product-type-blanks'),
    path('api/d2c/personalised/colour-blanks/', set_colour_blanks, name='d2c-set-colour-blanks'),
    path('api/d2c/personalised/m-numbers/', personalised_m_numbers, name='d2c-personalised-m-numbers'),
    path('api/cairn/snapshot', cairn_snapshot, name='cairn-snapshot'),
    path('api/cairn/quartile-brief/', cairn_quartile_brief, name='cairn-quartile-brief'),
    path('api/cairn/ads-sync/', cairn_ads_sync, name='cairn-ads-sync'),
    path('api/cairn/opportunities/', cairn_opportunities, name='cairn-opportunities'),
    path('api/cairn/margin/per-sku/', cairn_margin_per_sku, name='cairn-margin-per-sku'),
    path('api/cairn/etsy/margin/per-sku/', cairn_etsy_margin_per_sku, name='cairn-etsy-margin-per-sku'),
    path('api/cairn/ebay/margin/per-sku/', cairn_ebay_margin_per_sku, name='cairn-ebay-margin-per-sku'),
    path('api/cairn/etsy/listings/lookup-by-title/', cairn_etsy_listings_lookup, name='cairn-etsy-listings-lookup'),
    path('api/cairn/etsy/ad-spend/ingest/', cairn_etsy_ad_spend_ingest, name='cairn-etsy-ad-spend-ingest'),
    path('api/cairn/cogs-override/', cairn_cogs_override, name='cairn-cogs-override'),
    # Xero data API for cross-service consumption (Ledger). Bearer or
    # X-API-Key auth; see sales_velocity.views_xero for details.
    path('api/xero/invoices/', xero_invoices_view, name='xero-invoices'),
    path('api/xero/health',    xero_health_view,   name='xero-health'),
    path('api/imports/', include('imports.urls')),
    path('api/restock/', include('restock.urls')),
    path('api/', include('barcodes.urls')),
    path('api/fba/', include('fba_shipments.urls')),
    path('api/sales-velocity/', include('sales_velocity.api_urls')),
    path('api/costs/', include('costs.urls')),
]
