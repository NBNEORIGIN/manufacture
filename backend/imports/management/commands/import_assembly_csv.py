"""
Import Products and SKUs from the ASSEMBLY CSV export.

CSV columns (0-indexed):
  0  SKU             — seller SKU for this channel
  1  MASTER SKU      — M-number (e.g. M0001), links rows to a Product
  2  NEW SKU         — replacement SKU if any
  3  COUNTRY         — channel/marketplace code
  4  DESCRIPTION     — product description
  5  BLANK           — blank family
  6  IS PERSONALISED?— non-empty = True
  7  ASIN            — Amazon ASIN
  8  LINK
  9  Notes
  10 STOCK           — stock level (informational only)

Columns 11+ are a lookup table embedded in the same sheet — ignored.

Channel normalisation:
  UK               → UK
  US / USA         → US
  AU / AUS         → AU
  CA               → CA
  DE               → DE
  ES               → ES
  FR / FR*         → FR
  IT / IT*         → IT
  NL               → NL
  EBAY             → EBAY
  ETSY / Etsy / ETSY* → ETSY
  SHOPIFY          → SHOPIFY
  anything else    → skipped (STOCK, REUSE, OLD LISTING, etc.)
"""
import csv
import re
import sys
from django.core.management.base import BaseCommand
from django.db import transaction
from products.models import Product, SKU
from imports.models import ImportLog

VALID_CHANNELS = {
    'UK', 'US', 'AU', 'CA', 'DE', 'ES', 'FR', 'IT', 'NL',
    'EBAY', 'ETSY', 'SHOPIFY',
}

CHANNEL_ALIASES = {
    'USA': 'US',
    'AUS': 'AU',
    'Etsy': 'ETSY',
    'amazon': 'UK',  # bare 'amazon' is ambiguous — treat as UK
}


def normalise_channel(raw: str) -> str | None:
    raw = (raw or '').strip()
    if not raw:
        return None
    if raw in VALID_CHANNELS:
        return raw
    if raw in CHANNEL_ALIASES:
        return CHANNEL_ALIASES[raw]
    # Prefix matching: FR CRAFTS, FR DESIGNED, IT DESIGNED, ETSY*, etc.
    for prefix in ('FR', 'IT', 'ETSY'):
        if raw.upper().startswith(prefix):
            return prefix
    return None  # skip STOCK, REUSE, OLD LISTING, etc.


def normalise_m_number(raw: str) -> str | None:
    """Return uppercase M-number if it looks like M0001-M9999, else None."""
    raw = (raw or '').strip().upper()
    if re.match(r'^M\d{3,}$', raw):
        return raw
    return None


