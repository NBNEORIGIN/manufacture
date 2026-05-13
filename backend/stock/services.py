"""
Stock authority service — single source of truth for "who owns stock data?"

Two phases of the Manufacture/Master-Stock-sheet integration:

1. Sheet is authoritative (current state, 2026-05-13).
   - Pull runs every 5 minutes via qcluster (master_stock_sheet_sync_5min)
   - Manufacture's StockLevel.current_stock is a 5-min-old read-only copy
   - Any app-side write to current_stock gets silently reverted on next pull
   - Therefore: refuse stock writes at the API layer so the user gets
     a clear "this happens in the sheet" message instead of doing
     work that vanishes 5 minutes later.

2. Manufacture is authoritative (post-cutover — see master_stock_cutover_playbook).
   - Pull schedule deleted; push (push_master_stock_sheet) enabled
   - App writes flow to the sheet within 5 minutes
   - This gate returns True; existing stock-write code paths run as normal.

Toggle: settings.STOCK_PUSH_TO_SHEET_ENABLED. Same env var used by
the push command — keeps the two halves of the cutover paired so
they can't get out of step.
"""
from __future__ import annotations

from django.conf import settings


STOCK_READONLY_MSG = (
    'Stock changes happen in the Master Stock Google Sheet, not in '
    'Manufacture. Edit the sheet and the change will reflect in the '
    'app within 5 minutes.'
)

STOCK_READONLY_ERROR_CODE = 'stock_readonly'


def stock_writes_allowed() -> bool:
    """
    True when Manufacture is authoritative for stock counts.

    While the Master Stock Google Sheet is the source of truth (current
    state), this returns False and the API layer rejects writes to
    StockLevel.current_stock. Flipping STOCK_PUSH_TO_SHEET_ENABLED=True
    via the cutover playbook makes Manufacture canonical.
    """
    return bool(getattr(settings, 'STOCK_PUSH_TO_SHEET_ENABLED', False))
