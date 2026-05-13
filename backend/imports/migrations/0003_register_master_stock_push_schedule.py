"""
Register a Django-Q2 Schedule for the Master Stock sheet PUSH direction.

Pairs with 0002_register_master_stock_schedule (the pull). The two
schedules together give bidirectional sync between Manufacture and
the Master Stock Google Sheet:

  pull (every 5 min): sheet → Manufacture
  push (every 2 min): Manufacture → sheet

Push runs more frequently so app edits propagate quickly. The push
command itself is no-op until STOCK_PUSH_TO_SHEET_ENABLED=True (see
push_master_stock_sheet command), so this schedule is safe to
register on every deploy.

Race window: if both sides edit the same row within a ~2-minute
window, the last writer wins. NBNE's edit volume is low enough that
this is unlikely to surface in practice; per-row conflict arbitration
can be added later if needed.

Idempotent: get_or_create on schedule name.
"""
from datetime import timedelta

from django.db import migrations
from django.utils import timezone


SCHEDULE_NAME = 'master_stock_sheet_push_2min'
FUNC_PATH = (
    'imports.management.commands.push_master_stock_sheet.'
    'run_master_stock_sheet_push'
)


def register_schedule(apps, schema_editor):
    try:
        from django_q.models import Schedule
    except ImportError:
        return

    Schedule.objects.get_or_create(
        name=SCHEDULE_NAME,
        defaults={
            'func': FUNC_PATH,
            'schedule_type': Schedule.MINUTES,
            'minutes': 2,
            'next_run': timezone.now() + timedelta(minutes=1),
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
        ('imports', '0002_register_master_stock_schedule'),
    ]

    operations = [
        migrations.RunPython(register_schedule, unregister_schedule),
    ]
