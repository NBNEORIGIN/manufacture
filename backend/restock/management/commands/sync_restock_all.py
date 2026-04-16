"""
Management command: sync_restock_all
Runs SP-API sync for all marketplaces sequentially.
Designed to be called from cron daily.

Usage: python manage.py sync_restock_all [--marketplace GB]
"""
import logging
import time
from django.core.management.base import BaseCommand

from restock.models import RestockReport
from restock.schema import MARKETPLACE_TO_REGION
from restock.spapi_client import request_report, download_report
from restock.parser import parse_restock_csv
from restock.assembler import assemble_restock_plan

logger = logging.getLogger(__name__)

ALL_MARKETPLACES = ['GB', 'US', 'CA', 'AU', 'DE', 'FR']


class Command(BaseCommand):
    help = 'Sync FBA restock data from SP-API for all (or specified) marketplaces'

    def add_arguments(self, parser):
        parser.add_argument(
            '--marketplace',
            type=str,
            default='',
            help='Specific marketplace to sync (default: all)',
        )

    def handle(self, *args, **options):
        mp_filter = options['marketplace'].upper()
        marketplaces = [mp_filter] if mp_filter else ALL_MARKETPLACES

        self.stdout.write(f'Syncing {len(marketplaces)} marketplace(s): {", ".join(marketplaces)}')

        results = []
        for marketplace in marketplaces:
            self.stdout.write(f'  -> {marketplace}...', ending='')
            region = MARKETPLACE_TO_REGION.get(marketplace, 'EU')

            report = RestockReport.objects.create(
                marketplace=marketplace,
                region=region,
                status='running',
                source='spapi',
            )

            try:
                report_id = request_report(marketplace)
                report.report_id = report_id
                report.save(update_fields=['report_id'])

                raw_bytes = download_report(report_id, region)
                rows = parse_restock_csv(raw_bytes, filter_marketplace=marketplace)
                assemble_restock_plan(report, rows)

                report.row_count = len(rows)
                report.status = 'complete'
                report.save(update_fields=['row_count', 'status'])

                self.stdout.write(f' {len(rows)} rows')
                results.append((marketplace, 'ok', len(rows)))

            except Exception as exc:
                logger.exception('Sync failed for %s', marketplace)
                report.status = 'error'
                report.error_message = str(exc)
                report.save(update_fields=['status', 'error_message'])
                self.stdout.write(f' ERROR: {exc}')
                results.append((marketplace, 'error', str(exc)))

            # Brief pause between marketplaces to avoid SP-API rate limits
            if marketplace != marketplaces[-1]:
                time.sleep(10)

        ok = sum(1 for _, s, _ in results if s == 'ok')
        self.stdout.write(self.style.SUCCESS(f'Done: {ok}/{len(marketplaces)} succeeded'))


def run_all_sync():
    """
    Callable entry point for Django-Q2 scheduled task.
    Syncs all marketplaces sequentially.
    """
    from django.core.management import call_command
    call_command('sync_restock_all')
