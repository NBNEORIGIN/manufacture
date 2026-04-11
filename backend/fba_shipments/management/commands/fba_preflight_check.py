"""
Pre-flight readiness check for the FBA Shipment Automation module.

Reports, for a given marketplace, how many active SKUs are ready to be included
in an automated FBA shipment. The three axes are:

  1. FNSKU coverage  — does `barcodes.ProductBarcode` have an FNSKU row for the
     SKU's Product in this marketplace?
  2. Shipping dimensions — does the underlying Product have length/width/height
     /weight values populated? These feed `setPackingInformation`.
  3. Prep category set in Seller Central — this is the one axis the command
     CANNOT verify locally; v2024-03-20 does not expose PrepDetailList as an
     API input, and `getInventorySummaries` does not return prep state. We
     surface a reminder so Ben knows to check Seller Central manually.

Usage:
    python manage.py fba_preflight_check --marketplace UK
    python manage.py fba_preflight_check --marketplace UK --show-missing

Exit code is 0 if every active SKU has FNSKU + shipping dimensions; 1 otherwise.
This makes the command suitable for a CI-style readiness gate.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from barcodes.models import ProductBarcode
from fba_shipments.models import FBA_MARKETPLACE_CHOICES
from products.models import SKU, Product


SUPPORTED_MARKETPLACES = {code for code, _ in FBA_MARKETPLACE_CHOICES}

# Channels in products.SKU.channel that are FBA-eligible for a given marketplace.
# Some marketplaces have historical channel aliases (e.g. 'UK' vs 'EBAY_UK'); for
# FBA we only care about the plain Amazon channel code.
MARKETPLACE_TO_SKU_CHANNELS = {
    'UK': {'UK'},
    'US': {'US'},
    'CA': {'CA'},
    'AU': {'AU'},
    'DE': {'DE'},
}

# Product fields that must be populated for setPackingInformation to succeed.
# These are added by the products 0008_shipping_dimensions migration.
SHIPPING_DIMENSION_FIELDS = (
    'shipping_length_cm',
    'shipping_width_cm',
    'shipping_height_cm',
    'shipping_weight_g',
)


class Command(BaseCommand):
    help = "Check that active SKUs for a marketplace are ready for FBA shipment automation."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            '--marketplace',
            required=True,
            choices=sorted(SUPPORTED_MARKETPLACES),
            help='Marketplace code to check (UK, US, CA, AU, DE).',
        )
        parser.add_argument(
            '--show-missing',
            action='store_true',
            help='List the M-numbers / SKUs that are missing prerequisites.',
        )

    def handle(self, *args, marketplace: str, show_missing: bool, **kwargs) -> None:
        if marketplace not in SUPPORTED_MARKETPLACES:
            raise CommandError(f'Unsupported marketplace: {marketplace}')

        eligible_channels = MARKETPLACE_TO_SKU_CHANNELS[marketplace]

        # 1. Active SKUs for this marketplace
        active_skus = (
            SKU.objects
            .filter(channel__in=eligible_channels, active=True, product__active=True)
            .select_related('product')
            .order_by('product__m_number')
        )
        total_skus = active_skus.count()

        if total_skus == 0:
            self.stdout.write(self.style.WARNING(
                f'No active SKUs found for channel in {eligible_channels}. '
                f'Nothing to check.'
            ))
            return

        # 2. FNSKU coverage via barcodes.ProductBarcode
        fnsku_product_ids = set(
            ProductBarcode.objects
            .filter(
                barcode_type='FNSKU',
                marketplace__in=[marketplace, 'ALL'],
                barcode_value__gt='',
            )
            .values_list('product_id', flat=True)
        )

        # 3. Shipping dimension coverage on Product
        dims_filter = Q()
        for field in SHIPPING_DIMENSION_FIELDS:
            # A field is "populated" if it is not null and not zero.
            dims_filter &= Q(**{f'{field}__isnull': False}) & ~Q(**{field: 0})
        products_with_dims = set(
            Product.objects
            .filter(dims_filter)
            .values_list('id', flat=True)
        )

        # Tally
        fnsku_ok: list[SKU] = []
        fnsku_missing: list[SKU] = []
        dims_ok: list[SKU] = []
        dims_missing: list[SKU] = []

        for sku in active_skus:
            if sku.product_id in fnsku_product_ids:
                fnsku_ok.append(sku)
            else:
                fnsku_missing.append(sku)
            if sku.product_id in products_with_dims:
                dims_ok.append(sku)
            else:
                dims_missing.append(sku)

        fully_ready = [
            sku for sku in active_skus
            if sku.product_id in fnsku_product_ids
            and sku.product_id in products_with_dims
        ]

        # Output
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'FBA preflight — marketplace {marketplace}'
        ))
        self.stdout.write('')
        self._row('Active SKUs',          total_skus,        total_skus)
        self._row('With FNSKU',           len(fnsku_ok),     total_skus)
        self._row('With shipping dims',   len(dims_ok),      total_skus)
        self._row('Fully ready',          len(fully_ready),  total_skus)
        self.stdout.write('')

        # Prep category reminder — cannot be verified automatically.
        self.stdout.write(self.style.WARNING(
            'Reminder: `Prep category` must be set per SKU once in Seller Central '
            '(one-time manual step). v2024-03-20 does not accept PrepDetailList as '
            'an API input; Amazon forces configuration via the UI. If createInboundPlan '
            'fails with FBA_INB_0182 or similar, the prep category is the first thing '
            'to check.'
        ))
        self.stdout.write('')

        if show_missing:
            if fnsku_missing:
                self.stdout.write(self.style.NOTICE(
                    f'SKUs missing an FNSKU for {marketplace} '
                    f'(populate via barcodes sync):'
                ))
                for sku in fnsku_missing:
                    self.stdout.write(f'  - {sku.product.m_number} / {sku.sku}')
                self.stdout.write('')

            if dims_missing:
                self.stdout.write(self.style.NOTICE(
                    'Products missing shipping dimensions '
                    '(length/width/height/weight):'
                ))
                shown: set[str] = set()
                for sku in dims_missing:
                    key = sku.product.m_number
                    if key in shown:
                        continue
                    shown.add(key)
                    self.stdout.write(f'  - {sku.product.m_number} — {sku.product.description[:60]}')
                self.stdout.write('')

        if len(fully_ready) == total_skus:
            self.stdout.write(self.style.SUCCESS(
                f'All {total_skus} active SKU(s) for {marketplace} are '
                f'ready for FBA shipment automation (excluding prep category).'
            ))
            return

        # Non-zero exit on incompleteness so this command can gate a deployment.
        raise CommandError(
            f'{total_skus - len(fully_ready)} of {total_skus} SKU(s) not ready '
            f'for FBA shipment automation in {marketplace}. '
            f'Re-run with --show-missing for details.'
        )

    def _row(self, label: str, count: int, total: int) -> None:
        pct = (count / total * 100) if total else 0.0
        self.stdout.write(f'  {label:<22} {count:>6} / {total} ({pct:5.1f}%)')
