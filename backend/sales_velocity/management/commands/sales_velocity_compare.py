"""
Ad-hoc diagnostic: print a per-M-number variance report between the
latest SalesVelocityHistory aggregate and current StockLevel.sixty_day_sales.

Not scheduled. Useful for debugging post-cutover: did today's velocity
agree with what the spreadsheet said yesterday?

Usage:
    python manage.py sales_velocity_compare
    python manage.py sales_velocity_compare --csv variance.csv
"""
from __future__ import annotations

import csv
import sys

from django.core.management.base import BaseCommand
from django.db.models import Max, Sum


class Command(BaseCommand):
    help = (
        'Print per-M-number variance between SalesVelocityHistory and '
        'StockLevel.sixty_day_sales.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv',
            type=str,
            default='',
            help='Write variance report to this CSV file instead of stdout.',
        )

    def handle(self, *args, **opts):
        from sales_velocity.models import SalesVelocityHistory
        from stock.models import StockLevel

        latest = SalesVelocityHistory.objects.aggregate(m=Max('snapshot_date'))['m']
        if latest is None:
            self.stdout.write(self.style.WARNING(
                'No SalesVelocityHistory rows — has the aggregator run yet?'
            ))
            return

        rows = (
            SalesVelocityHistory.objects
            .filter(snapshot_date=latest)
            .values('product_id', 'product__m_number')
            .annotate(total_30d=Sum('units_sold_30d'))
            .order_by('product__m_number')
        )
        product_ids = [r['product_id'] for r in rows]
        stock_by_product = dict(
            StockLevel.objects
            .filter(product_id__in=product_ids)
            .values_list('product_id', 'sixty_day_sales')
        )

        header = [
            'm_number', 'product_id',
            'current_stock_sixty_day_sales',
            'api_30d_times_2',
            'variance_pct',
        ]
        output_rows = []
        for r in rows:
            api_60 = (r['total_30d'] or 0) * 2
            current = stock_by_product.get(r['product_id']) or 0
            variance = 0.0
            if current:
                variance = round((api_60 - current) / current * 100, 2)
            output_rows.append([
                r['product__m_number'], r['product_id'],
                current, api_60, variance,
            ])

        if opts['csv']:
            with open(opts['csv'], 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(header)
                writer.writerows(output_rows)
            self.stdout.write(self.style.SUCCESS(
                f'Wrote {len(output_rows)} rows to {opts["csv"]}'
            ))
        else:
            writer = csv.writer(sys.stdout)
            writer.writerow(header)
            writer.writerows(output_rows)
