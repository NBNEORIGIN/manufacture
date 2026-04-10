"""
URL routes for the FBA Shipment Automation module.

Wired under /api/fba/ from config/urls.py.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from fba_shipments.views import FBAShipmentPlanViewSet, preflight

router = DefaultRouter()
router.register(r'plans', FBAShipmentPlanViewSet, basename='fba-plan')

urlpatterns = [
    path('', include(router.urls)),
    path('preflight/', preflight, name='fba-preflight'),
]
