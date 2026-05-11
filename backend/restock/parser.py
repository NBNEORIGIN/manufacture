"""
FBA Manage Inventory Health TSV parser.
Report type: GET_FBA_INVENTORY_PLANNING_DATA

The SP-API returns a tab-separated file. The marketplace column contains
Amazon marketplace codes (UK, US, CA, AU, DE, FR). Each report is
marketplace-specific (requested per marketplace-id), but we still filter
by the requested marketplace code after parsing.
"""
import csv
import io
from datetime import date
from typing import Optional

from .schema import (
    COLUMN_MAP, COUNTRY_TO_MARKETPLACE, MARKETPLACE_CODE_MAP,
    INVENTORY_COLUMN_MAP,
)


def _safe_int(v) -> Optional[int]:
    if v is None or str(v).strip() == '':
        return None
    try:
        return int(float(str(v).replace(',', '')))
    except (ValueError, TypeError):
        return None


def _safe_float(v) -> Optional[float]:
    if v is None or str(v).strip() == '':
        return None
    try:
        return float(str(v).replace(',', ''))
    except (ValueError, TypeError):
        return None


def _parse_date(v) -> Optional[date]:
    """Handle YYYY-MM-DD, DD/MM/YYYY and MM/DD/YYYY."""
    if not v or str(v).strip() == '':
        return None
    s = str(v).strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d/%m/%Y %H:%M:%S'):
        try:
            from datetime import datetime
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _normalise_marketplace(raw: str) -> str:
    """
    Convert marketplace code from the report to our canonical code.
    Report uses 'UK' for Great Britain; we use 'GB'.
    Falls back to country-name lookup for manual uploads.
    """
    code = raw.strip().upper()
    if code in MARKETPLACE_CODE_MAP:
        return MARKETPLACE_CODE_MAP[code]
    # Try country-name lookup (for manual CSV uploads using old format)
    key = raw.strip().lower()
    if key in COUNTRY_TO_MARKETPLACE:
        return COUNTRY_TO_MARKETPLACE[key]
    return code[:2]


def _derive_alert(units_available: int, days_of_supply: Optional[float],
                  amazon_recommended_qty: Optional[int]) -> str:
    """
    Derive our internal alert classification from inventory state.
    The SP-API alert column contains selling-velocity alerts (Low traffic,
    Low conversion) not restock alerts. We derive our own:
      - out_of_stock: 0 units available
      - reorder_now: <30 days supply with a positive restock recommendation
      - blank: no action required
    """
    if units_available == 0:
        return 'out_of_stock'
    if days_of_supply is not None and days_of_supply < 30:
        if amazon_recommended_qty and amazon_recommended_qty > 0:
            return 'reorder_now'
    return ''


