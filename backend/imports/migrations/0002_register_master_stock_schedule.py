"""
Register a Django-Q2 Schedule for the Master Stock sheet pull.

Runs every 5 minutes, calls
imports.management.commands.sync_master_stock_sheet.run_master_stock_sheet_sync
which in turn invokes the management command, which fetches the
published CSV and delegates to import_master_stock_csv.

Idempotent: get_or_create on the schedule name. Re-applying this
migration on an existing deploy is a no-op.

Why pull, not push: as of 2026-05-12 the Google Sheet is the source
of truth for warehouse stock. Manufacture follows the sheet. When
Toby flips the source of truth, this schedule should either be
deleted or paired with the push schedule (set STOCK_PUSH_TO_SHEET_ENABLED=True).
"""
from datetime import timedelta

from django.db import migrations
from django.utils import timezone


SCHEDULE_NAME = 'master_stock_sheet_sync_5min'
FUNC_PATH = (
    'imports.management.commands.sync_master_stock_sheet.'
    'run_master_stock_sheet_sync'
)


def register_schedule(apps, schema_editor):
    try:
        from django_q.models import Schedule
    except ImportError:
        # Dev environments without django-q installed — schedule
        # registration is a no-op and the cron-equivalent simply
        # doesn't run.
        return

    Schedule.objects.get_or_create(
        name=SCHEDULE_NAME,
        defaults={
            'func': FUNC_PATH,
            'schedule_type': Schedule.MINUTES,
            'minutes': 5,
            'next_run': timezone.now() + timedelta(minutes=2),
            'repeats': -1,
        },
    )


def unregister_schedule(apps, schema_editor):
    try:
        from django_q.models import Schedule
    except ImportError:
        return
    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('imports', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(register_schedule, unregister_schedule),
    ]
