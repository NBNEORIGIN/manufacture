"""
Make List Engine — replicates Ivan's Worksheet logic.

For each active product where do_not_restock=False:
  deficit = optimal_stock_30d - current_stock
  priority = sixty_day_sales * deficit (highest = most urgent)

Returns ordered list of items sorted by priority descending.
"""
from products.models import Product
from stock.models import StockLevel


BLANK_MACHINE_MAP = {
    'DONALD': 'ROLF',
    'SAVILLE': 'ROLF',
    'DICK': 'ROLF',
    'STALIN': 'ROLF',
    'JOSEPH': 'ROLF',
    'HARRY': 'ROLF',
    'AILEEN': 'ROLF',
    'SADDAM': 'ROLF',
    'LOUIS': 'ROLF',
    'IDI': 'MIMAKI',
    'MYRA': 'MIMAKI',
    'TOM': 'MIMAKI',
    'GARY': 'MIMAKI',
    'RICHARD': 'MIMAKI',
    'DRACULA': 'MIMAKI',
    'TED': 'MIMAKI',
    'PRINCE ANDREW': 'MIMAKI',
    'BARZAN': 'MIMAKI',
    'BABY JESUS': 'MIMAKI',
}


def get_make_list(group_by_blank=False):
    stocks = (
        StockLevel.objects
        .select_related('product')
        .filter(
            product__active=True,
            product__do_not_restock=False,
            stock_deficit__gt=0,
        )
    )

    items = []
    for s in stocks:
        priority = s.sixty_day_sales * s.stock_deficit
        items.append({
            'm_number': s.product.m_number,
            'description': s.product.description,
            'blank': s.product.blank,
            'material': s.product.material,
            'current_stock': s.current_stock,
            'fba_stock': s.fba_stock,
            'sixty_day_sales': s.sixty_day_sales,
            'optimal_stock_30d': s.optimal_stock_30d,
            'stock_deficit': s.stock_deficit,
            'priority_score': priority,
            'machine': BLANK_MACHINE_MAP.get(s.product.blank, ''),
        })

    items.sort(key=lambda x: x['priority_score'], reverse=True)

    if group_by_blank:
        grouped = {}
        for item in items:
            blank = item['blank']
            if blank not in grouped:
                grouped[blank] = []
            grouped[blank].append(item)
        return {'grouped': True, 'blanks': grouped}

    return {'grouped': False, 'items': items}
