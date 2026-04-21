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
    # Ivan review 17 bug 2: iterate Products (not StockLevels) so we match the
    # Products tab's data source exactly. Every active/restockable product
    # appears, and stock is read via the OneToOne FK (same path as /api/products/).
    from products.models import Product
    products_qs = (
        Product.objects
        .select_related('stock', 'design')
        .filter(active=True, do_not_restock=False)
        # Ivan review 16: exclude N/A machine + N/A/Personalised families from Production
        .exclude(machine_type='N/A')
        .exclude(blank_family__in=['N/A', 'Personalised'])
    )

    # Build active production order lookup: m_number -> (id, simple_stage)
    active_orders = {
        o.product.m_number: (o.id, o.simple_stage)
        for o in ProductionOrder.objects.select_related('product').filter(completed_at__isnull=True)
    }

    items = []
    for p in products_qs:
        stock = getattr(p, 'stock', None)
        current_stock = stock.current_stock if stock else 0
        fba_stock = stock.fba_stock if stock else 0
        sixty_day_sales = stock.sixty_day_sales if stock else 0
        optimal_stock_30d = stock.optimal_stock_30d if stock else 0
        stock_deficit = stock.stock_deficit if stock else 0

        machine = _resolve_machine(p.blank)
        order_id, simple_stage = active_orders.get(p.m_number, (None, None))
        priority = sixty_day_sales * stock_deficit
        stored_mt = p.machine_type
        items.append({
            'm_number': p.m_number,
            'description': p.description,
            'blank': p.blank,
            'material': p.material,
            'blank_family': p.blank_family,
            'current_stock': current_stock,
            'fba_stock': fba_stock,
            'sixty_day_sales': sixty_day_sales,
            'optimal_stock_30d': optimal_stock_30d,
            'stock_deficit': stock_deficit,
            'priority_score': priority,
            'machine': machine,
            'machine_type': stored_mt if stored_mt else _machine_type(machine),
            'in_progress': p.in_progress,
            'production_order_id': order_id,
            'simple_stage': simple_stage,
            'has_design': p.has_design,
            'design_machines': p.design.machines_ready() if hasattr(p, 'design') else [],
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
