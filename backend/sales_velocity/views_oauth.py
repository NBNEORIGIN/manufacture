"""
Admin-only eBay OAuth consent views.

Flow:
    1. Admin visits /admin/oauth/ebay/connect
    2. We build the eBay authorization URL and redirect the browser there.
    3. Admin consents in eBay's UI, eBay redirects to /admin/oauth/ebay/callback
       with a `code` query parameter.
    4. We POST to eBay's token endpoint with grant_type=authorization_code,
       receive a refresh + access token, and upsert the
       `sales_velocity.OAuthCredential(provider='ebay')` row.
    5. Admin sees a success page confirming the consent is stored.

Only staff can access these views. The callback validates `state` to
defend against CSRF.
"""
from __future__ import annotations

import base64
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

from sales_velocity.adapters.ebay import EBAY_OAUTH_URLS, EBAY_SCOPES
from sales_velocity.models import OAuthCredential

logger = logging.getLogger(__name__)


@staff_member_required
@require_GET
def ebay_connect(request: HttpRequest) -> HttpResponse:
    """Kick off the eBay OAuth consent flow."""
    client_id = getattr(settings, 'EBAY_CLIENT_ID', '')
    ru_name = getattr(settings, 'EBAY_RU_NAME', '')
    env = (getattr(settings, 'EBAY_ENVIRONMENT', 'production') or 'production').lower()

    if not client_id or not ru_name:
        return HttpResponseBadRequest(
            'EBAY_CLIENT_ID and EBAY_RU_NAME must be set in the manufacture '
            '.env before the eBay consent flow can run.'
        )

    auth_url = EBAY_OAUTH_URLS[env]['auth']
    state = secrets.token_urlsafe(32)
    request.session['ebay_oauth_state'] = state

    params = {
        'client_id': client_id,
        'response_type': 'code',
        'redirect_uri': ru_name,
        'scope': ' '.join(EBAY_SCOPES),
        'state': state,
    }
    return redirect(f'{auth_url}?{urlencode(params)}')


@staff_member_required
@require_GET
def ebay_callback(request: HttpRequest) -> HttpResponse:
    """Handle eBay's redirect back after consent."""
    code = request.GET.get('code')
    state = request.GET.get('state')
    expected_state = request.session.pop('ebay_oauth_state', None)

    if not code:
        return HttpResponseBadRequest('Missing authorization code in callback.')
    if not state or state != expected_state:
        return HttpResponseBadRequest(
            'OAuth state mismatch — possible CSRF. Restart the flow at '
            '/admin/oauth/ebay/connect.'
        )

    client_id = getattr(settings, 'EBAY_CLIENT_ID', '')
    client_secret = getattr(settings, 'EBAY_CLIENT_SECRET', '')
    ru_name = getattr(settings, 'EBAY_RU_NAME', '')
    env = (getattr(settings, 'EBAY_ENVIRONMENT', 'production') or 'production').lower()
    token_url = EBAY_OAUTH_URLS[env]['token']

    basic = base64.b64encode(f'{client_id}:{client_secret}'.encode()).decode()
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': f'Basic {basic}',
    }
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': ru_name,
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(token_url, headers=headers, data=data)
    except httpx.HTTPError as exc:
        logger.exception('eBay token exchange failed: %s', exc)
        return HttpResponse(
            f'eBay token exchange network error: {exc}', status=502,
        )

    if response.status_code != 200:
        logger.error(
            'eBay token exchange failed %d: %s',
            response.status_code, response.text[:500],
        )
        return HttpResponse(
            f'eBay rejected the authorization code ({response.status_code}). '
            f'Check the redirect URI registration on your eBay dev app.',
            status=502,
        )

    token_data = response.json()
    access_token = token_data.get('access_token')
    refresh_token = token_data.get('refresh_token')
    expires_in = int(token_data.get('expires_in', 7200))
    if not access_token or not refresh_token:
        return HttpResponse(
            'eBay returned a token response missing access_token or refresh_token.',
            status=502,
        )

    cred, created = OAuthCredential.objects.update_or_create(
        provider='ebay',
        defaults={
            'access_token': access_token,
            'refresh_token': refresh_token,
            'access_token_expires_at': django_tz.now() + timedelta(seconds=expires_in),
            'last_refreshed_at': django_tz.now(),
            'scope': ' '.join(EBAY_SCOPES),
        },
    )

    return HttpResponse(
        f'<h1>eBay OAuth connected</h1>'
        f'<p>Credential row {"created" if created else "updated"}.</p>'
        f'<p>Access token expires in {expires_in}s.</p>'
        f'<p>Refresh token stored — subsequent sales-velocity runs will '
        f'refresh in place automatically.</p>'
        f'<p><a href="/admin/sales_velocity/oauthcredential/">View in admin</a></p>',
        content_type='text/html',
    )
