"""
URL routing for the sales_velocity module.

Includes:
- Admin-only OAuth consent views for eBay (one-time setup + reconnect)
- DRF API endpoints mounted under /api/sales-velocity/ (Phase 2B.5)
"""
from __future__ import annotations

from django.urls import path

from sales_velocity import views_oauth

urlpatterns = [
    # Admin OAuth consent flow for eBay (one-time per environment).
    # Staff-only — protected by @staff_member_required on the views.
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
]
