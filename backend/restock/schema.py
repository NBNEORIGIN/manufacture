"""
FBA Manage Inventory Health report schema.
SP-API report type: GET_FBA_INVENTORY_PLANNING_DATA
"""

REPORT_TYPE = 'GET_FBA_INVENTORY_PLANNING_DATA'

COLUMN_MAP = {
    'Country': 'marketplace',
    'Product Name': 'product_name',
    'FNSKU': 'fnsku',
    'Merchant SKU': 'merchant_sku',
    'ASIN': 'asin',
    'Price': 'price',
    'Sales last 30 days': 'sales_last_30d',
    'Units Sold Last 30 Days': 'units_sold_30d',
    'Total Units': 'units_total',
    'Inbound': 'units_inbound',
    'Available': 'units_available',
    'Days of Supply at Amazon Fulfillment Network': 'days_of_supply_amazon',
    'Total Days of Supply (including units from open shipments)': 'days_of_supply_total',
    'Alert': 'alert',
    'Recommended replenishment qty': 'amazon_recommended_qty',
    'Recommended ship date': 'amazon_ship_date',
    'Unit storage size': 'unit_storage_size',
}

# Country name → marketplace code normalisation
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
