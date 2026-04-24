"""
CSV-based variant of import_master_stock.

The primary command reads the MASTER STOCK XLSX sheet. This one accepts a
CSV export of the same sheet (produced by Google Sheets "Download → CSV").

CSV shape — the first two rows are summary totals (ignored), row 3 is the
header, data begins at row 4:

    <summary row>
    <summary row>
    IN PROGRESS,MASTER,DESCRIPTION,BLANK,MATERIAL,STOCK,60 Day Stock,...
    FALSE,M0001,Silver Circular Push Pull,DONALD,SILVER SUB,190,245,...
    ...

Usage:
    python manage.py import_master_stock_csv --file path/to/MASTER_STOCK.csv [--dry-run]
"""
import csv
import re

from django.core.management.base import BaseCommand, CommandError

from products.models import Product
from stock.models import StockLevel
from imports.models import ImportLog


def _safe_int(v):
    try:
        return int(float(str(v).replace(',', '').strip()))
    except (ValueError, TypeError, AttributeError):
        return 0


def _as_bool(v) -> bool:
    if v is None:
        return False
    s = str(v).strip().upper()
    return s in ('TRUE', '1', 'YES', 'Y')


class Command(BaseCommand):
    help = 'Import / refresh Product + StockLevel rows from a MASTER STOCK CSV.'

    def add_arguments(self, parser):
        parser.add_argument('--file', type=str, required=True,
                            help='Path to the MASTER STOCK CSV.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would change without writing.')

    def handle(self, *args, **opts):
        path = opts['file']
        dry = opts['dry_run']

        self.stdout.write(f'Reading {path}')
        try:
            with open(path, encoding='utf-8-sig', newline='') as fh:
                rows = list(csv.reader(fh))
        except FileNotFoundError as exc:
            raise CommandError(f'File not found: {path}') from exc

        if len(rows) < 4:
            raise CommandError('CSV too short — expected 2 summary rows, 1 header row, then data.')

        header_row = rows[2]
        data_rows = rows[3:]

        col_map = {}
        for idx, val in enumerate(header_row):
            if val and str(val).strip():
                col_map[str(val).strip().upper()] = idx

        required = ['MASTER', 'DESCRIPTION', 'BLANK']
        for col in required:
            if col not in col_map:
                raise CommandError(
                    f'Missing required column: {col}. Found: {sorted(col_map.keys())}'
                )

        def get(row, key, default=''):
            idx = col_map.get(key)
            if idx is None or idx >= len(row):
                return default
            return row[idx]

        stats = {'processed': 0, 'created': 0, 'updated': 0, 'skipped': 0, 'unchanged': 0}
        errors: list[dict] = []

        for row in data_rows:
            m_number_raw = get(row, 'MASTER')
            if not m_number_raw or not str(m_number_raw).strip():
                continue
            m_number = str(m_number_raw).strip().upper()
            if not re.match(r'^M\d+$', m_number):
                continue

            stats['processed'] += 1

            description = str(get(row, 'DESCRIPTION') or '').strip()
            blank = str(get(row, 'BLANK') or '').strip().upper()
            material = str(get(row, 'MATERIAL') or '').strip()
            in_progress = _as_bool(get(row, 'IN PROGRESS'))

            stock_val = _safe_int(get(row, 'STOCK'))
            sixty_day = _safe_int(get(row, '60 DAY STOCK'))
            deficit = _safe_int(get(row, 'STOCK DEFICIT'))

            if not description:
                stats['skipped'] += 1
                errors.append({'m_number': m_number, 'reason': 'empty description'})
                continue

            if dry:
                self.stdout.write(
                    f'  [DRY] {m_number}: {description[:50]} ({blank}) '
                    f'stock={stock_val} 60d={sixty_day} deficit={deficit}'
                )
                continue

            try:
                product, created = Product.objects.update_or_create(
                    m_number=m_number,
                    defaults={
                        'description': description[:500],
                        'blank': blank[:50],
                        'material': material[:100],
                        'in_progress': in_progress,
                        'active': True,
                    },
                )
                StockLevel.objects.update_or_create(
                    product=product,
                    defaults={
                        'current_stock': stock_val,
                        'sixty_day_sales': sixty_day,
                        'stock_deficit': max(0, deficit),
                    },
                )
                if created:
                    stats['created'] += 1
                else:
                    stats['updated'] += 1
            except Exception as exc:
                errors.append({'m_number': m_number, 'reason': str(exc)[:200]})
                stats['skipped'] += 1

        if not dry:
            ImportLog.objects.create(
                import_type='master_stock',
                filename=path,
                rows_processed=stats['processed'],
                rows_created=stats['created'],
                rows_updated=stats['updated'],
                rows_skipped=stats['skipped'],
                errors=errors[:50],
            )

        prefix = '[DRY RUN] ' if dry else ''
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}MASTER STOCK CSV import complete: "
            f"{stats['processed']} processed, "
            f"{stats['created']} created, "
            f"{stats['updated']} updated, "
            f"{stats['skipped']} skipped, "
            f"{len(errors)} errors"
        ))