def parse_restock_csv(
    content: bytes,
    filter_marketplace: Optional[str] = None,
) -> list[dict]:
    """
    Parse raw TSV bytes from GET_FBA_INVENTORY_PLANNING_DATA report.

    Returns a list of dicts with normalised keys. Filters to
    filter_marketplace if provided (e.g. 'GB').
    """
    text = content.decode('utf-8', errors='replace')
    # Report is tab-separated
    reader = csv.DictReader(io.StringIO(text), delimiter='\t')

    rows = []
    for raw_row in reader:
        # Build normalised row using COLUMN_MAP
        row: dict = {}
        for csv_col, key in COLUMN_MAP.items():
            row[key] = raw_row.get(csv_col, '').strip()

        # Skip empty or header-like rows
        sku = row.get('merchant_sku', '')
        if not sku or sku.upper() in ('SKU', 'MERCHANT SKU', 'ABC123'):
            continue

        # Normalise marketplace (UK → GB etc.)
        row['marketplace'] = _normalise_marketplace(row.get('marketplace', ''))

        if filter_marketplace and row['marketplace'] != filter_marketplace.upper():
            continue

        # Type coercions
        row['price'] = _safe_float(row.get('price'))
        row['sales_last_30d'] = _safe_float(row.get('sales_last_30d'))
        row['units_sold_7d'] = _safe_int(row.get('units_sold_7d')) or 0
        row['units_sold_30d'] = _safe_int(row.get('units_sold_30d')) or 0
        row['units_sold_60d'] = _safe_int(row.get('units_sold_60d')) or 0
        row['units_sold_90d'] = _safe_int(row.get('units_sold_90d')) or 0
        row['units_available'] = _safe_int(row.get('units_available')) or 0
        row['units_inbound'] = _safe_int(row.get('units_inbound')) or 0
        row['units_reserved'] = _safe_int(row.get('units_reserved')) or 0
        row['units_unfulfillable'] = _safe_int(row.get('units_unfulfillable')) or 0
        # Use Amazon's own FBA total (available + inbound + reserved + researching)
        # if present; otherwise fall back to the sum we can compute.
        fba_total = _safe_int(row.get('units_fba_total'))
        if fba_total is not None:
            row['units_total'] = fba_total
        else:
            row['units_total'] = (
                row['units_available'] + row['units_inbound']
                + row['units_reserved']
            )
        row['days_of_supply_amazon'] = _safe_float(row.get('days_of_supply_amazon'))
        row['days_of_supply_total'] = _safe_float(row.get('days_of_supply_total'))
        row['amazon_recommended_qty'] = _safe_int(row.get('amazon_recommended_qty'))
        row['amazon_ship_date'] = _parse_date(row.get('amazon_ship_date'))

        # Derive our alert classification (not Amazon's velocity alert)
        row['alert'] = _derive_alert(
            row['units_available'],
            row['days_of_supply_amazon'],
            row['amazon_recommended_qty'],
        )

        rows.append(row)

    return rows


def parse_fba_inventory_csv(content: bytes) -> list[dict]:
    """
    Parse raw TSV bytes from the Manage FBA Inventory report
    (GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA).

    Returns one normalised row per SKU with current inventory only —
    no sales velocity. Used as a supplement to the primary Restock
    Inventory Planning report: any SKU here with units_total=0 that
    isn't in the planning report is a slow-mover Amazon's algorithm
    silently dropped (Ivan #23 finding).

    Marketplace is not a per-row column in this report; it's
    seller-account-level. Caller filters by which marketplace is
    being supplemented.
    """
    text = content.decode('utf-8', errors='replace')
    reader = csv.DictReader(io.StringIO(text), delimiter='\t')

    rows: list[dict] = []
    for raw_row in reader:
        row: dict = {}
        for csv_col, key in INVENTORY_COLUMN_MAP.items():
            row[key] = raw_row.get(csv_col, '').strip()

        sku = row.get('merchant_sku', '')
        if not sku or sku.upper() == 'SKU':
            continue

        row['units_total']              = _safe_int(row.get('units_total')) or 0
        row['units_available']          = _safe_int(row.get('units_available')) or 0
        row['units_reserved']           = _safe_int(row.get('units_reserved')) or 0
        row['units_unfulfillable']      = _safe_int(row.get('units_unfulfillable')) or 0
        row['units_warehouse']          = _safe_int(row.get('units_warehouse')) or 0
        row['units_inbound_working']    = _safe_int(row.get('units_inbound_working')) or 0
        row['units_inbound_shipped']    = _safe_int(row.get('units_inbound_shipped')) or 0
        row['units_inbound_receiving']  = _safe_int(row.get('units_inbound_receiving')) or 0
        row['units_researching']        = _safe_int(row.get('units_researching')) or 0
        # Roll inbound stages into one number for the RestockItem schema.
        row['units_inbound'] = (
            row['units_inbound_working']
            + row['units_inbound_shipped']
            + row['units_inbound_receiving']
        )
        row['price'] = _safe_float(row.get('price'))

        rows.append(row)

    return rows
