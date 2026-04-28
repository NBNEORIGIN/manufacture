"""
CSV/TSV report parsers for Amazon Seller Central reports.

Each parser returns a list of dicts with normalised field names.
Parsers handle format detection, column mapping, and data cleaning.
"""
import csv
import io
import re


def detect_delimiter(content: str) -> str:
    first_line = content.split('\n')[0]
    if '\t' in first_line:
        return '\t'
    return ','


def clean_int(val):
    if not val:
        return 0
    val = str(val).strip().replace(',', '')
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 0


def clean_str(val):
    return str(val).strip() if val else ''


def parse_fba_inventory(content: str) -> dict:
    """
    Parse FBA Manage Inventory report.
    Expected columns: sku, asin, fnsku, product-name, condition,
                      your-price, afn-fulfillable-quantity, ...
    Key field: afn-fulfillable-quantity = units at Amazon warehouse
    """
    delimiter = detect_delimiter(content)
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)

    items = []
    errors = []

    for i, row in enumerate(reader):
        sku = clean_str(row.get('sku') or row.get('seller-sku') or row.get('Seller SKU', ''))
        if not sku:
            continue

        fba_qty = clean_int(
            row.get('afn-fulfillable-quantity')
            or row.get('Fulfillable Quantity')
            or row.get('afn-warehouse-quantity')
            or 0
        )
        asin = clean_str(row.get('asin') or row.get('ASIN', ''))
        fnsku = clean_str(row.get('fnsku') or row.get('FNSKU', ''))

        items.append({
            'sku': sku,
            'asin': asin,
            'fnsku': fnsku,
            'fba_quantity': fba_qty,
        })

    return {'items': items, 'errors': errors, 'report_type': 'fba_inventory'}


def parse_sales_traffic(content: str) -> dict:
    """
    Parse Business Reports - Sales & Traffic by SKU.
    Expected columns: (Parent) ASIN, (Child) ASIN, Title, SKU,
                      Sessions, Units Ordered, ...
    Key field: Units Ordered = sales volume for velocity calculation
    """
    delimiter = detect_delimiter(content)
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)

    items = []
    errors = []

    for row in reader:
        sku = clean_str(
            row.get('sku') or row.get('SKU')
            or row.get('(Child) ASIN') or ''
        )
        if not sku:
            continue

        units = clean_int(
            row.get('Units Ordered')
            or row.get('units-ordered')
            or row.get('Total Order Items')
            or 0
        )
        sessions = clean_int(row.get('Sessions') or row.get('sessions') or 0)

        items.append({
            'sku': sku,
            'units_ordered': units,
            'sessions': sessions,
        })

    return {'items': items, 'errors': errors, 'report_type': 'sales_traffic'}


def parse_restock_inventory(content: str) -> dict:
    """
    Parse Restock Inventory report.
    Expected columns: SKU, ASIN, Product Name, Available,
                      Recommended restock qty, Recommended ship date, ...
    """
    delimiter = detect_delimiter(content)
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)

    items = []
    errors = []

    for row in reader:
        sku = clean_str(
            row.get('SKU') or row.get('sku')
            or row.get('Merchant SKU') or ''
        )
        if not sku:
            continue

        restock_qty = clean_int(
            row.get('Recommended restock qty')
            or row.get('Recommended Order Quantity')
            or row.get('recommended-restock-qty')
            or 0
        )
        available = clean_int(
            row.get('Available') or row.get('available')
            or row.get('afn-fulfillable-quantity') or 0
        )
        asin = clean_str(row.get('ASIN') or row.get('asin') or '')

        items.append({
            'sku': sku,
            'asin': asin,
            'available': available,
            'restock_quantity': restock_qty,
        })

    return {'items': items, 'errors': errors, 'report_type': 'restock'}


def parse_zenstores(content: str) -> dict:
    """
    Parse Zenstores Order Export CSV.
    Columns: Order ID, Status, Date, Channel, First name, Last name,
             ..., Lineitem SKU, ..., Lineitem quantity, ..., Flags, ...
    Key fields: Order ID, Lineitem SKU, Lineitem quantity, Flags, Channel,
                Date, First name + Last name, Lineitem name
    """
    delimiter = detect_delimiter(content)
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)

    items = []
    errors = []

    for row in reader:
        order_id = clean_str(row.get('Order ID', ''))
        sku = clean_str(row.get('Lineitem SKU', ''))
        if not order_id or not sku:
            continue

        quantity = clean_int(row.get('Lineitem quantity', 1)) or 1
        flags = clean_str(row.get('Flags', ''))
        channel = clean_str(row.get('Channel', ''))
        date_str = clean_str(row.get('Date', ''))
        first = clean_str(row.get('First name', ''))
        last = clean_str(row.get('Last name', ''))
        description = clean_str(row.get('Lineitem name', ''))
        # Zenstores order status — used downstream to detect orders that
        # have already shipped externally (MCF / hand-shipped) so we don't
        # double-handle them in the d2c queue.
        zen_status = clean_str(row.get('Status', ''))
        shipped_date = clean_str(row.get('Shipped date', ''))

        items.append({
            'order_id': order_id,
            'sku': sku,
            'quantity': quantity,
            'flags': flags,
            'channel': channel,
            'order_date': date_str,
            'customer_name': f'{first} {last}'.strip(),
            'description': description,
            'zen_status': zen_status,
            'shipped_date': shipped_date,
        })

    return {'items': items, 'errors': errors, 'report_type': 'zenstores'}


def detect_report_type(content: str) -> str | None:
    first_line = content.split('\n')[0].lower()
    if 'afn-fulfillable-quantity' in first_line or 'fulfillable quantity' in first_line:
        return 'fba_inventory'
    if 'units ordered' in first_line or 'units-ordered' in first_line:
        return 'sales_traffic'
    if 'recommended restock' in first_line or 'recommended-restock' in first_line:
        return 'restock'
    if 'lineitem sku' in first_line and 'order id' in first_line:
        return 'zenstores'
    return None


PARSERS = {
    'fba_inventory': parse_fba_inventory,
    'sales_traffic': parse_sales_traffic,
    'restock': parse_restock_inventory,
    'zenstores': parse_zenstores,
}
