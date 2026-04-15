from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BlankCostViewSet,
    MNumberCostOverrideViewSet,
    cost_config_view,
    cost_price_bulk_view,
    cost_price_view,
)

router = DefaultRouter()
router.register(r'blanks', BlankCostViewSet, basename='cost-blank')
router.register(r'overrides', MNumberCostOverrideViewSet, basename='cost-override')

urlpatterns = [
    path('', include(router.urls)),
    path('config/', cost_config_view, name='cost-config'),
    path('price/bulk/', cost_price_bulk_view, name='cost-price-bulk'),
    path('price/<str:m_number>/', cost_price_view, name='cost-price'),
]
