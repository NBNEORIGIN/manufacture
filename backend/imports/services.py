"""
Import service: applies parsed report data to the database.
All stock updates are staged (preview mode) and require confirmation.
"""
import re

from products.models import Product, SKU
from stock.models import StockLevel


# Match an embedded M-number anywhere in the SKU, e.g. "LARGE M0634",
# "M0634GOLD", "M0634S-CAT - GOLD". Anchored by a word boundary on the M
# so we don't grab random "...cmMxxx..." fragments.
_M_NUMBER_RE = re.compile(r'(?:^|[^A-Z0-9])(M\d{3,5})(?=$|[^0-9])')


def _resolve_sku_to_product(sku_value: str):
    """
    Resolve a marketplace SKU to a Product.

    Resolution order (first hit wins):
      1. Exact match on products.SKU
      2. Case-insensitive match on products.SKU
      3. Regex-extract an embedded M-number (e.g. "LARGE M0634" → M0634)
         and look that up in Product.m_number. This catches Etsy / eBay
         variant strings that weren't explicitly registered in the SKU
         table but reference a known M-number.
    """
    if not sku_value:
        return None
    sku_clean = sku_value.strip()
    try:
        # 1) Exact match
        sku_obj = SKU.objects.select_related('product').filter(sku=sku_clean).first()
        if sku_obj:
            return sku_obj.product
        # 2) Case-insensitive
        sku_obj = SKU.objects.select_related('product').filter(sku__iexact=sku_clean).first()
        if sku_obj:
            return sku_obj.product
        # 3) Regex fallback — scan for embedded M-number
        m = _M_NUMBER_RE.search(sku_clean.upper())
        if m:
            m_number = m.group(1)
            product = Product.objects.filter(m_number=m_number).first()
            if product:
                return product
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
                # NB: recalculate_deficit() saves with update_fields=['stock_deficit',
                # 'updated_at'] only, which would drop our sixty_day_sales write.
                # Persist the sales value FIRST, then recalc.
                stock.save(update_fields=['sixty_day_sales', 'updated_at'])
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


def apply_zenstores(parsed: dict, preview_only=True) -> dict:
    """
    Apply Zenstores export: creates DispatchOrder records in the D2C queue.
    Idempotent — skips orders that already exist by order_id + sku.
    """
    from d2c.models import DispatchOrder
    from dateutil.parser import parse as parse_date

    changes = []
    skipped = []

    for item in parsed['items']:
        # Check if already imported (idempotent)
        exists = DispatchOrder.objects.filter(
            order_id=item['order_id'], sku=item['sku']
        ).exists()
        if exists:
            skipped.append({'sku': item['sku'], 'reason': f'Order {item["order_id"]} already imported'})
            continue

        product = _resolve_sku_to_product(item['sku'])

        changes.append({
            'order_id': item['order_id'],
            'sku': item['sku'],
            'm_number': product.m_number if product else '',
            'quantity': item['quantity'],
            'flags': item['flags'],
            'channel': item['channel'],
            'description': item['description'][:60],
        })

        if not preview_only:
            order_date = None
            if item['order_date']:
                try:
                    order_date = parse_date(item['order_date'])
                except (ValueError, TypeError):
                    pass

            DispatchOrder.objects.create(
                order_id=item['order_id'],
                sku=item['sku'],
                product=product,
                description=item['description'][:500],
                quantity=item['quantity'],
                flags=item['flags'],
                channel=item['channel'],
                order_date=order_date,
                customer_name=item['customer_name'][:200],
            )

    return {
        'report_type': 'zenstores',
        'preview': preview_only,
        'changes': changes,
        'skipped': skipped,
        'total_items': len(parsed['items']),
    }


APPLIERS = {
    'fba_inventory': apply_fba_inventory,
    'sales_traffic': apply_sales_traffic,
    'restock': apply_restock_inventory,
    'zenstores': apply_zenstores,
}
