"""
Personalised-order analytics for Ivan + Ben.

The dispatch queue on /d2c is for fulfillable generics only. Personalised
orders go through the memorial app / manual brass workflow, so they don't
need an action button. But they DO need to be counted so we know how many
blanks of each variant to prepare and on what cadence.

This module joins `DispatchOrder` rows to the `PersonalisedSKU` catalogue
and returns aggregated counts, sliced by product type / colour / decoration
/ theme, for three rolling windows (7d / 30d / 90d) plus all-time.

Endpoint:
    GET /api/d2c/personalised/stats/
"""
from datetime import timedelta
from collections import defaultdict

from django.db.models import Sum, Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from .models import DispatchOrder, PersonalisedSKU, ProductTypeBlanks, ColourBlanks
from products.models import Product, SKU as MarketplaceSKU


@api_view(['GET'])
@permission_classes([AllowAny])
def personalised_m_numbers(request):
    """
    Return the set of M-numbers considered personalised — used by the
    Profitability page to flag rows.

    A product is personalised if either:
      1. Product.is_personalised is True (the canonical flag), OR
      2. Any PersonalisedSKU.sku resolves (via products.SKU) to a product
         with that M-number.

    Both routes are unioned because the catalogue and the Product flag
    drift independently — a SKU lands in the personalised CSV before the
    Product flag is flipped, and vice versa. Whichever signal is set
    first should mark the row personalised in profit reporting.

    Response:
        {"m_numbers": ["M0634", "M0680", ...], "count": 42}
    """
    flagged = set(
        Product.objects.filter(is_personalised=True)
        .values_list('m_number', flat=True)
    )
    catalogued_skus = list(
        PersonalisedSKU.objects.values_list('sku', flat=True)
    )
    via_catalogue = set(
        MarketplaceSKU.objects
        .filter(sku__in=catalogued_skus)
        .values_list('product__m_number', flat=True)
    )
    m_numbers = sorted(m for m in flagged | via_catalogue if m)
    return Response({'m_numbers': m_numbers, 'count': len(m_numbers)})


WINDOWS = [
    ('7d', 7),
    ('30d', 30),
    ('90d', 90),
]


def _sum_qty(qs) -> int:
    return qs.aggregate(total=Sum('quantity'))['total'] or 0


def _group_counts(qs, field_map, label_field):
    """
    Aggregate `qs` (a DispatchOrder queryset already joined to PersonalisedSKU
    via `sku__in`) into a dict keyed by PersonalisedSKU[label_field].

    `field_map` is the sku → label lookup dict we precompute once.
    Returns {label: total_qty} with totals summed across matching rows.
    """
    buckets: dict[str, int] = defaultdict(int)
    rows = qs.values('sku', 'quantity')
    for r in rows:
        label = field_map.get(r['sku'], '')
        if not label:
            label = 'Unknown'
        buckets[label] += r['quantity']
    return dict(buckets)


