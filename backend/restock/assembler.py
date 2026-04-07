"""
SKU→M-number resolver and restock plan assembler.

Resolution order:
  1. Manufacture's own SKU table (same DB — fast, no HTTP)
  2. Cairn /ami/sku-mapping/lookup endpoint (fallback for SKUs not in local DB)

This avoids cross-DB access while still using Cairn's richer ami_sku_mapping
for SKUs that pre-date the Manufacture seeding.
"""
import logging
import os
import requests
from typing import Optional

from .models import RestockReport, RestockItem
from .newsvendor import NewsvendorInput, calculate_restock_qty

logger = logging.getLogger(__name__)

CAIRN_API_URL = os.getenv('CAIRN_API_URL', 'http://localhost:8765')
CAIRN_API_KEY = os.getenv('CAIRN_API_KEY', '')


def _cairn_headers() -> dict:
    h = {}
    if CAIRN_API_KEY:
        h['x-api-key'] = CAIRN_API_KEY
    return h


def _resolve_sku_local(merchant_sku: str, marketplace: str) -> Optional[str]:
    """Look up M-number from Manufacture's own SKU table."""
    from products.models import SKU
    # Map marketplace code to channel name used in SKU table
    channel_map = {
        'GB': 'UK', 'US': 'US', 'CA': 'CA', 'AU': 'AU',
        'DE': 'DE', 'FR': 'FR',
    }
    channel = channel_map.get(marketplace.upper(), marketplace.upper())
    sku_obj = (
        SKU.objects
        .filter(sku=merchant_sku)
        .select_related('product')
        .first()
    )
    if sku_obj:
        return sku_obj.product.m_number
    # Try without channel filter if channel-specific not found
    sku_obj = (
        SKU.objects
        .filter(sku__iexact=merchant_sku)
        .select_related('product')
        .first()
    )
    return sku_obj.product.m_number if sku_obj else None


def _resolve_sku_cairn(merchant_sku: str, marketplace: str) -> Optional[str]:
    """Fall back to Cairn's ami_sku_mapping via HTTP."""
    try:
        resp = requests.get(
            f'{CAIRN_API_URL}/ami/sku-mapping/lookup',
            headers=_cairn_headers(),
            params={'sku': merchant_sku, 'marketplace': marketplace},
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json().get('m_number')
    except Exception as exc:
        logger.debug('Cairn SKU lookup failed for %s: %s', merchant_sku, exc)
    return None


def resolve_sku(merchant_sku: str, marketplace: str) -> Optional[str]:
    """Resolve a merchant SKU to an M-number. Local-first, Cairn fallback."""
    m = _resolve_sku_local(merchant_sku, marketplace)
    if m:
        return m
    return _resolve_sku_cairn(merchant_sku, marketplace)


def _get_margin(m_number: str) -> Optional[float]:
    """
    Fetch product margin from Manufacture's Product table.
    Returns None if no margin stored — Newsvendor will use the 3:1 fallback.
    """
    # The Product model doesn't yet have a margin field — return None.
    # When margin data is available (future phase), implement this.
    return None


def assemble_restock_plan(
    report: RestockReport,
    raw_rows: list[dict],
    use_newsvendor: bool = True,
) -> list[RestockItem]:
    """
    Build RestockItem records from parsed CSV rows:
    1. Resolve SKU → M-number
    2. Fetch margin if available
    3. Run Newsvendor calculation
    4. Bulk-create RestockItem records
    """
    items_to_create = []
    resolved = 0

    for row in raw_rows:
        sku = row.get('merchant_sku', '')
        marketplace = row.get('marketplace', report.marketplace)

        m_number = resolve_sku(sku, marketplace) or ''
        if m_number:
            resolved += 1

        margin = _get_margin(m_number) if m_number else None
        price = row.get('price') or 5.0  # fallback if price missing in report

        nv_qty = None
        nv_confidence = None
        nv_notes = ''

        if use_newsvendor:
            inp = NewsvendorInput(
                units_sold_30d=row.get('units_sold_30d') or 0,
                days_of_supply_amazon=row.get('days_of_supply_amazon'),
                alert=row.get('alert', ''),
                price=price,
                margin=margin,
            )
            result = calculate_restock_qty(inp)
            nv_qty = result.recommended_qty
            nv_confidence = result.confidence
            nv_notes = result.notes

        ship_date = row.get('amazon_ship_date')

        item = RestockItem(
            report=report,
            marketplace=marketplace,
            merchant_sku=sku,
            asin=row.get('asin', ''),
            fnsku=row.get('fnsku', ''),
            m_number=m_number,
            product_name=row.get('product_name', '')[:500],
            units_total=row.get('units_total') or 0,
            units_available=row.get('units_available') or 0,
            units_inbound=row.get('units_inbound') or 0,
            days_of_supply_amazon=row.get('days_of_supply_amazon'),
            days_of_supply_total=row.get('days_of_supply_total'),
            sales_last_30d=row.get('sales_last_30d') or 0,
            units_sold_30d=row.get('units_sold_30d') or 0,
            alert=row.get('alert', ''),
            amazon_recommended_qty=row.get('amazon_recommended_qty'),
            amazon_ship_date=ship_date,
            newsvendor_qty=nv_qty,
            newsvendor_confidence=nv_confidence,
            newsvendor_notes=nv_notes,
        )
        items_to_create.append(item)

    created = RestockItem.objects.bulk_create(items_to_create)
    logger.info(
        'Assembled %d RestockItems for %s (%d SKUs resolved to M-numbers)',
        len(created), report.marketplace, resolved,
    )
    return created
