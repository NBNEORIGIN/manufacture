from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.decorators import api_view
from rest_framework.response import Response

from products.views import ProductViewSet, SKUViewSet
from stock.views import StockLevelViewSet
from production.views import ProductionOrderViewSet, MakeListView

router = DefaultRouter(trailing_slash=False)
router.register(r'products', ProductViewSet, basename='product')
router.register(r'skus', SKUViewSet, basename='sku')
router.register(r'stock', StockLevelViewSet, basename='stock')
router.register(r'production-orders', ProductionOrderViewSet, basename='production-order')


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
        }
    })


urlpatterns = [
    path('', api_index),
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),
    path('api/make-list', MakeListView.as_view(), name='make-list'),
    path('api/make-list/', MakeListView.as_view(), name='make-list-slash'),
    path('api/imports/', include('imports.urls')),
    path('api/imports', include('imports.urls')),
]
