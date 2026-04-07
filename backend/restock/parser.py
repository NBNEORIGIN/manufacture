"""
FBA Manage Inventory Health CSV parser.
Report type: GET_FBA_INVENTORY_PLANNING_DATA

The CSV contains ALL marketplaces in one file. Filter by marketplace code
if a specific marketplace is requested.
"""
import csv
import io
from datetime import date
from typing import Optional

from .schema import COLUMN_MAP, COUNTRY_TO_MARKETPLACE


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
    """Handle DD/MM/YYYY and MM/DD/YYYY and YYYY-MM-DD."""
    if not v or str(v).strip() == '':
        return None
    s = str(v).strip()
    for fmt in ('%d/%m/%Y', '%m/%d/%Y', '%Y-%m-%d', '%d/%m/%Y %H:%M:%S'):
        try:
            from datetime import datetime
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _normalise_marketplace(raw: str) -> str:
    """Convert 'United Kingdom' or 'GB' or 'gb' → 'GB'."""
    key = raw.strip().lower()
    return COUNTRY_TO_MARKETPLACE.get(key, raw.strip().upper()[:2])


def parse_restock_csv(
    content: bytes,
    filter_marketplace: Optional[str] = None,
) -> list[dict]:
    """
    Parse raw CSV bytes from GET_FBA_INVENTORY_PLANNING_DATA report.

    Returns a list of dicts with normalised keys per COLUMN_MAP.
    Filters to filter_marketplace if provided (e.g. 'GB').
    """
    text = content.decode('utf-8', errors='replace')
    reader = csv.DictReader(io.StringIO(text))

    rows = []
    for raw_row in reader:
        # Build normalised row using COLUMN_MAP
        row: dict = {}
        for csv_col, key in COLUMN_MAP.items():
            row[key] = raw_row.get(csv_col, '').strip()

        # Skip header-like or empty rows
        sku = row.get('merchant_sku', '')
        if not sku or sku.upper() in ('MERCHANT SKU', 'ABC123'):
            continue

        # Normalise marketplace
        raw_country = row.get('marketplace', '')
        row['marketplace'] = _normalise_marketplace(raw_country)

        if filter_marketplace and row['marketplace'] != filter_marketplace.upper():
            continue

        # Coerce types — blank → None, not 0
        row['price'] = _safe_float(row.get('price'))
        row['sales_last_30d'] = _safe_float(row.get('sales_last_30d'))
        row['units_sold_30d'] = _safe_int(row.get('units_sold_30d')) or 0
        row['units_total'] = _safe_int(row.get('units_total')) or 0
        row['units_inbound'] = _safe_int(row.get('units_inbound')) or 0
        row['units_available'] = _safe_int(row.get('units_available')) or 0
        row['days_of_supply_amazon'] = _safe_float(row.get('days_of_supply_amazon'))
        row['days_of_supply_total'] = _safe_float(row.get('days_of_supply_total'))
        row['amazon_recommended_qty'] = _safe_int(row.get('amazon_recommended_qty'))
        row['amazon_ship_date'] = _parse_date(row.get('amazon_ship_date'))
        row['alert'] = row.get('alert', '').strip().lower().replace(' ', '_')

        rows.append(row)

    return rows
