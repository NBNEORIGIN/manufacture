"""
Xero adapter for B2B revenue.

OAuth2 flow identical to eBay: consent once at /admin/oauth/xero/connect,
store refresh + access tokens on OAuthCredential(provider='xero'),
auto-refresh on expiry.

Pulls ACCREC (sales) invoices from Xero Accounting API to calculate
B2B monthly revenue for overhead allocation.

Scopes: accounting.transactions.read (granular, post-March 2026)
"""
from __future__ import annotations

import base64
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone as django_tz

from sales_velocity.models import OAuthCredential

logger = logging.getLogger(__name__)

XERO_AUTH_URL = 'https://login.xero.com/identity/connect/authorize'
XERO_TOKEN_URL = 'https://identity.xero.com/connect/token'
XERO_API_BASE = 'https://api.xero.com/api.xro/2.0'
XERO_CONNECTIONS_URL = 'https://api.xero.com/connections'

XERO_SCOPES = [
    'openid',
    'profile',
    'email',
    'accounting.invoices.read',
    'offline_access',
]

TOKEN_REFRESH_BUFFER_SECONDS = 300  # 5 minutes


def _get_client_id() -> str:
    return getattr(settings, 'XERO_CLIENT_ID', '') or ''


def _get_client_secret() -> str:
    return getattr(settings, 'XERO_CLIENT_SECRET', '') or ''


def _get_credential() -> OAuthCredential | None:
    return OAuthCredential.objects.filter(provider='xero').first()


def _refresh_access_token(cred: OAuthCredential) -> str:
    """Refresh the access token using the stored refresh token."""
    client_id = _get_client_id()
    client_secret = _get_client_secret()

    with transaction.atomic():
        cred = OAuthCredential.objects.select_for_update().get(pk=cred.pk)

        # Another thread might have refreshed already
        if cred.access_token_expires_at and cred.access_token_expires_at > django_tz.now() + timedelta(seconds=TOKEN_REFRESH_BUFFER_SECONDS):
            return cred.access_token

        resp = httpx.post(
            XERO_TOKEN_URL,
            data={
                'grant_type': 'refresh_token',
                'refresh_token': cred.refresh_token,
                'client_id': client_id,
                'client_secret': client_secret,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        cred.access_token = data['access_token']
        cred.refresh_token = data.get('refresh_token', cred.refresh_token)
        cred.access_token_expires_at = django_tz.now() + timedelta(seconds=int(data.get('expires_in', 1800)))
        cred.last_refreshed_at = django_tz.now()
        cred.save(update_fields=['access_token', 'refresh_token', 'access_token_expires_at', 'last_refreshed_at'])

        return cred.access_token


def get_valid_access_token() -> str:
    """Get a valid access token, refreshing if needed."""
    cred = _get_credential()
    if not cred:
        raise RuntimeError('No Xero OAuth credential found — run /admin/oauth/xero/connect first')

    if (
        cred.access_token_expires_at
        and cred.access_token_expires_at > django_tz.now() + timedelta(seconds=TOKEN_REFRESH_BUFFER_SECONDS)
    ):
        return cred.access_token

    return _refresh_access_token(cred)


def get_tenant_id() -> str:
    """Get the Xero tenant (organisation) ID from the connections endpoint."""
    token = get_valid_access_token()
    resp = httpx.get(
        XERO_CONNECTIONS_URL,
        headers={'Authorization': f'Bearer {token}'},
        timeout=15,
    )
    resp.raise_for_status()
    connections = resp.json()
    if not connections:
        raise RuntimeError('No Xero organisations connected to this app')
    return connections[0]['tenantId']


def fetch_invoice_revenue(lookback_days: int = 30) -> dict:
    """
    Fetch ACCREC (sales) invoices from Xero for the last N days.
    Returns:
        {
            'total_revenue_gbp': Decimal,
            'invoice_count': int,
            'period_start': date,
            'period_end': date,
        }
    """
    token = get_valid_access_token()
    tenant_id = get_tenant_id()

    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)

    # Xero date filter format
    where_clause = (
        f'Type=="ACCREC" AND Status!="DELETED" AND Status!="VOIDED" AND Status!="DRAFT" '
        f'AND Date>=DateTime({start_date.year},{start_date.month},{start_date.day}) '
        f'AND Date<=DateTime({end_date.year},{end_date.month},{end_date.day})'
    )

    headers = {
        'Authorization': f'Bearer {token}',
        'Xero-Tenant-Id': tenant_id,
        'Accept': 'application/json',
    }

    total = Decimal('0')
    invoice_count = 0
    page = 1

    while True:
        resp = httpx.get(
            f'{XERO_API_BASE}/Invoices',
            params={'where': where_clause, 'page': page},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        invoices = data.get('Invoices', [])

        if not invoices:
            break

        for inv in invoices:
            amount = inv.get('Total') or inv.get('SubTotal') or 0
            total += Decimal(str(amount))
            invoice_count += 1

        # Xero paginates at 100 per page
        if len(invoices) < 100:
            break
        page += 1

    return {
        'total_revenue_gbp': total.quantize(Decimal('0.01')),
        'invoice_count': invoice_count,
        'period_start': start_date,
        'period_end': end_date,
    }
