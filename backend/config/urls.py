from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.decorators import api_view
from rest_framework.response import Response

from products.views import ProductViewSet, SKUViewSet
from stock.views import StockLevelViewSet
from production.views import ProductionOrderViewSet, MakeListView
from shipments.views import ShipmentViewSet
from d2c.views import DispatchOrderViewSet
from procurement.views import MaterialViewSet
from production.views_records import ProductionRecordViewSet
from core.auth_views import login_view, logout_view, me_view
from core.views_bugreport import bugreport_view

router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='product')
router.register(r'skus', SKUViewSet, basename='sku')
router.register(r'stock', StockLevelViewSet, basename='stock')
router.register(r'production-orders', ProductionOrderViewSet, basename='production-order')
router.register(r'shipments', ShipmentViewSet, basename='shipment')
router.register(r'dispatch', DispatchOrderViewSet, basename='dispatch')
router.register(r'materials', MaterialViewSet, basename='material')
router.register(r'records', ProductionRecordViewSet, basename='record')


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
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),
    path('api/auth/login/', login_view, name='login'),
    path('api/auth/logout/', logout_view, name='logout'),
    path('api/auth/me/', me_view, name='me'),
    path('api/make-list/', MakeListView.as_view(), name='make-list'),
    path('api/bugreport/', bugreport_view, name='bugreport'),
    path('api/imports/', include('imports.urls')),
    path('api/restock/', include('restock.urls')),
    path('api/', include('barcodes.urls')),
]
