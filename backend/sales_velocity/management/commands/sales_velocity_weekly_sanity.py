"""
Weekly post-cutover sanity check. Populates DriftAlert rows for any
product whose today's velocity differs from the 7-day rolling average
by more than the configured tolerance (default 5%).

Runs via Django-Q weekly schedule — see migration 0002. Can also be
invoked manually for debugging:

    python manage.py sales_velocity_weekly_sanity
    python manage.py sales_velocity_weekly_sanity --tolerance 10.0
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from sales_velocity.services.aggregator import run_weekly_sanity_check


class Command(BaseCommand):
    help = 'Run the weekly post-cutover drift sanity check.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tolerance',
            type=float,
            default=5.0,
            help='Variance threshold in percent. Default 5.0.',
        )

    def handle(self, *args, **opts):
        result = run_weekly_sanity_check(tolerance_pct=opts['tolerance'])
        self.stdout.write(json.dumps(result, indent=2))
