"""
Import materials from PROCUREMENT sheet.
21 rows, well-structured: MaterialID, MaterialName, Category, etc.
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from openpyxl import load_workbook
from procurement.models import Material
from imports.models import ImportLog


class Command(BaseCommand):
    help = 'Import materials from PROCUREMENT sheet'

    def add_arguments(self, parser):
        parser.add_argument('--file', type=str, default=None)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        filepath = options['file'] or settings.SPREADSHEET_PATH
        dry_run = options['dry_run']

        self.stdout.write(f'Loading {filepath}...')
        wb = load_workbook(filepath, read_only=True, data_only=True)
        ws = wb['PROCUREMENT']

        rows = list(ws.iter_rows(values_only=True))
        header = rows[0]

        col_map = {}
        for idx, val in enumerate(header):
            if val:
                col_map[str(val).strip()] = idx

        stats = {'processed': 0, 'created': 0, 'updated': 0}

        for row in rows[1:]:
            mat_id = row[col_map.get('MaterialID', 0)]
            if not mat_id:
                continue

            mat_id = str(mat_id).strip()
            stats['processed'] += 1

            def get_val(key, default=''):
                idx = col_map.get(key, -1)
                if idx < 0 or idx >= len(row):
                    return default
                return row[idx] if row[idx] is not None else default

            if dry_run:
                self.stdout.write(f'  [DRY] {mat_id}: {get_val("MaterialName")}')
                continue

            price = get_val('CurrentPrice', None)
            if price is not None:
                try:
                    price = float(price)
                except (ValueError, TypeError):
                    price = None

            def safe_int(val, default=0):
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return default

            _, created = Material.objects.update_or_create(
                material_id=mat_id,
                defaults={
                    'name': str(get_val('MaterialName'))[:200],
                    'category': str(get_val('Category'))[:100],
                    'unit_of_measure': str(get_val('UnitOfMeasure'))[:50],
                    'current_stock': safe_int(get_val('CurrentStock', 0)),
                    'reorder_point': safe_int(get_val('ReorderPoint', 0)),
                    'standard_order_quantity': safe_int(get_val('StandardOrderQuantity', 0)),
                    'preferred_supplier': str(get_val('PreferredSupplierID'))[:200],
                    'product_page_url': str(get_val('ProductPageURL'))[:500],
                    'lead_time_days': safe_int(get_val('LeadTimeDays', 0)),
                    'safety_stock': safe_int(get_val('SafetyStockQuantity', 0)),
                    'in_house_description': str(get_val('In-House description'))[:200],
                    'notes': str(get_val('Notes')),
                    'current_price': price,
                },
            )

            if created:
                stats['created'] += 1
            else:
                stats['updated'] += 1

        wb.close()

        if not dry_run:
            ImportLog.objects.create(
                import_type='procurement',
                filename=filepath,
                rows_processed=stats['processed'],
                rows_created=stats['created'],
                rows_updated=stats['updated'],
                rows_skipped=0,
                errors=[],
            )

        self.stdout.write(self.style.SUCCESS(
            f"PROCUREMENT import complete: {stats['processed']} processed, "
            f"{stats['created']} created, {stats['updated']} updated"
        ))
