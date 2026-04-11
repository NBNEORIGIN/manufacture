"""
Purge stale audit log + drift alert rows.

Runs via Django-Q weekly schedule. Retention policy:
- SalesVelocityAPICall successes: 14 days
- SalesVelocityAPICall errors:    90 days
- DriftAlert:                     90 days
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from sales_velocity.services.aggregator import purge_audit_log


class Command(BaseCommand):
    help = 'Delete stale SalesVelocityAPICall and DriftAlert rows.'

    def handle(self, *args, **opts):
        result = purge_audit_log()
        self.stdout.write(json.dumps(result, indent=2))
