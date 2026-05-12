"""
Push Manufacture's current Product + StockLevel state back to the
Master Stock Google Sheet.

This is the write-direction counterpart to sync_master_stock_sheet.
That command treats the sheet as the source of truth and overwrites
Manufacture; this one treats Manufacture as the source of truth and
overwrites the sheet.

Architecture
------------
- Auth via a Google service-account JSON key mounted into the
  container at ``$GOOGLE_SHEETS_CREDENTIALS_PATH`` (default
  ``/run/secrets/sheets_service_account.json``). Service-account
  must be shared on the sheet with Editor permission.
- Target sheet identified by ``$MASTER_STOCK_SHEET_ID`` (the
  document ID, NOT the published-CSV ID), tab name
  ``$MASTER_STOCK_SHEET_TAB`` (default "MASTER STOCK").
- Gated by ``settings.STOCK_PUSH_TO_SHEET_ENABLED`` — same shadow
  pattern as ``SALES_VELOCITY_WRITE_ENABLED``. While False, the
  command logs what it would change but does NOT write. Flip the
  env var to True once you've confirmed the dry-run output.

Sheet layout
------------
The first three rows of the sheet are summary stats + a header row;
see ``import_master_stock_csv`` for the column map. We write to the
columns whose canonical header (in row 3, upper-cased) is one of:

  MASTER         | M-number — natural key, also our lookup
  DESCRIPTION    | Product.description
  BLANK          | Product.blank
  MATERIAL       | Product.material
  STOCK          | StockLevel.current_stock
  IN PROGRESS    | Product.in_progress  (TRUE / blank)

Anything else in the sheet (formulas, comments, the IN/OUT rows
above, formatting) is left untouched. We update cells one row at a
time, keyed on MASTER, so a manual edit elsewhere in the sheet
never gets clobbered.

Conflict handling
-----------------
On every run we first READ the sheet's current MASTER column, build
a map of {m_number → row_index}, and only update existing rows.
M-numbers in Manufacture that aren't yet in the sheet are appended
at the bottom. A future "remove orphans" sweep can take rows that
exist in the sheet but not in Manufacture (out of scope here —
deletes are higher risk and need explicit human confirmation).

Run
---
    python manage.py push_master_stock_sheet [--dry-run] [--limit N]

The first real run will sweep every Product row through the API in
batches. Subsequent runs (when wired to qcluster) only touch rows
that actually changed since the previous push.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


# Column headers we'll touch. Anything not in this set is left alone.
WRITE_COLUMNS = {
    'MASTER',        # natural key — never changed once a row exists
    'DESCRIPTION',
    'BLANK',
    'MATERIAL',
    'STOCK',
    'IN PROGRESS',
}


def _bool_to_cell(v: bool) -> str:
    """In-progress column is 'TRUE' / '' in the sheet."""
    return 'TRUE' if v else ''


class Command(BaseCommand):
    help = (
        'Push Manufacture Product + StockLevel rows back to the Master '
        'Stock Google Sheet. Gated by STOCK_PUSH_TO_SHEET_ENABLED.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would change without writing to the sheet.',
        )
        parser.add_argument(
            '--limit', type=int, default=0,
            help='Cap the number of rows updated (0 = no cap). Useful for '
                 'the first run when verifying behaviour against a subset.',
        )

    def handle(self, *args, **opts):
        from products.models import Product
        from stock.models import StockLevel
        from imports.models import ImportLog

        # ── Config + auth ───────────────────────────────────────────────
        sheet_id = (
            os.environ.get('MASTER_STOCK_SHEET_ID', '')
            or getattr(settings, 'MASTER_STOCK_SHEET_ID', '')
        )
        if not sheet_id:
            raise CommandError(
                'Set MASTER_STOCK_SHEET_ID in the environment '
                '(the document ID from /spreadsheets/d/<ID>/edit, NOT the '
                'published-CSV 2PACX-1v ID).'
            )

        tab = (
            os.environ.get('MASTER_STOCK_SHEET_TAB', '')
            or getattr(settings, 'MASTER_STOCK_SHEET_TAB', '')
            or 'MASTER STOCK'
        )

        creds_path = (
            os.environ.get('GOOGLE_SHEETS_CREDENTIALS_PATH', '')
            or getattr(settings, 'GOOGLE_SHEETS_CREDENTIALS_PATH', '')
            or '/run/secrets/sheets_service_account.json'
        )
        if not os.path.exists(creds_path):
            raise CommandError(
                f'Service-account JSON not found at {creds_path}. '
                f'Mount the key into the container via docker-compose.'
            )

        # Shadow-mode gate. Even with --dry-run NOT passed, we refuse to
        # write unless the env-var flag is on. This prevents an
        # accidental qcluster invocation from clobbering the sheet
        # before we trust the diff logic.
        live = bool(getattr(settings, 'STOCK_PUSH_TO_SHEET_ENABLED', False))
        dry = opts['dry_run'] or not live

        if not live:
            self.stdout.write(self.style.NOTICE(
                'STOCK_PUSH_TO_SHEET_ENABLED is False — running in '
                'dry-run mode regardless of --dry-run flag. Flip the '
                'env var to True to enable real writes.'
            ))

        # ── Open the sheet ──────────────────────────────────────────────
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError as exc:
            raise CommandError(
                f'gspread / google-auth not installed: {exc}. '
                f'Add gspread + google-auth to backend/requirements.txt '
                f'and rebuild the backend image.'
            ) from exc

        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        client = gspread.authorize(creds)

        try:
            spreadsheet = client.open_by_key(sheet_id)
        except gspread.SpreadsheetNotFound:
            raise CommandError(
                f'Sheet {sheet_id} not found by service account. '
                f'Make sure the sheet is shared with '
                f'{creds.service_account_email} as Editor.'
            )

        try:
            worksheet = spreadsheet.worksheet(tab)
        except gspread.WorksheetNotFound:
            available = [w.title for w in spreadsheet.worksheets()]
            raise CommandError(
                f'Tab "{tab}" not found. Available tabs: {available}'
            )

        # ── Read existing sheet state ───────────────────────────────────
        self.stdout.write(f'Reading current sheet state from "{tab}"…')
        all_rows = worksheet.get_all_values()
        if len(all_rows) < 4:
            raise CommandError(
                f'Sheet only has {len(all_rows)} rows; expected at least 4 '
                f'(2 summary rows, 1 header row, then data).'
            )

        header_row_idx = 2  # zero-based; row 3 in human terms
        header = all_rows[header_row_idx]
        col_index = {
            str(v).strip().upper(): i
            for i, v in enumerate(header)
            if v and str(v).strip()
        }

        missing = WRITE_COLUMNS - set(col_index)
        if missing:
            raise CommandError(
                f'Sheet header missing required columns: {sorted(missing)}. '
                f'Found: {sorted(col_index)}'
            )

        # Build {m_number → 1-based sheet row index}.
        master_col = col_index['MASTER']
        existing_rows: dict[str, int] = {}
        for i, row in enumerate(all_rows[header_row_idx + 1:], start=header_row_idx + 2):
            if len(row) <= master_col:
                continue
            m = str(row[master_col] or '').strip().upper()
            if m:
                existing_rows[m] = i  # 1-based row in the sheet

        self.stdout.write(
            f'  sheet has {len(existing_rows)} M-numbered rows '
            f'(of {len(all_rows) - header_row_idx - 1} data rows total)'
        )

        # ── Pull Manufacture state ──────────────────────────────────────
        products = (
            Product.objects.filter(active=True)
            .select_related('stock')
            .order_by('m_number')
        )
        manufacture_state: dict[str, dict[str, Any]] = {}
        for p in products:
            m = (p.m_number or '').strip().upper()
            if not m:
                continue
            stock = getattr(p, 'stock', None)
            manufacture_state[m] = {
                'DESCRIPTION': p.description or '',
                'BLANK':       p.blank or '',
                'MATERIAL':    p.material or '',
                'STOCK':       str(stock.current_stock) if stock else '0',
                'IN PROGRESS': _bool_to_cell(bool(p.in_progress)),
            }

        self.stdout.write(f'  Manufacture has {len(manufacture_state)} active Products')

        # ── Diff ────────────────────────────────────────────────────────
        updates: list[tuple[int, str, str, str]] = []   # (row, col_letter, old, new)
        appends: list[list[str]] = []
        unchanged = 0

        def col_letter(i: int) -> str:
            # Zero-based column index → A1 letter (e.g. 0 → A, 26 → AA).
            letters = ''
            n = i + 1
            while n:
                n, rem = divmod(n - 1, 26)
                letters = chr(65 + rem) + letters
            return letters

        for m, fields in manufacture_state.items():
            row_idx = existing_rows.get(m)
            if row_idx is None:
                # Build a sparse row in the sheet's column order. Only
                # fill the cells we own — leave everything else blank
                # so any sheet-side formulas in those columns recompute.
                new_row = ['' for _ in header]
                new_row[col_index['MASTER']] = m
                for header_name, value in fields.items():
                    col = col_index[header_name]
                    new_row[col] = value
                appends.append(new_row)
                continue

            existing_row = all_rows[row_idx - 1]
            for header_name, new_val in fields.items():
                col = col_index[header_name]
                old_val = existing_row[col] if col < len(existing_row) else ''
                if str(old_val).strip() == str(new_val).strip():
                    continue
                updates.append((row_idx, col_letter(col), old_val, new_val))

            if not any(
                u[0] == row_idx for u in updates[-len(fields):]
            ):
                unchanged += 1

        self.stdout.write('')
        self.stdout.write(
            f'Push summary: {len(updates)} cell updates across '
            f'{len({u[0] for u in updates})} rows, '
            f'{len(appends)} new rows to append, '
            f'{unchanged} unchanged'
        )

        if opts['limit']:
            cap = opts['limit']
            updates = updates[:cap]
            appends = appends[:max(0, cap - len(updates))]
            self.stdout.write(self.style.NOTICE(
                f'  --limit {cap}: capping at {len(updates)} updates '
                f'+ {len(appends)} appends'
            ))

        if dry:
            self.stdout.write(self.style.NOTICE(
                f'\n[DRY-RUN — STOCK_PUSH_TO_SHEET_ENABLED='
                f'{getattr(settings, "STOCK_PUSH_TO_SHEET_ENABLED", False)}]'
            ))
            for row, col, old, new in updates[:20]:
                self.stdout.write(f'  row {row} col {col}: {old!r} -> {new!r}')
            if len(updates) > 20:
                self.stdout.write(f'  … and {len(updates) - 20} more')
            for new_row in appends[:5]:
                self.stdout.write(f'  APPEND: {new_row}')
            if len(appends) > 5:
                self.stdout.write(f'  … and {len(appends) - 5} more appends')
            return

        # ── Real write ──────────────────────────────────────────────────
        if updates:
            # gspread batch_update accepts a list of {range, values}.
            payload = [
                {'range': f'{tab}!{col}{row}', 'values': [[new]]}
                for row, col, _, new in updates
            ]
            worksheet.batch_update(payload, value_input_option='USER_ENTERED')
            self.stdout.write(self.style.SUCCESS(
                f'  wrote {len(updates)} cell updates'
            ))

        if appends:
            worksheet.append_rows(
                appends, value_input_option='USER_ENTERED',
                table_range=f'{tab}!A{header_row_idx + 1}',
            )
            self.stdout.write(self.style.SUCCESS(
                f'  appended {len(appends)} new rows'
            ))

        # Audit trail in ImportLog (existing model).
        try:
            ImportLog.objects.create(
                import_type='master_stock_push',
                row_count=len(updates) + len(appends),
                # Avoid blob/JSON columns we don't know exist; the existing
                # import_master_stock_csv uses a similar minimal entry.
            )
        except Exception as exc:  # noqa: BLE001 — audit log is best-effort
            logger.warning('push_master_stock_sheet: ImportLog write failed: %s', exc)
