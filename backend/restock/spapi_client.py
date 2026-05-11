"""
SP-API client — calls Amazon directly using LWA credentials.

Auth: LWA (Login with Amazon) OAuth2 — refresh token → access token (1hr TTL)
All SP-API requests use: x-amz-access-token: {access_token}

Regions:
  EU → sellingpartnerapi-eu.amazon.com  (GB, DE, FR)
  NA → sellingpartnerapi-na.amazon.com  (US, CA)
  FE → sellingpartnerapi-fe.amazon.com  (AU)
"""
import gzip
import logging
import os
import time

import requests as _requests

from .schema import (
    MARKETPLACE_TO_REGION, MARKETPLACE_IDS,
    REPORT_TYPE, INVENTORY_REPORT_TYPE,
)

logger = logging.getLogger(__name__)

REGION_HOSTS = {
    'EU': 'sellingpartnerapi-eu.amazon.com',
    'NA': 'sellingpartnerapi-na.amazon.com',
    'FE': 'sellingpartnerapi-fe.amazon.com',
}

CLIENT_ID = os.getenv('AMAZON_CLIENT_ID', '')

# In-memory token cache: {region: (access_token, expires_at)}
_token_cache: dict = {}


def _get_access_token(region: str) -> str:
    """Exchange LWA refresh token for access token (cached, 60s buffer)."""
    cached = _token_cache.get(region)
    if cached and time.time() < cached[1] - 60:
        return cached[0]

    env_key = 'AMAZON_REFRESH_TOKEN_AU' if region == 'FE' else f'AMAZON_REFRESH_TOKEN_{region}'
    refresh_token = os.getenv(env_key, '')
    if not refresh_token:
        raise ValueError(f'Missing {env_key} in environment')

    client_secret = os.getenv('AMAZON_CLIENT_SECRET', '')
    if not client_secret:
        raise ValueError('Missing AMAZON_CLIENT_SECRET in environment')
    if not CLIENT_ID:
        raise ValueError('Missing AMAZON_CLIENT_ID in environment')

    resp = _requests.post(
        'https://api.amazon.com/auth/o2/token',
        json={
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
            'client_id': CLIENT_ID,
            'client_secret': client_secret,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    access_token = data['access_token']
    expires_in = int(data.get('expires_in', 3600))
    _token_cache[region] = (access_token, time.time() + expires_in)
    return access_token


def _spapi_get(region: str, path: str, params: dict | None = None) -> dict:
    host = REGION_HOSTS[region]
    resp = _requests.get(
        f'https://{host}{path}',
        params=params or {},
        headers={'x-amz-access-token': _get_access_token(region), 'Content-Type': 'application/json'},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _spapi_post(region: str, path: str, body: dict) -> dict:
    host = REGION_HOSTS[region]
    resp = _requests.post(
        f'https://{host}{path}',
        json=body,
        headers={'x-amz-access-token': _get_access_token(region), 'Content-Type': 'application/json'},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ── Public interface (matches what views.py expects) ──────────────────────────

def request_report(marketplace: str) -> str:
    """
    Request GET_FBA_INVENTORY_PLANNING_DATA for a marketplace.
    Returns Amazon reportId.
    """
    region = MARKETPLACE_TO_REGION.get(marketplace.upper(), 'EU')
    marketplace_id = MARKETPLACE_IDS.get(marketplace.upper(), '')

    data = _spapi_post(region, '/reports/2021-06-30/reports', {
        'reportType': REPORT_TYPE,
        'marketplaceIds': [marketplace_id],
    })
    return data['reportId']


def request_inventory_report(marketplace: str) -> str:
    """
    Request GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA for a marketplace.

    Returns the full FBA inventory snapshot for the seller account in
    that region — every active FBA SKU, regardless of sales velocity.
    Used as a supplement to the Inventory Planning report so the
    Make List catches slow-movers Amazon's restock algorithm drops.

    Returns Amazon reportId. Use download_report() to fetch the bytes.
    """
    region = MARKETPLACE_TO_REGION.get(marketplace.upper(), 'EU')
    marketplace_id = MARKETPLACE_IDS.get(marketplace.upper(), '')

    data = _spapi_post(region, '/reports/2021-06-30/reports', {
        'reportType': INVENTORY_REPORT_TYPE,
        'marketplaceIds': [marketplace_id],
    })
    return data['reportId']


def download_report(report_id: str, region: str, max_wait: int = 1800) -> bytes:
    """
    Poll until report is DONE, then download and return raw CSV bytes.
    Blocks for up to max_wait seconds (Amazon takes 5-15 min).
    """
    deadline = time.time() + max_wait
    poll_interval = 30

    while time.time() < deadline:
        data = _spapi_get(region, f'/reports/2021-06-30/reports/{report_id}')
        status = data.get('processingStatus', '')
        logger.info('SP-API report %s: processingStatus=%s', report_id, status)

        if status == 'DONE':
            doc_id = data.get('reportDocumentId')
            if not doc_id:
                raise RuntimeError(f'Report {report_id} DONE but no reportDocumentId')

            doc_data = _spapi_get(region, f'/reports/2021-06-30/documents/{doc_id}')
            url = doc_data['url']
            compression = doc_data.get('compressionAlgorithm', '')

            dl_resp = _requests.get(url, timeout=120)
            dl_resp.raise_for_status()
            content = dl_resp.content
            if compression == 'GZIP':
                content = gzip.decompress(content)
            return content

        if status in ('CANCELLED', 'FATAL'):
            raise RuntimeError(f'Report {report_id} failed: status={status}')

        time.sleep(poll_interval)

    raise TimeoutError(f'Report {report_id} not ready after {max_wait}s')
