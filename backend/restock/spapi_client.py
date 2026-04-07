"""
Thin HTTP adapter — delegates SP-API report downloads to Cairn AMI.

Architecture rule: Manufacture has no Amazon API credentials.
All SP-API calls go via Cairn's /ami/spapi/report/* endpoints.
"""
import os
import time
import logging
import requests

from .schema import MARKETPLACE_TO_REGION, MARKETPLACE_IDS, REPORT_TYPE

logger = logging.getLogger(__name__)

CAIRN_API_URL = os.getenv('CAIRN_API_URL', 'http://localhost:8765')
CAIRN_API_KEY = os.getenv('CAIRN_API_KEY', '')


def _headers() -> dict:
    h = {'Content-Type': 'application/json'}
    if CAIRN_API_KEY:
        h['x-api-key'] = CAIRN_API_KEY
    return h


def request_report(marketplace: str) -> str:
    """
    Ask Cairn to request a GET_FBA_INVENTORY_PLANNING_DATA report for a marketplace.
    Returns Amazon reportId.
    """
    region = MARKETPLACE_TO_REGION.get(marketplace.upper(), 'EU')
    marketplace_id = MARKETPLACE_IDS.get(marketplace.upper(), '')

    resp = requests.post(
        f'{CAIRN_API_URL}/ami/spapi/report/request',
        headers=_headers(),
        json={
            'report_type': REPORT_TYPE,
            'region': region,
            'marketplace_ids': [marketplace_id],
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data['report_id']


def get_report_status(report_id: str, region: str) -> dict:
    """
    Check status of a previously requested report.
    Returns {processing_status, document_id}.
    """
    resp = requests.get(
        f'{CAIRN_API_URL}/ami/spapi/report/{report_id}/status',
        headers=_headers(),
        params={'region': region},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def download_report(report_id: str, region: str, max_wait: int = 1800) -> bytes:
    """
    Poll until report is DONE, then download and return raw CSV bytes.
    Blocks for up to max_wait seconds (Amazon takes 5-15 min).
    """
    deadline = time.time() + max_wait
    poll_interval = 30

    while time.time() < deadline:
        status_data = get_report_status(report_id, region)
        processing_status = status_data.get('processing_status', '')
        logger.info(
            'Restock report %s: processing_status=%s', report_id, processing_status
        )

        if processing_status == 'DONE':
            resp = requests.get(
                f'{CAIRN_API_URL}/ami/spapi/report/{report_id}/download',
                headers=_headers(),
                params={'region': region},
                timeout=120,
            )
            resp.raise_for_status()
            return resp.content

        if processing_status in ('CANCELLED', 'FATAL'):
            raise RuntimeError(
                f'Report {report_id} failed with status: {processing_status}'
            )

        time.sleep(poll_interval)

    raise TimeoutError(f'Report {report_id} not ready after {max_wait}s')
