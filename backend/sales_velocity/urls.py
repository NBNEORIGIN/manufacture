"""
URL routing for the sales_velocity module.

Includes:
- Admin-only OAuth consent views for eBay (one-time setup + reconnect)
- DRF API endpoints mounted under /api/sales-velocity/ (Phase 2B.5)
"""
from __future__ import annotations

from django.urls import path

from sales_velocity import views_oauth, views_oauth_xero

urlpatterns = [
    # Admin OAuth consent flow for eBay (one-time per environment).
    path(
        'admin/oauth/ebay/connect',
        views_oauth.ebay_connect,
        name='sales_velocity_ebay_connect',
    ),
    path(
        'admin/oauth/ebay/callback',
        views_oauth.ebay_callback,
        name='sales_velocity_ebay_callback',
    ),
    # Admin OAuth consent flow for Xero (B2B revenue).
    path(
        'admin/oauth/xero/connect',
        views_oauth_xero.xero_connect,
        name='sales_velocity_xero_connect',
    ),
    path(
        'admin/oauth/xero/callback',
        views_oauth_xero.xero_callback,
        name='sales_velocity_xero_callback',
    ),
]
