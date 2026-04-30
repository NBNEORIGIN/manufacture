"""
Bulk COGS lookup for a list of marketplace SKUs.

Reads SKUs from stdin (one per line) or from --file. Resolves each SKU to its
Product via products.SKU, then calls costs.get_cost_price() and dumps a CSV
to stdout.

Usage:
    docker compose -p manufacture exec backend \\
        python manage.py cogs_for_skus --file /tmp/skus.txt > cogs.csv

    # or piped:
    cat skus.txt | docker compose -p manufacture exec -T backend \\
        python manage.py cogs_for_skus > cogs.csv

Columns:
    sku, m_number, cost_gbp, material_gbp, labour_gbp, overhead_gbp,
    source, confidence, blank_raw, is_composite, notes
"""
from __future__ import annotations

import csv
import sys

from django.core.management.base import BaseCommand

from costs.models import get_cost_price
from products.models import SKU


class Command(BaseCommand):
    help = 'Bulk COGS lookup for marketplace SKUs (CSV out).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            help='Path to a file with one SKU per line. Defaults to stdin.',
        )
        parser.add_argument(
            '--channel',
            default='',
            help='Optional channel filter (e.g. amazon, etsy). '
                 'If omitted, the first matching SKU regardless of channel wins.',
        )

    def handle(self, *args, **opts):
        # Read SKU list
        if opts.get('file'):
            with open(opts['file']) as f:
                skus = [line.strip() for line in f if line.strip()]
        else:
            skus = [line.strip() for line in sys.stdin if line.strip()]

        if not skus:
            self.stderr.write('No SKUs given.')
            return

        # Build SKU -> Product map in one query
        qs = SKU.objects.select_related('product').filter(sku__in=skus)
        if opts['channel']:
            qs = qs.filter(channel=opts['channel'])
        # If a SKU appears under multiple channels, we keep the first one we
        # encounter — explicit --channel filter avoids ambiguity.
        sku_to_product = {}
        for row in qs:
            sku_to_product.setdefault(row.sku, row.product)

        writer = csv.writer(sys.stdout)
        writer.writerow([
            'sku', 'm_number', 'cost_gbp', 'material_gbp', 'labour_gbp',
            'overhead_gbp', 'source', 'confidence', 'blank_raw',
            'is_composite', 'notes',
        ])

        unmatched = 0
        for sku in skus:
            product = sku_to_product.get(sku)
            if product is None:
                writer.writerow([sku, '', '', '', '', '', 'UNMATCHED', '', '', '', ''])
                unmatched += 1
                continue
            r = get_cost_price(product)
            writer.writerow([
                sku,
                r['m_number'],
                r['cost_gbp'],
                r['material_gbp'] if r['material_gbp'] is not None else '',
                r['labour_gbp'] if r['labour_gbp'] is not None else '',
                r['overhead_gbp'] if r['overhead_gbp'] is not None else '',
                r['source'],
                r['confidence'],
                r['blank_raw'],
                r['is_composite'],
                r['notes'].replace('\n', ' ').strip(),
            ])

        self.stderr.write(
            f'Done: {len(skus) - unmatched} matched, {unmatched} unmatched.'
        )
