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
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

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

# Widened on 2026-05-08 from accounting.invoices.read to
# accounting.transactions.read to expose ACCPAY (bills) data to Ledger.
# Adds accounting.contacts.read for supplier-name normalisation.
#
# After deploying the scope change, Toby must re-consent at
# /admin/oauth/xero/connect — Xero prompts because new scopes are
# requested. The existing access token keeps working until expiry
# (~30 min) but refresh against the new client config will fail unless
# new tokens are issued via consent. See README for the playbook.
XERO_SCOPES = [
    'openid',
    'profile',
    'email',
    'accounting.transactions.read',   # Invoices (ACCREC + ACCPAY) + Payments + BankTransactions
    'accounting.contacts.read',       # Supplier name normalisation
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


# ── Per-invoice fetchers (added 2026-05-08 for Ledger consumption) ─────────
#
# `fetch_invoice_revenue()` above is the legacy aggregate-only path used by
# Manufacture's own overhead allocation. The fetchers below return per-
# invoice rows for Ledger to write into its expenditure / revenue tables
# via the /api/xero/invoices/ endpoint (see views_xero.py).


# Statuses that represent real, recognised invoices. DRAFT / DELETED /
# VOIDED / SUBMITTED-with-no-action are filtered out at the where clause.
_REAL_INVOICE_STATUSES: frozenset[str] = frozenset({'AUTHORISED', 'PAID', 'SUBMITTED'})


def _xero_get(
    url: str,
    headers: dict,
    params: dict | None = None,
    *,
    max_retries: int = 3,
    timeout: float = 30.0,
) -> httpx.Response:
    """
    GET wrapper with exponential-ish backoff on Xero's 429 rate-limit.

    Xero returns Retry-After in seconds when it throttles. We honour
    that header + 1s safety margin per attempt. Final attempt re-raises
    via `response.raise_for_status()` if it still 429s.

    Non-429 errors (5xx, network) raise immediately. Caller decides
    whether to retry or surface the error.
    """
    last_resp: httpx.Response | None = None
    for attempt in range(max_retries):
        resp = httpx.get(url, headers=headers, params=params or {}, timeout=timeout)
        last_resp = resp
        if resp.status_code == 429:
            try:
                retry_after = int(resp.headers.get('Retry-After', '5'))
            except ValueError:
                retry_after = 5
            logger.warning(
                'Xero 429 on %s (attempt %d/%d) — sleeping %ds',
                url, attempt + 1, max_retries, retry_after + 1,
            )
            time.sleep(retry_after + 1)
            continue
        resp.raise_for_status()
        return resp
    # Out of retries — raise on the last response for visibility.
    if last_resp is not None:
        last_resp.raise_for_status()
    raise RuntimeError(f'Xero rate-limited after {max_retries} retries')


def _summarise_lines(invoice: dict) -> tuple[str, int]:
    """
    Pack the LineItem descriptions into a single 500-char string and
    return (description, line_count). Drops empty descriptions, joins
    with ' | ', truncates at 497 + '...' to keep the wire payload tidy.
    """
    line_items = invoice.get('LineItems') or []
    parts: list[str] = []
    for li in line_items:
        d = (li.get('Description') or '').strip()
        if d:
            parts.append(d)
    joined = ' | '.join(parts)
    if len(joined) > 500:
        joined = joined[:497] + '...'
    return joined, len(line_items)


def fetch_invoices(
    invoice_type: str,
    lookback_days: int = 30,
) -> list[dict]:
    """
    Fetch per-invoice data from Xero (no aggregation).

    Args:
        invoice_type: 'ACCREC' (sales) or 'ACCPAY' (bills). Required.
        lookback_days: how many days back from today.

    Returns: list of dicts, one per invoice. See module README /
    XERO_MANUFACTURE_PROMPT.md for the exact field shape — Ledger
    consumes this directly via the /api/xero/invoices/ endpoint.

    Filters: status in {AUTHORISED, PAID, SUBMITTED}. DRAFT, DELETED,
    VOIDED excluded at the Xero where clause level.

    Pagination: walks 100-per-page until exhausted.
    """
    if invoice_type not in ('ACCREC', 'ACCPAY'):
        raise ValueError(f'invoice_type must be ACCREC or ACCPAY, got {invoice_type!r}')

    token = get_valid_access_token()
    tenant_id = get_tenant_id()

    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)

    where_clause = (
        f'Type=="{invoice_type}" '
        f'AND Status!="DRAFT" AND Status!="DELETED" AND Status!="VOIDED" '
        f'AND Date>=DateTime({start_date.year},{start_date.month},{start_date.day}) '
        f'AND Date<=DateTime({end_date.year},{end_date.month},{end_date.day})'
    )

    headers = {
        'Authorization': f'Bearer {token}',
        'Xero-Tenant-Id': tenant_id,
        'Accept': 'application/json',
    }

    out: list[dict] = []
    page = 1
    while True:
        resp = _xero_get(
            f'{XERO_API_BASE}/Invoices',
            headers=headers,
            params={'where': where_clause, 'page': page},
        )
        data = resp.json()
        invoices = data.get('Invoices') or []
        if not invoices:
            break

        for inv in invoices:
            status = inv.get('Status')
            if status not in _REAL_INVOICE_STATUSES:
                # Belt-and-braces: the where clause already excludes the
                # bad statuses, but a Xero quirk occasionally lets one
                # through. Drop here too.
                continue

            description, line_count = _summarise_lines(inv)
            contact = inv.get('Contact') or {}

            out.append({
                'invoice_id':     inv.get('InvoiceID'),
                'invoice_number': inv.get('InvoiceNumber'),
                'type':           inv.get('Type'),
                'status':         status,
                'date':           inv.get('DateString') or inv.get('Date'),
                'due_date':       inv.get('DueDateString') or inv.get('DueDate'),
                'fully_paid_on':  inv.get('FullyPaidOnDate'),
                'contact_name':   contact.get('Name'),
                'contact_id':     contact.get('ContactID'),
                'description':    description,
                'currency_code':  inv.get('CurrencyCode'),
                'currency_rate':  float(inv.get('CurrencyRate') or 1.0),
                'subtotal':       float(inv.get('SubTotal') or 0),
                'total_tax':      float(inv.get('TotalTax') or 0),
                'total':          float(inv.get('Total') or 0),
                'amount_paid':    float(inv.get('AmountPaid') or 0),
                'amount_due':     float(inv.get('AmountDue') or 0),
                'line_count':     line_count,
            })

        if len(invoices) < 100:
            break
        page += 1

    logger.info(
        'fetch_invoices(type=%s, lookback_days=%d) -> %d invoices',
        invoice_type, lookback_days, len(out),
    )
    return out


