"""
Xero data API for cross-service consumption (added 2026-05-08).

Manufacture owns the Xero OAuth connection. Other services on the same
Hetzner box (Ledger primarily) consume invoice data through this API
rather than running their own OAuth — single refresh-token lifecycle,
single consent flow, single source of truth for what's "real" in Xero.

Endpoints:
- GET /api/xero/invoices/?type=ACCREC|ACCPAY&days=30  (cached 5 min)
- GET /api/xero/health                                (live, no cache)

Auth:
Both endpoints accept either:
  - Authorization: Bearer <CAIRN_API_KEY>
  - X-API-Key: <CAIRN_API_KEY>
or a logged-in Django session (so admins can hit them directly in
browser for diagnostics). The shared key is `CAIRN_API_KEY` in
Manufacture's env (Ledger reads from `DEEK_API_KEY` on its side, but
the values match — same shared secret across the cluster).

If the env var is unset, the Bearer / X-API-Key paths are bypassed and
session auth is the only gate. Useful in dev.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from sales_velocity.adapters import xero as xero_adapter

logger = logging.getLogger(__name__)


# ── Auth helper ──────────────────────────────────────────────────────────────

def _auth_ok(request: Request) -> bool:
    """
    Accept the cluster-shared API key via Bearer or X-API-Key header,
    OR a logged-in Django session. If CAIRN_API_KEY is unset the header
    paths are bypassed and we fall back to session auth only.
    """
    expected = getattr(settings, 'CAIRN_API_KEY', '') or ''

    if expected:
        # Bearer
        bearer = request.META.get('HTTP_AUTHORIZATION', '') or ''
        if bearer.startswith('Bearer ') and bearer[len('Bearer '):].strip() == expected:
            return True
        # X-API-Key
        x_api = (
            request.META.get('HTTP_X_API_KEY', '')
            or request.META.get('HTTP_X_APIKEY', '')
            or ''
        ).strip()
        if x_api and x_api == expected:
            return True

    # Session fallback — useful for browser diagnostics by admin users.
    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated:
        return True

    return False


def _unauthorized() -> Response:
    return Response({'error': 'unauthorized'}, status=401)


# ── /api/xero/invoices/ ──────────────────────────────────────────────────────

# Cached for 5 min per (type, days). Avoids hammering Xero when Ledger
# polls every few minutes — invoice data doesn't move between polls.
_INVOICES_CACHE_TTL_SECONDS = 5 * 60


@api_view(['GET'])
@permission_classes([AllowAny])  # Auth handled manually (Bearer / X-API-Key / session)
def xero_invoices_view(request: Request) -> Response:
    """
    Return per-invoice rows from Xero, filtered by type and lookback.

    Query params:
      - type: 'ACCREC' (sales) or 'ACCPAY' (bills). Required.
      - days: integer 1..365. Default 30.

    Response:
      {
        "type": "ACCREC", "days": 30,
        "tenant_id": "...", "tenant_name": "...",
        "count": N,
        "invoices": [ {...}, ... ]
      }
    """
    if not _auth_ok(request):
        return _unauthorized()

    invoice_type = (request.query_params.get('type') or '').strip().upper()
    if invoice_type not in ('ACCREC', 'ACCPAY'):
        return Response(
            {'error': 'invalid_type', 'detail': 'type must be ACCREC or ACCPAY'},
            status=400,
        )

    raw_days = (request.query_params.get('days') or '30').strip()
    try:
        days = int(raw_days)
    except ValueError:
        return Response({'error': 'invalid_days', 'detail': f'days={raw_days!r}'}, status=400)
    if days < 1 or days > 365:
        return Response({'error': 'invalid_days', 'detail': 'days must be 1..365'}, status=400)

    cache_key = f'xero_invoices:{invoice_type}:{days}'
    cached = cache.get(cache_key)
    if cached is not None:
        # Tag the response so consumers know they got a cached payload.
        return Response({**cached, 'cached': True})

    try:
        invoices = xero_adapter.fetch_invoices(invoice_type=invoice_type, lookback_days=days)
    except RuntimeError as exc:
        # No OAuth credential / no tenants connected — actionable error.
        logger.warning('xero_invoices_view: configuration error: %s', exc)
        return Response(
            {'error': 'xero_not_configured', 'detail': str(exc)},
            status=503,
        )
    except Exception as exc:  # noqa: BLE001 — surface upstream failures cleanly
        logger.error('xero_invoices_view: upstream error: %s', exc, exc_info=True)
        return Response(
            {'error': 'xero_upstream_error', 'detail': f'{type(exc).__name__}: {exc}'},
            status=502,
        )

    # Resolve tenant for the response envelope. Fall back to the cached
    # connection if the live call fails — best-effort metadata.
    tenant_id: str | None = None
    tenant_name: str | None = None
    try:
        status = xero_adapter.get_token_status()
        tenant_id = status.get('tenant_id')
        tenant_name = status.get('tenant_name')
    except Exception as exc:  # noqa: BLE001
        logger.warning('xero_invoices_view: tenant resolution failed: %s', exc)

    payload = {
        'type': invoice_type,
        'days': days,
        'tenant_id': tenant_id,
        'tenant_name': tenant_name,
        'count': len(invoices),
        'invoices': invoices,
        'cached': False,
    }
    cache.set(cache_key, payload, _INVOICES_CACHE_TTL_SECONDS)
    return Response(payload)


# ── /api/xero/health ─────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])  # Auth handled manually
def xero_health_view(request: Request) -> Response:
    """
    Lightweight health check for upstream consumers (Ledger).

    Returns connection state without triggering a token refresh — if
    the token is expired, says so honestly so Ledger fails fast and
    Toby gets pinged to re-consent.
    """
    if not _auth_ok(request):
        return _unauthorized()

    try:
        status = xero_adapter.get_token_status()
    except Exception as exc:  # noqa: BLE001
        logger.error('xero_health_view: status read failed: %s', exc, exc_info=True)
        return Response(
            {
                'connected': False,
                'error': f'{type(exc).__name__}: {exc}',
            },
            status=200,  # 200 with connected=false; consumers branch on the flag
        )
    return Response(status)
