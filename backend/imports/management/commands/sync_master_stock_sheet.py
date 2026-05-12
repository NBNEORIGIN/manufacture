"""
Temporary one-way sync from the MASTER STOCK Google Sheet.

Pulls the published CSV at MASTER_STOCK_SHEET_CSV_URL, writes it to a
temp file, then hands off to the existing import_master_stock_csv
command which already knows the column layout.

This is intentionally minimal — the Manufacture app is still in
development and the Google Sheet remains the source of truth for
warehouse stock. When Manufacture goes live the sync direction
flips (Manufacture pushes to the sheet as a backup) and this
command can be retired or repurposed.

Setup:
  1. In Google Sheets: File → Share → Publish to web →
     Sheet: MASTER STOCK, Format: CSV → Publish.
  2. Copy the published URL.
  3. Set MASTER_STOCK_SHEET_CSV_URL=<that URL> in
     /etc/nbne/manufacture.env (or the deployment secret store).
  4. Add a host crontab entry:
        */5 * * * * cd /opt/nbne/manufacture && \\
            docker compose -p manufacture -f docker/docker-compose.yml \\
            exec -T backend python manage.py sync_master_stock_sheet \\
            >> /var/log/nbne/master_stock_sync.log 2>&1

Notes:
  - Read-only — never writes back to the sheet.
  - Falls through to import_master_stock_csv, so the row-level dedup
    and ImportLog audit trail are reused.
  - Warehouse stock only (StockLevel.current_stock). FBA stock is
    populated independently from SP-API and is not touched here.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import requests
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


SHEET_URL_ENV = 'MASTER_STOCK_SHEET_CSV_URL'
DEFAULT_TIMEOUT_S = 30


class Command(BaseCommand):
    help = (
        'Pull the MASTER STOCK Google Sheet (published CSV URL) and '
        'import via import_master_stock_csv. Read-only sync.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--url',
            help=f'Override the {SHEET_URL_ENV} env var.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Fetch the sheet but report changes without writing.',
        )
        parser.add_argument(
            '--timeout', type=int, default=DEFAULT_TIMEOUT_S,
            help=f'HTTP timeout in seconds (default {DEFAULT_TIMEOUT_S}).',
        )

    def handle(self, *args, **opts):
        url = opts.get('url') or os.environ.get(SHEET_URL_ENV) \
            or getattr(settings, SHEET_URL_ENV, '')
        if not url:
            raise CommandError(
                f'No URL — set {SHEET_URL_ENV} env var or pass --url.\n'
                f'Get the URL from Google Sheets via '
                f'File → Share → Publish to web → CSV.'
            )

        self.stdout.write(f'Fetching MASTER STOCK sheet from {url[:80]}…')
        try:
            resp = requests.get(url, timeout=opts['timeout'])
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise CommandError(f'Sheet fetch failed: {exc}') from exc

        body = resp.content
        if not body:
            raise CommandError('Sheet fetch returned empty body.')

        # Sanity-check: a published CSV starts with text, not HTML. If the
        # sheet isn't actually published-to-web Google returns a sign-in page.
        head = body[:200].lstrip().lower()
        if head.startswith(b'<!doctype') or head.startswith(b'<html'):
            raise CommandError(
                'Got HTML, not CSV. The sheet probably isn\'t published-to-web. '
                'Re-do File → Share → Publish to web → CSV in Google Sheets.'
            )

        # Write to a temp file and delegate to the existing import command.
        with tempfile.NamedTemporaryFile(
            mode='wb', suffix='.csv', delete=False
        ) as tmp:
            tmp.write(body)
            tmp_path = Path(tmp.name)

        try:
            self.stdout.write(f'Saved {len(body)} bytes to {tmp_path}')
            call_command(
                'import_master_stock_csv',
                file=str(tmp_path),
                **({'dry_run': True} if opts['dry_run'] else {}),
            )
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass


def run_master_stock_sheet_sync():
    """
    Callable entry point for Django-Q2 scheduled task — registered by the
    imports/migrations/0002_register_master_stock_schedule.py migration as
    `master_stock_sheet_sync_5min`, runs every 5 minutes.

    Pull-direction only: sheet → Manufacture. The push direction is built
    (push_master_stock_sheet command) but stays dormant via the
    STOCK_PUSH_TO_SHEET_ENABLED flag until Toby decides to flip the source
    of truth.
    """
    from django.core.management import call_command
    call_command('sync_master_stock_sheet')
