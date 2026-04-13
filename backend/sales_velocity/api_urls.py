"""
DRF API routing for the sales_velocity module.

Mounted at /api/sales-velocity/ by config/urls.py. Populated in
Phase 2B.5 with viewsets for the Sales Velocity tab UI.
"""
from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from sales_velocity import views

router = DefaultRouter()
router.register(r'history', views.SalesVelocityHistoryViewSet, basename='sv-history')
router.register(r'unmatched', views.UnmatchedSKUViewSet, basename='sv-unmatched')
router.register(r'manual-sales', views.ManualSaleViewSet, basename='sv-manual-sales')
router.register(r'drift-alerts', views.DriftAlertViewSet, basename='sv-drift-alerts')

urlpatterns = [
    *router.urls,
    path('status/', views.status_view, name='sv-status'),
    path('shadow-diff/', views.shadow_diff_view, name='sv-shadow-diff'),
    path('refresh/', views.refresh_view, name='sv-refresh'),
    path('table/', views.table_view, name='sv-table'),
    path('summary/', views.summary_view, name='sv-summary'),
]
