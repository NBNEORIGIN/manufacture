"""
Create 10 placeholder ProductBarcode rows for M0001–M0010.
Use instead of loaddata when product PKs are unknown.

    python manage.py seed_barcodes
"""
from django.core.management.base import BaseCommand, CommandError
from products.models import Product
from barcodes.models import ProductBarcode


class Command(BaseCommand):
    help = 'Seed 10 placeholder FNSKU barcodes for M0001–M0010 (dev testing)'

    def handle(self, *args, **options):
        m_numbers = [f'M{str(i).zfill(4)}' for i in range(1, 11)]
        created = 0
        skipped = 0

        for i, m_number in enumerate(m_numbers, start=1):
            try:
                product = Product.objects.get(m_number=m_number)
            except Product.DoesNotExist:
                raise CommandError(
                    f"Product {m_number} not found. "
                    "Ensure master stock has been imported before seeding barcodes."
                )

            barcode_value = f'X001TEST{str(i).zfill(3)}'
            label_title = product.description[:80]

            _, was_created = ProductBarcode.objects.get_or_create(
                product=product,
                marketplace='UK',
                barcode_type='FNSKU',
                defaults={
                    'barcode_value': barcode_value,
                    'label_title': label_title,
                    'condition': 'New',
                    'source': 'manual',
                    'notes': 'Seed data for development testing',
                },
            )
            if was_created:
                created += 1
            else:
                skipped += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Done — {created} created, {skipped} already existed'
            )
        )
