"""
Manual trigger for the sales velocity aggregator.

Usage:
    python manage.py refresh_sales_velocity
    python manage.py refresh_sales_velocity --dry-run
    python manage.py refresh_sales_velocity --channels=amazon_uk,etsy
    python manage.py refresh_sales_velocity --days=7
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from sales_velocity.services.aggregator import run_daily_aggregation


class Command(BaseCommand):
    help = (
        'Run the sales velocity aggregator manually. Normally runs via '
        'Django-Q daily at 04:17 UTC.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Make real API calls but roll back all DB writes.',
        )
        parser.add_argument(
            '--channels',
            type=str,
            default='',
            help=(
                'Comma-separated channel codes to include. Default: all. '
                'Example: --channels=amazon_uk,etsy'
            ),
        )
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Lookback window in days. Default 30.',
        )

    def handle(self, *args, **opts):
        channels_filter = None
        if opts['channels']:
            channels_filter = [
                c.strip() for c in opts['channels'].split(',') if c.strip()
            ]

        result = run_daily_aggregation(
            lookback_days=opts['days'],
            channels_filter=channels_filter,
            dry_run=opts['dry_run'],
        )

        self.stdout.write(self.style.SUCCESS(
            f'Aggregation complete for {result["snapshot_date"]}:'
        ))
        self.stdout.write(json.dumps(result, indent=2))
