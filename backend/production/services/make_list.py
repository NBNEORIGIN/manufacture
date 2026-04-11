"""
Make List Engine — replicates Ivan's Worksheet logic.

For each active product where do_not_restock=False:
  deficit = optimal_stock_30d - current_stock
  priority = sixty_day_sales * deficit (highest = most urgent)

Returns ordered list of items sorted by priority descending.
"""
from stock.models import StockLevel
from production.models import ProductionOrder


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
    'HAROLD': 'ROLF',
    'BUNDY': 'ROLF',
    'FRED': 'ROLF',
    'KIM': 'ROLF',
    'JAVED': 'ROLF',
    'JIMMY': 'ROLF',
    'MIKHAIL': 'ROLF',
    'YANG': 'ROLF',
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
    'GERRY': 'MIMAKI',
    'SPOTTED DICK': 'MIMAKI',
    'LITTLE DICK': 'MIMAKI',
    'BIG DICK': 'ROLF',
}


MACHINE_TYPE_MAP = {
    'ROLF': 'UV',
    'MIMAKI': 'UV',
    'MAO': 'UV',
    'EPSON': 'SUB',
    'MUTOH': 'SUB',
}


def _resolve_machine(blank: str) -> str:
    """Resolve machine from blank, handling composite blanks like 'DICK, TOM'."""
    if not blank:
        return ''
    # Direct match first
    if blank in BLANK_MACHINE_MAP:
        return BLANK_MACHINE_MAP[blank]
    # Try first word for composites like "BUNDY, HAROLD" or "DICK ,TOM"
    first = blank.split(',')[0].split('-')[0].strip()
    if first in BLANK_MACHINE_MAP:
        return BLANK_MACHINE_MAP[first]
    return ''


def _machine_type(machine: str) -> str:
    return MACHINE_TYPE_MAP.get(machine.upper(), machine)


def get_make_list(group_by_blank=False):
    # Return every active, restockable product — the frontend windows the list
    # and users can filter by deficit via the "Deficit ≥ %" filter. We no longer
    # gate on stock_deficit>0 so Ivan can see the full catalogue in one place.
    stocks = (
        StockLevel.objects
        .select_related('product', 'product__design')
        .filter(
            product__active=True,
            product__do_not_restock=False,
        )
    )

    # Build active production order lookup: m_number -> (id, simple_stage)
    active_orders = {
        o.product.m_number: (o.id, o.simple_stage)
        for o in ProductionOrder.objects.select_related('product').filter(completed_at__isnull=True)
    }

    items = []
    for s in stocks:
        machine = _resolve_machine(s.product.blank)
        order_id, simple_stage = active_orders.get(s.product.m_number, (None, None))
        priority = s.sixty_day_sales * s.stock_deficit
        # Use stored machine_type override if set, otherwise derive from blank
        stored_mt = s.product.machine_type
        items.append({
            'm_number': s.product.m_number,
            'description': s.product.description,
            'blank': s.product.blank,
            'material': s.product.material,
            'blank_family': s.product.blank_family,
            'current_stock': s.current_stock,
            'fba_stock': s.fba_stock,
            'sixty_day_sales': s.sixty_day_sales,
            'optimal_stock_30d': s.optimal_stock_30d,
            'stock_deficit': s.stock_deficit,
            'priority_score': priority,
            'machine': machine,
            'machine_type': stored_mt if stored_mt else _machine_type(machine),
            'in_progress': s.product.in_progress,
            'production_order_id': order_id,
            'simple_stage': simple_stage,
            'has_design': s.product.has_design,
            'design_machines': s.product.design.machines_ready() if hasattr(s.product, 'design') else [],
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