class Command(BaseCommand):
    help = 'Import Products and SKUs from the ASSEMBLY CSV'

    def add_arguments(self, parser):
        parser.add_argument('--file', required=True, type=str,
                            help='Path to the ASSEMBLY .csv file')
        parser.add_argument('--dry-run', action='store_true',
                            help='Parse and report without writing to the DB')
        parser.add_argument('--encoding', default='utf-8-sig',
                            help='File encoding (default: utf-8-sig)')

    def handle(self, *args, **options):
        filepath = options['file']
        dry_run = options['dry_run']
        encoding = options['encoding']

        self.stdout.write(f'Reading {filepath}...')
        try:
            with open(filepath, encoding=encoding, errors='replace', newline='') as f:
                rows = list(csv.reader(f))
        except FileNotFoundError:
            self.stderr.write(f'File not found: {filepath}')
            sys.exit(1)

        if not rows:
            self.stderr.write('Empty file.')
            sys.exit(1)

        # Skip header row
        data_rows = rows[1:]
        self.stdout.write(f'{len(data_rows)} data rows.')

        # ── Pass 1: collect unique products ───────────────────────────────────
        # Use first occurrence of each M-number for product fields.
        products_data: dict[str, dict] = {}
        for row in data_rows:
            if len(row) < 5:
                continue
            m_number = normalise_m_number(row[1])
            if not m_number or m_number in products_data:
                continue
            description = str(row[4] or '').strip()[:500] or m_number
            blank = str(row[5] or '').strip().upper()[:50]
            is_personalised = bool(str(row[6] or '').strip())
            products_data[m_number] = {
                'description': description,
                'blank': blank,
                'is_personalised': is_personalised,
            }

        self.stdout.write(f'Unique products found: {len(products_data)}')

        # ── Pass 2: collect SKU rows ───────────────────────────────────────────
        sku_rows = []
        skipped_channel = 0
        skipped_no_sku = 0
        for row in data_rows:
            if len(row) < 4:
                continue
            m_number = normalise_m_number(row[1])
            if not m_number:
                continue
            seller_sku = str(row[0] or '').strip()
            if not seller_sku:
                skipped_no_sku += 1
                continue
            channel = normalise_channel(row[3])
            if not channel:
                skipped_channel += 1
                continue
            new_sku = str(row[2] or '').strip()[:100]
            asin = str(row[7] or '').strip()[:20]
            sku_rows.append({
                'm_number': m_number,
                'sku': seller_sku[:100],
                'new_sku': new_sku,
                'channel': channel,
                'asin': asin,
            })

        self.stdout.write(
            f'Valid SKU rows: {len(sku_rows)} '
            f'(skipped {skipped_channel} unknown channels, '
            f'{skipped_no_sku} missing SKU)'
        )

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — no changes written.'))
            return

        # ── Write ──────────────────────────────────────────────────────────────
        stats = {
            'products_created': 0, 'products_updated': 0,
            'skus_created': 0, 'skus_updated': 0,
        }
        errors = []

        with transaction.atomic():
            # Products
            for m_number, fields in products_data.items():
                try:
                    _, created = Product.objects.update_or_create(
                        m_number=m_number,
                        defaults=fields,
                    )
                    if created:
                        stats['products_created'] += 1
                    else:
                        stats['products_updated'] += 1
                except Exception as e:
                    errors.append(f'Product {m_number}: {e}')

            # Build a lookup cache so we don't hit the DB per SKU row
            product_cache = {
                p.m_number: p
                for p in Product.objects.filter(m_number__in=products_data.keys())
            }

            # SKUs
            for row in sku_rows:
                product = product_cache.get(row['m_number'])
                if not product:
                    errors.append(f'SKU {row["sku"]}: product {row["m_number"]} not in cache')
                    continue
                try:
                    _, created = SKU.objects.update_or_create(
                        sku=row['sku'],
                        channel=row['channel'],
                        defaults={
                            'product': product,
                            'new_sku': row['new_sku'],
                            'asin': row['asin'],
                        },
                    )
                    if created:
                        stats['skus_created'] += 1
                    else:
                        stats['skus_updated'] += 1
                except Exception as e:
                    errors.append(f'SKU {row["sku"]} ({row["channel"]}): {e}')

        ImportLog.objects.create(
            import_type='assembly',
            filename=filepath,
            rows_processed=len(data_rows),
            rows_created=stats['products_created'] + stats['skus_created'],
            rows_updated=stats['products_updated'] + stats['skus_updated'],
            rows_skipped=skipped_channel + skipped_no_sku,
            errors=errors[:100],  # cap at 100 to avoid huge JSON blobs
        )

        self.stdout.write(self.style.SUCCESS(
            f"Done. Products: {stats['products_created']} created, "
            f"{stats['products_updated']} updated. "
            f"SKUs: {stats['skus_created']} created, "
            f"{stats['skus_updated']} updated."
        ))
        if errors:
            self.stdout.write(self.style.WARNING(f'{len(errors)} errors:'))
            for e in errors[:20]:
                self.stdout.write(f'  {e}')
            if len(errors) > 20:
                self.stdout.write(f'  ... and {len(errors) - 20} more (see ImportLog)')
