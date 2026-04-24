"""
Import/refresh the personalised SKU catalogue from
backend/d2c/data/personalised_skus.csv.

CSV format:
    SKU,COLOUR,TYPE,DecorationType,Theme

Idempotent — existing rows are updated, new ones inserted, and missing
ones left alone (non-destructive). Use `--prune` to remove entries that
are no longer in the CSV.
"""
import csv
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import transaction

from d2c.models import PersonalisedSKU


DEFAULT_PATH = Path(__file__).resolve().parents[2] / 'data' / 'personalised_skus.csv'


class Command(BaseCommand):
    help = 'Seed / refresh PersonalisedSKU records from a CSV (default: backend/d2c/data/personalised_skus.csv).'

    def add_arguments(self, parser):
        parser.add_argument('--file', type=str, default=str(DEFAULT_PATH),
                            help='Path to the CSV file.')
        parser.add_argument('--prune', action='store_true',
                            help='Delete PersonalisedSKU rows not present in the CSV.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report changes without writing.')

    def handle(self, *args, **opts):
        path = Path(opts['file'])
        if not path.exists():
            self.stderr.write(self.style.ERROR(f'CSV not found: {path}'))
            return

        dry = opts['dry_run']
        prune = opts['prune']

        created = 0
        updated = 0
        unchanged = 0
        skipped = 0
        seen = set()

        with path.open(encoding='utf-8-sig') as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        self.stdout.write(f'Read {len(rows)} rows from {path}')

        with transaction.atomic():
            for row in rows:
                sku = (row.get('SKU') or '').strip()
                if not sku:
                    skipped += 1
                    continue
                seen.add(sku)

                fields = {
                    'colour': (row.get('COLOUR') or '').strip(),
                    'product_type': (row.get('TYPE') or '').strip(),
                    'decoration_type': (row.get('DecorationType') or '').strip(),
                    'theme': (row.get('Theme') or '').strip(),
                }
                # Normalise DecorationType: CSV uses Graphic / Photo / None
                if fields['decoration_type'] not in ('Graphic', 'Photo', 'None', ''):
                    fields['decoration_type'] = fields['decoration_type'].capitalize()

                existing = PersonalisedSKU.objects.filter(sku=sku).first()
                if existing:
                    diff = {k: v for k, v in fields.items() if getattr(existing, k) != v}
                    if diff:
                        if not dry:
                            for k, v in diff.items():
                                setattr(existing, k, v)
                            existing.save(update_fields=list(diff.keys()) + ['updated_at'])
                        updated += 1
                    else:
                        unchanged += 1
                else:
                    if not dry:
                        PersonalisedSKU.objects.create(sku=sku, **fields)
                    created += 1

            pruned = 0
            if prune:
                qs = PersonalisedSKU.objects.exclude(sku__in=seen)
                pruned = qs.count()
                if pruned and not dry:
                    qs.delete()

            if dry:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f'{"[DRY RUN] " if dry else ""}'
            f'Created {created}, updated {updated}, unchanged {unchanged}, '
            f'skipped {skipped}, pruned {pruned}.'
        ))
