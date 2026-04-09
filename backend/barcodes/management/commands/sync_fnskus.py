"""
Sync FNSKUs from Amazon SP-API into ProductBarcode.

    python manage.py sync_fnskus --marketplace UK
    python manage.py sync_fnskus --all
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from barcodes.models import FNSKUSyncLog
from barcodes.services.sp_api_sync import sync_fnskus_for_marketplace

MARKETPLACES = ['UK', 'US', 'CA', 'AU', 'DE']


class Command(BaseCommand):
    help = 'Sync FNSKUs from Amazon SP-API'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--marketplace', choices=MARKETPLACES, help='Single marketplace')
        group.add_argument('--all', action='store_true', help='All 5 marketplaces sequentially')

    def handle(self, *args, **options):
        targets = MARKETPLACES if options['all'] else [options['marketplace']]
        for marketplace in targets:
            self.stdout.write(f'Syncing {marketplace}…')
            log = FNSKUSyncLog(marketplace=marketplace, ran_at=timezone.now())
            try:
                result = sync_fnskus_for_marketplace(marketplace)
                log.created = result['created']
                log.updated = result['updated']
                log.unmatched_count = len(result['unmatched_skus'])
                log.save()
                self.stdout.write(self.style.SUCCESS(
                    f'  {marketplace}: {result["created"]} created, {result["updated"]} updated, '
                    f'{log.unmatched_count} unmatched SKUs'
                ))
                if result['unmatched_skus']:
                    self.stdout.write(f'  Unmatched: {", ".join(result["unmatched_skus"][:20])}')
            except Exception as exc:
                log.error_message = str(exc)
                log.save()
                self.stderr.write(self.style.ERROR(f'  {marketplace} failed: {exc}'))