def fetch_payments(lookback_days: int = 30) -> list[dict]:
    """
    Fetch payment records (Phase 2 — stub).

    Cash-side reconciliation will need this: each payment ties a bank
    transaction back to an invoice via PaymentID → InvoiceID. Useful
    for matching the rate-card B2B fee model to actual Stripe / bank
    fees in future.

    Intended response shape:
        {
            'payment_id':   str,
            'date':         'YYYY-MM-DD',
            'amount':       float,
            'invoice_id':   str,    # FK back to Invoice
            'account_code': str,    # bank account paid from
            'reference':    str,
        }

    Currently returns an empty list. When Phase 2 lands, the
    implementation hits GET /api.xro/2.0/Payments?where=Date>=...
    """
    return []


def get_token_status() -> dict:
    """
    Read the current OAuthCredential row + tenant cache for the
    /api/xero/health endpoint.

    Does NOT trigger a refresh — `connected: false` is the right
    signal when tokens are missing or expired, not "fix yourself
    silently". Re-consent flows go through the admin UI explicitly.
    """
    cred = _get_credential()
    if cred is None:
        return {
            'connected': False,
            'tenant_id': None,
            'tenant_name': None,
            'scopes': [],
            'token_expires_in_seconds': None,
            'last_refreshed_at': None,
            'reason': 'no_oauth_credential',
        }

    expires = cred.access_token_expires_at
    expires_in: int | None = None
    if expires is not None:
        delta = (expires - django_tz.now()).total_seconds()
        expires_in = int(delta) if delta > 0 else 0

    # Try to read the cached tenant from /connections without forcing a
    # refresh. If the access token is expired, surface that as
    # `connected: false` rather than refreshing-by-side-effect.
    tenant_id: str | None = None
    tenant_name: str | None = None
    if cred.access_token and expires_in and expires_in > 0:
        try:
            resp = httpx.get(
                XERO_CONNECTIONS_URL,
                headers={'Authorization': f'Bearer {cred.access_token}'},
                timeout=10,
            )
            if resp.status_code == 200:
                connections = resp.json() or []
                if connections:
                    tenant_id = connections[0].get('tenantId')
                    tenant_name = connections[0].get('tenantName')
        except httpx.HTTPError:
            # Silently degrade — health endpoint shouldn't 500 on a
            # transient Xero blip.
            pass

    # The model field is `scope` (singular, space-separated) per
    # OAuthCredential.scope. Split into a list for the health response.
    scopes: list[str] = []
    raw_scope = getattr(cred, 'scope', '') or ''
    if raw_scope:
        scopes = [s.strip() for s in raw_scope.split() if s.strip()]

    return {
        'connected': bool(cred.access_token and expires_in and expires_in > 0 and tenant_id),
        'tenant_id': tenant_id,
        'tenant_name': tenant_name,
        'scopes': scopes,
        'token_expires_in_seconds': expires_in,
        'last_refreshed_at': cred.last_refreshed_at.isoformat() if cred.last_refreshed_at else None,
    }
