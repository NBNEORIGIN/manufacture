"""
Admin-only Xero OAuth consent views.

Flow identical to eBay:
    1. Admin visits /admin/oauth/xero/connect
    2. Redirect to Xero authorization URL
    3. Xero redirects to /admin/oauth/xero/callback with code
    4. Exchange code for tokens, store in OAuthCredential(provider='xero')
"""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.utils import timezone as django_tz
from django.views.decorators.http import require_GET

from sales_velocity.adapters.xero import XERO_AUTH_URL, XERO_TOKEN_URL, XERO_SCOPES
from sales_velocity.models import OAuthCredential

logger = logging.getLogger(__name__)


@staff_member_required
@require_GET
def xero_connect(request: HttpRequest) -> HttpResponse:
    """Kick off the Xero OAuth consent flow."""
    client_id = getattr(settings, 'XERO_CLIENT_ID', '')
    if not client_id:
        return HttpResponseBadRequest(
            'XERO_CLIENT_ID must be set in the manufacture .env before the Xero consent flow can run.'
        )

    state = secrets.token_urlsafe(32)
    request.session['xero_oauth_state'] = state

    redirect_uri = request.build_absolute_uri('/admin/oauth/xero/callback')

    params = {
        'response_type': 'code',
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'scope': ' '.join(XERO_SCOPES),
        'state': state,
    }
    return redirect(f'{XERO_AUTH_URL}?{urlencode(params)}')


@staff_member_required
@require_GET
def xero_callback(request: HttpRequest) -> HttpResponse:
    """Handle Xero's redirect back after consent."""
    code = request.GET.get('code')
    state = request.GET.get('state')
    expected_state = request.session.pop('xero_oauth_state', None)

    if not code:
        return HttpResponseBadRequest('Missing authorization code in callback.')
    if not state or state != expected_state:
        return HttpResponseBadRequest(
            'OAuth state mismatch — possible CSRF. Restart the flow at /admin/oauth/xero/connect.'
        )

    client_id = getattr(settings, 'XERO_CLIENT_ID', '')
    client_secret = getattr(settings, 'XERO_CLIENT_SECRET', '')
    redirect_uri = request.build_absolute_uri('/admin/oauth/xero/callback')

    try:
        resp = httpx.post(
            XERO_TOKEN_URL,
            data={
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': redirect_uri,
                'client_id': client_id,
                'client_secret': client_secret,
            },
            timeout=30,
        )
    except httpx.HTTPError as exc:
        logger.exception('Xero token exchange failed: %s', exc)
        return HttpResponse(f'Xero token exchange error: {exc}', status=502)

    if resp.status_code != 200:
        logger.error('Xero token exchange %d: %s', resp.status_code, resp.text[:500])
        return HttpResponse(
            f'Xero rejected the authorization code ({resp.status_code}). '
            f'Check the redirect URI registration in your Xero app.',
            status=502,
        )

    token_data = resp.json()
    access_token = token_data.get('access_token')
    refresh_token = token_data.get('refresh_token')
    expires_in = int(token_data.get('expires_in', 1800))

    if not access_token or not refresh_token:
        return HttpResponse('Xero returned incomplete token data.', status=502)

    cred, created = OAuthCredential.objects.update_or_create(
        provider='xero',
        defaults={
            'access_token': access_token,
            'refresh_token': refresh_token,
            'access_token_expires_at': django_tz.now() + timedelta(seconds=expires_in),
            'last_refreshed_at': django_tz.now(),
            'scope': ' '.join(XERO_SCOPES),
        },
    )

    return HttpResponse(
        f'<h1>Xero OAuth connected</h1>'
        f'<p>Credential row {"created" if created else "updated"}.</p>'
        f'<p>Access token expires in {expires_in}s.</p>'
        f'<p>Refresh token stored — B2B revenue will now pull automatically from Xero invoices.</p>',
        content_type='text/html',
    )
