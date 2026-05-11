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

from .schema import MARKETPLACE_TO_REGION, MARKETPLACE_IDS, REPORT_TYPE

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


def fetch_inventory_summaries(marketplace: str) -> list[dict]:
    """
    Fetch the FBA inventory summary for a marketplace via the direct
    /fba/inventory/v1/summaries endpoint.

    Returns one normalised dict per SKU. Includes SKUs with zero stock,
    which is the whole point — they're what the Inventory Planning
    report silently drops and Ivan's Mr Cool vibe metric flagged.

    Why not GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA report? Tried it
    2026-05-11; Amazon returns processingStatus=FATAL on every submit
    against our GB account (no usable error metadata). The direct
    /summaries endpoint works first try, returns paginated JSON in
    real-time (no 5-15 min queue wait), and exposes the same data we
    need.

    Pagination: 50 SKUs per page via nextToken. Typical seller account
    is a few hundred to a few thousand SKUs, so 10-50 round trips per
    marketplace. Each round trip is ~1 second. Done synchronously.
    """
    region = MARKETPLACE_TO_REGION.get(marketplace.upper(), 'EU')
    marketplace_id = MARKETPLACE_IDS.get(marketplace.upper(), '')
    if not marketplace_id:
        raise ValueError(f'Unknown marketplace: {marketplace}')

    rows: list[dict] = []
    next_token: str | None = None
    pages = 0
    # Amazon's FBA Inventory API rate limit: 1 request/sec burst 1.
    # Sleep between page fetches so we don't 429 ourselves. Retry on
    # 429 with the Retry-After header value (or 5s default) and an
    # extra second of safety margin.
    inter_page_sleep_s = 1.0
    while True:
        params: dict[str, str] = {
            'details': 'true',
            'granularityType': 'Marketplace',
            'granularityId': marketplace_id,
            'marketplaceIds': marketplace_id,
        }
        if next_token:
            params['nextToken'] = next_token

        attempt = 0
        while True:
            try:
                data = _spapi_get(region, '/fba/inventory/v1/summaries', params=params)
                break
            except _requests.HTTPError as exc:
                resp = getattr(exc, 'response', None)
                if resp is not None and resp.status_code == 429 and attempt < 3:
                    try:
                        retry_after = int(resp.headers.get('Retry-After', '5'))
                    except (ValueError, TypeError):
                        retry_after = 5
                    logger.warning(
                        'fetch_inventory_summaries(%s): 429 on page %d (attempt %d) '
                        '— sleeping %ds', marketplace, pages + 1, attempt + 1,
                        retry_after + 1,
                    )
                    time.sleep(retry_after + 1)
                    attempt += 1
                    continue
                raise
        pages += 1

        payload = data.get('payload') or {}
        summaries = payload.get('inventorySummaries') or []
        for s in summaries:
            details = s.get('inventoryDetails') or {}
            reserved = (details.get('reservedQuantity') or {}).get(
                'totalReservedQuantity', 0,
            )
            unfulfillable = (details.get('unfulfillableQuantity') or {}).get(
                'totalUnfulfillableQuantity', 0,
            )
            inbound = (
                (details.get('inboundWorkingQuantity') or 0)
                + (details.get('inboundShippedQuantity') or 0)
                + (details.get('inboundReceivingQuantity') or 0)
            )
            rows.append({
                'merchant_sku':         s.get('sellerSku') or '',
                'fnsku':                s.get('fnSku') or '',
                'asin':                 s.get('asin') or '',
                'product_name':         (s.get('productName') or '')[:500],
                'units_total':          int(s.get('totalQuantity') or 0),
                'units_available':      int(details.get('fulfillableQuantity') or 0),
                'units_inbound':        int(inbound),
                'units_reserved':       int(reserved),
                'units_unfulfillable':  int(unfulfillable),
            })

        next_token = (data.get('pagination') or {}).get('nextToken')
        if not next_token:
            break
        # Respect the 1 req/sec rate limit between pages.
        time.sleep(inter_page_sleep_s)

    logger.info(
        'fetch_inventory_summaries(%s): %d rows over %d pages',
        marketplace, len(rows), pages,
    )
    return rows


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
