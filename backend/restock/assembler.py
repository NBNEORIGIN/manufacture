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

# SKUs starting with this prefix are Amazon return-resale listings, not our own
# stock — they should never enter the restock planner.
RETURN_RESALE_PREFIX = 'amzn.gr'


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
    2. Skip D2C exclusions
    3. Fetch margin if available
    4. Run Newsvendor calculation
    5. Bulk-create RestockItem records
    """
    from .models import RestockExclusion
    excluded_m_numbers = set(
        RestockExclusion.objects.values_list('m_number', flat=True)
    )

    items_to_create = []
    resolved = 0
    excluded = 0
    skipped_returns = 0

    for row in raw_rows:
        sku = row.get('merchant_sku', '')
        marketplace = row.get('marketplace', report.marketplace)

        # Amazon posts returned stock back as `amzn.gr.*` SKUs for resale at a
        # lower price — they're not our own inventory and must be ignored.
        if sku.lower().startswith(RETURN_RESALE_PREFIX):
            skipped_returns += 1
            continue

        m_number = resolve_sku(sku, marketplace) or ''
        if m_number:
            resolved += 1
            if m_number in excluded_m_numbers:
                excluded += 1
                continue

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
                units_available=row.get('units_available') or 0,
                units_inbound=row.get('units_inbound') or 0,
                units_reserved=row.get('units_reserved') or 0,
                units_total=row.get('units_total') or 0,
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
            units_reserved=row.get('units_reserved') or 0,
            units_unfulfillable=row.get('units_unfulfillable') or 0,
            days_of_supply_amazon=row.get('days_of_supply_amazon'),
            days_of_supply_total=row.get('days_of_supply_total'),
            sales_last_30d=row.get('sales_last_30d') or 0,
            units_sold_7d=row.get('units_sold_7d') or 0,
            units_sold_30d=row.get('units_sold_30d') or 0,
            units_sold_60d=row.get('units_sold_60d') or 0,
            units_sold_90d=row.get('units_sold_90d') or 0,
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
        'Assembled %d RestockItems for %s (%d resolved, %d D2C-excluded, %d return-resale skipped)',
        len(created), report.marketplace, resolved, excluded, skipped_returns,
    )
    return created


def supplement_with_inventory(
    report: RestockReport,
    inventory_rows: list[dict],
    marketplace: str,
) -> int:
    """
    Add token RestockItem rows for SKUs that are out of stock at FBA
    (units_total == 0) but absent from the Inventory Planning report.

    Why: Amazon's Inventory Planning report (the primary feed) filters
    out very-slow-velocity sold-out items — "no recent sales = don't
    restock". Ivan's Mr Cool vibe metric (review #23) showed ~50
    units/month of revenue being silently leaked because of this.

    The Manage FBA Inventory report lists every FBA SKU regardless of
    velocity, so any SKU here with units_total=0 that isn't in the
    primary report is exactly the cohort we want to surface.

    For each supplementary row we resolve SKU → M-number, check the
    product is active + non-personalised + not on do_not_restock, and
    add a RestockItem with:
      - newsvendor_qty = 1 (token quantity — Ivan adjusts in shipment)
      - confidence    = 0.3 (LOW — no velocity data)
      - alert         = 'out_of_stock'
      - velocity      = 0 (no signal in this report)

    Returns the number of supplementary rows added. Safe to call
    multiple times on the same report; existing SKUs are skipped.
    """
    from .models import RestockExclusion
    from products.models import Product

    excluded_m_numbers = set(
        RestockExclusion.objects.values_list('m_number', flat=True)
    )
    existing_skus = set(
        RestockItem.objects
        .filter(report=report)
        .values_list('merchant_sku', flat=True)
    )
    # Ivan review 25 fix: dedupe at the M-number level, not just SKU.
    # One M-number commonly has 5+ SKU variants (UK/US/CA/AU/EU). If
    # the planning report covers M0001 via one SKU, we don't also want
    # to supplement-add 4 token-1 rows for its other zero-stock SKUs.
    existing_m_numbers = set(
        RestockItem.objects
        .filter(report=report)
        .exclude(m_number='')
        .values_list('m_number', flat=True)
    )

    items_to_create = []
    counters = {
        'added':              0,
        'has_stock':          0,   # skipped: units_total > 0
        'already_present':    0,   # skipped: SKU already in this report
        'm_already_present':  0,   # skipped: M-number already in this report (different SKU)
        'return_resale':      0,   # skipped: amzn.gr* SKU
        'unresolved':         0,   # skipped: SKU → m_number failed
        'product_missing':    0,   # skipped: no active/restockable Product
        'd2c_excluded':       0,   # skipped: m_number on exclusion list
    }

    for row in inventory_rows:
        sku = row.get('merchant_sku', '')
        if not sku:
            continue

        if sku.lower().startswith(RETURN_RESALE_PREFIX):
            counters['return_resale'] += 1
            continue

        if sku in existing_skus:
            counters['already_present'] += 1
            continue

        # We only supplement out-of-stock items. If FBA already has
        # stock and Amazon's algorithm didn't flag the SKU, trust
        # Amazon's "sufficient stock" call.
        if (row.get('units_total') or 0) != 0:
            counters['has_stock'] += 1
            continue

        m_number = resolve_sku(sku, marketplace) or ''
        if not m_number:
            counters['unresolved'] += 1
            continue
        if m_number in excluded_m_numbers:
            counters['d2c_excluded'] += 1
            continue
        if m_number in existing_m_numbers:
            counters['m_already_present'] += 1
            continue

        product = (
            Product.objects
            .filter(
                m_number=m_number,
                active=True,
                do_not_restock=False,
                is_personalised=False,
            )
            .first()
        )
        if not product:
            counters['product_missing'] += 1
            continue

        items_to_create.append(RestockItem(
            report=report,
            marketplace=marketplace,
            merchant_sku=sku,
            asin=row.get('asin', '') or '',
            fnsku=row.get('fnsku', '') or '',
            m_number=m_number,
            product_name=(row.get('product_name', '') or '')[:500],
            units_total=0,
            units_available=row.get('units_available') or 0,
            units_inbound=row.get('units_inbound') or 0,
            units_reserved=row.get('units_reserved') or 0,
            units_unfulfillable=row.get('units_unfulfillable') or 0,
            sales_last_30d=0,
            units_sold_7d=0, units_sold_30d=0,
            units_sold_60d=0, units_sold_90d=0,
            alert='out_of_stock',
            newsvendor_qty=1,
            newsvendor_confidence=0.3,
            newsvendor_notes='supplement: out of stock, no velocity data — token restock 1',
        ))
        counters['added'] += 1
        # Track in-memory so a duplicate row in the same batch doesn't double-add.
        existing_skus.add(sku)
        existing_m_numbers.add(m_number)

    RestockItem.objects.bulk_create(items_to_create)
    logger.info(
        'supplement_with_inventory(%s): added=%d has_stock=%d already_present=%d '
        'm_already_present=%d return_resale=%d unresolved=%d '
        'product_missing=%d d2c_excluded=%d',
        marketplace, counters['added'], counters['has_stock'],
        counters['already_present'], counters['m_already_present'],
        counters['return_resale'], counters['unresolved'],
        counters['product_missing'], counters['d2c_excluded'],
    )
    return counters['added']