@api_view(['GET'])
@permission_classes([AllowAny])
def personalised_stats(request):
    """
    Return aggregated personalised-order counts across multiple time windows
    and dimensions. Response shape:

    {
      "windows": ["7d", "30d", "90d", "all"],
      "totals": {"7d": 42, "30d": 180, "90d": 510, "all": 2137},
      "by_type":        [{"label": "Regular Stake", "7d": 22, "30d": 94, "90d": 281, "all": 1012}, ...],
      "by_colour":      [...],
      "by_decoration":  [...],
      "by_theme":       [...],
      "by_sku":         [...],
      "catalogue_size": 99,
      "last_order_date": "2026-04-23T18:42:13Z",
    }
    """
    # Build sku → (type, colour, decoration, theme) maps
    catalogue = list(PersonalisedSKU.objects.all())
    type_map      = {c.sku: c.product_type or 'Unknown'    for c in catalogue}
    colour_map    = {c.sku: c.colour or 'Unknown'          for c in catalogue}
    decoration_map= {c.sku: c.decoration_type or 'Unknown' for c in catalogue}
    theme_map     = {c.sku: c.theme or '(no theme)'        for c in catalogue}
    personalised_skus = set(type_map.keys())

    # Base queryset: any dispatch order whose SKU is in the catalogue,
    # or whose linked product is flagged is_personalised.
    base = DispatchOrder.objects.filter(
        Q(sku__in=personalised_skus) | Q(product__is_personalised=True)
    )

    now = timezone.now()

    def window_qs(days):
        since = now - timedelta(days=days)
        # Use order_date when we have it, else created_at
        return base.filter(
            Q(order_date__gte=since) | Q(order_date__isnull=True, created_at__gte=since)
        )

    window_qsets = {label: window_qs(days) for label, days in WINDOWS}
    window_qsets['all'] = base

    # ── Totals per window ──────────────────────────────────────────────
    totals = {label: _sum_qty(qs) for label, qs in window_qsets.items()}

    # ── Grouped rows per dimension ─────────────────────────────────────
    # We only group the rows that are actually in the catalogue (known
    # personalised SKUs). Unknown-personalised orders still contribute to
    # the totals.
    def grouped(field_map, sort_desc=True):
        labels: set[str] = set()
        per_window: dict[str, dict[str, int]] = {}
        for w_label, qs in window_qsets.items():
            # Restrict to catalogue SKUs for grouping (we need a label)
            rows = qs.filter(sku__in=personalised_skus).values('sku', 'quantity')
            buckets: dict[str, int] = defaultdict(int)
            for r in rows:
                label = field_map.get(r['sku']) or 'Unknown'
                buckets[label] += r['quantity']
            per_window[w_label] = dict(buckets)
            labels.update(buckets.keys())

        rows_out = []
        for label in sorted(labels):
            row = {'label': label}
            for w_label in ('7d', '30d', '90d', 'all'):
                row[w_label] = per_window.get(w_label, {}).get(label, 0)
            rows_out.append(row)
        # Sort by all-time desc for a "top N" feel
        if sort_desc:
            rows_out.sort(key=lambda r: r.get('all', 0), reverse=True)
        return rows_out

    last_order = (
        base.exclude(order_date__isnull=True)
        .order_by('-order_date').values_list('order_date', flat=True).first()
        or base.order_by('-created_at').values_list('created_at', flat=True).first()
    )

    # Blank-name map: product_type → "Tom (acrylic), Dick (aluminium)" etc.
    blank_map = dict(
        ProductTypeBlanks.objects.values_list('product_type', 'blank_names')
    )

    by_type_rows = grouped(type_map)
    for row in by_type_rows:
        row['blank_names'] = blank_map.get(row['label'], '')

    colour_blank_map = dict(ColourBlanks.objects.values_list('colour', 'blank_names'))
    by_colour_rows = grouped(colour_map)
    for row in by_colour_rows:
        row['blank_names'] = colour_blank_map.get(row['label'], '')

    return Response({
        'windows': ['7d', '30d', '90d', 'all'],
        'totals': totals,
        'by_type':       by_type_rows,
        'by_colour':     by_colour_rows,
        'by_decoration': grouped(decoration_map),
        'by_theme':      grouped(theme_map),
        'by_sku': [
            {
                'label': c.sku,
                'type': c.product_type,
                'colour': c.colour,
                'decoration': c.decoration_type,
                'theme': c.theme,
                **{
                    w: int(window_qsets[w].filter(sku=c.sku).aggregate(t=Sum('quantity'))['t'] or 0)
                    for w in ('7d', '30d', '90d', 'all')
                },
            }
            for c in sorted(catalogue, key=lambda x: x.sku)
        ],
        'catalogue_size': len(catalogue),
        'last_order_date': last_order.isoformat() if last_order else None,
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def set_product_type_blanks(request):
    """
    Set the blank names for a product type.

    Body: {"product_type": "Regular Stake", "blank_names": "Tom (acrylic), Dick (aluminium)"}
    Creates the row if it doesn't exist, overwrites if it does. Blank-names may be empty
    to clear.
    """
    product_type = (request.data.get('product_type') or '').strip()
    blank_names = (request.data.get('blank_names') or '').strip()
    notes = (request.data.get('notes') or '').strip()

    if not product_type:
        return Response(
            {'error': 'product_type is required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    obj, _ = ProductTypeBlanks.objects.update_or_create(
        product_type=product_type,
        defaults={'blank_names': blank_names, 'notes': notes},
    )
    return Response({
        'product_type': obj.product_type,
        'blank_names': obj.blank_names,
        'notes': obj.notes,
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def set_colour_blanks(request):
    """
    Set the blank names for a catalogue colour (e.g. 'Silver' → 'Dick (aluminium)').

    Body: {"colour": "Silver", "blank_names": "Dick (aluminium face, CNC cut)"}
    """
    colour = (request.data.get('colour') or '').strip()
    blank_names = (request.data.get('blank_names') or '').strip()
    notes = (request.data.get('notes') or '').strip()

    if not colour:
        return Response(
            {'error': 'colour is required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    obj, _ = ColourBlanks.objects.update_or_create(
        colour=colour,
        defaults={'blank_names': blank_names, 'notes': notes},
    )
    return Response({
        'colour': obj.colour,
        'blank_names': obj.blank_names,
        'notes': obj.notes,
    })
