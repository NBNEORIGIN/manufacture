"""
FBA Manage Inventory Health report schema.
SP-API report type: GET_FBA_INVENTORY_PLANNING_DATA

Actual format returned by SP-API: tab-separated with lowercase-hyphenated headers.
"""

REPORT_TYPE = 'GET_FBA_INVENTORY_PLANNING_DATA'

# Maps actual TSV column name → our internal key
COLUMN_MAP = {
    'sku': 'merchant_sku',
    'fnsku': 'fnsku',
    'asin': 'asin',
    'product-name': 'product_name',
    'marketplace': 'marketplace',
    'your-price': 'price',
    'sales-shipped-last-30-days': 'sales_last_30d',
    'units-shipped-t30': 'units_sold_30d',
    'available': 'units_available',
    'inbound-quantity': 'units_inbound',
    'days-of-supply': 'days_of_supply_amazon',
    'Total Days of Supply (including units from open shipments)': 'days_of_supply_total',
    'alert': 'amazon_alert_raw',
    'Recommended ship-in quantity': 'amazon_recommended_qty',
    'Recommended ship-in date': 'amazon_ship_date',
    'storage-type': 'unit_storage_size',
    'Total Reserved Quantity': 'units_reserved',
    'unfulfillable-quantity': 'units_unfulfillable',
    'Inventory Supply at FBA': 'units_fba_total',
    'Reserved FC Transfer': 'reserved_fc_transfer',
    'Reserved FC Processing': 'reserved_fc_processing',
    'Reserved Customer Order': 'reserved_customer_order',
}

# Marketplace code normalisation — the report uses 'UK' not 'GB'
MARKETPLACE_CODE_MAP = {
    'UK': 'GB',
    'GB': 'GB',
    'US': 'US',
    'CA': 'CA',
    'AU': 'AU',
    'DE': 'DE',
    'FR': 'FR',
}

# Country name → marketplace code (for manual upload CSV compatibility)
COUNTRY_TO_MARKETPLACE = {
    'united kingdom': 'GB',
    'uk': 'GB',
    'gb': 'GB',
    'united states': 'US',
    'us': 'US',
    'usa': 'US',
    'canada': 'CA',
    'ca': 'CA',
    'australia': 'AU',
    'au': 'AU',
    'germany': 'DE',
    'de': 'DE',
    'france': 'FR',
    'fr': 'FR',
}

MARKETPLACE_TO_REGION = {
    'GB': 'EU',
    'DE': 'EU',
    'FR': 'EU',
    'US': 'NA',
    'CA': 'NA',
    'AU': 'FE',
}

MARKETPLACE_IDS = {
    'GB': 'A1F83G8C2ARO7P',
    'US': 'ATVPDKIKX0DER',
    'CA': 'A2EUQ1WTGCTBG2',
    'AU': 'A39IBJ37TRP1C6',
    'DE': 'A1PA6795UKMFR9',
    'FR': 'A13V1IB3VIYZZH',
}
