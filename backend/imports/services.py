"""
Import service: applies parsed report data to the database.
All stock updates are staged (preview mode) and require confirmation.
"""
from products.models import SKU
from stock.models import StockLevel


def _resolve_sku_to_product(sku_value: str):
    """Resolve a marketplace SKU to a Product via the SKU table."""
    try:
        sku_obj = SKU.objects.select_related('product').filter(sku=sku_value).first()
        if sku_obj:
            return sku_obj.product
    except Exception:
        pass
    return None


def apply_fba_inventory(parsed: dict, preview_only=True) -> dict:
    """
    Apply FBA inventory report: updates fba_stock on StockLevel.
    Returns preview of changes.
    """
    changes = []
    skipped = []

    for item in parsed['items']:
        product = _resolve_sku_to_product(item['sku'])
        if not product:
            skipped.append({'sku': item['sku'], 'reason': 'Unknown SKU'})
            continue

        try:
            stock = StockLevel.objects.get(product=product)
        except StockLevel.DoesNotExist:
            skipped.append({'sku': item['sku'], 'reason': f'No stock record for {product.m_number}'})
            continue

        old_fba = stock.fba_stock
        new_fba = item['fba_quantity']

        if old_fba != new_fba:
            changes.append({
                'm_number': product.m_number,
                'sku': item['sku'],
                'field': 'fba_stock',
                'old': old_fba,
                'new': new_fba,
            })
            if not preview_only:
                stock.fba_stock = new_fba
                stock.save(update_fields=['fba_stock', 'updated_at'])

    return {
        'report_type': 'fba_inventory',
        'preview': preview_only,
        'changes': changes,
        'skipped': skipped,
        'total_items': len(parsed['items']),
    }


def apply_sales_traffic(parsed: dict, preview_only=True) -> dict:
    """
    Apply sales report: accumulates units_ordered per M-number.
    Updates sixty_day_sales on StockLevel.
    """
    # Aggregate sales by product
    product_sales = {}
    skipped = []

    for item in parsed['items']:
        product = _resolve_sku_to_product(item['sku'])
        if not product:
            skipped.append({'sku': item['sku'], 'reason': 'Unknown SKU'})
            continue

        if product.m_number not in product_sales:
            product_sales[product.m_number] = {'product': product, 'total': 0}
        product_sales[product.m_number]['total'] += item['units_ordered']

    changes = []
    for m_number, data in product_sales.items():
        try:
            stock = StockLevel.objects.get(product=data['product'])
        except StockLevel.DoesNotExist:
            continue

        old_val = stock.sixty_day_sales
        new_val = data['total']

        if old_val != new_val:
            changes.append({
                'm_number': m_number,
                'field': 'sixty_day_sales',
                'old': old_val,
                'new': new_val,
            })
            if not preview_only:
                stock.sixty_day_sales = new_val
                stock.recalculate_deficit()

    return {
        'report_type': 'sales_traffic',
        'preview': preview_only,
        'changes': changes,
        'skipped': skipped,
        'total_items': len(parsed['items']),
    }


def apply_restock_inventory(parsed: dict, preview_only=True) -> dict:
    """
    Apply restock report: shows Amazon's recommended restock quantities.
    Informational — updates fba_stock from available field.
    """
    changes = []
    skipped = []

    for item in parsed['items']:
        product = _resolve_sku_to_product(item['sku'])
        if not product:
            skipped.append({'sku': item['sku'], 'reason': 'Unknown SKU'})
            continue

        try:
            stock = StockLevel.objects.get(product=product)
        except StockLevel.DoesNotExist:
            continue

        old_fba = stock.fba_stock
        new_fba = item['available']

        if old_fba != new_fba:
            changes.append({
                'm_number': product.m_number,
                'sku': item['sku'],
                'field': 'fba_stock',
                'old': old_fba,
                'new': new_fba,
                'restock_recommended': item['restock_quantity'],
            })
            if not preview_only:
                stock.fba_stock = new_fba
                stock.save(update_fields=['fba_stock', 'updated_at'])

    return {
        'report_type': 'restock',
        'preview': preview_only,
        'changes': changes,
        'skipped': skipped,
        'total_items': len(parsed['items']),
    }


APPLIERS = {
    'fba_inventory': apply_fba_inventory,
    'sales_traffic': apply_sales_traffic,
    'restock': apply_restock_inventory,
}
