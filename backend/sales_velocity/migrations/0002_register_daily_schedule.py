"""
Register Django-Q Schedule entries for the sales_velocity aggregator
and its post-cutover sanity + purge jobs.

- Daily aggregation: 04:17 UTC, after FNSKU sync (03:00) and FBA
  reconciliation (hourly). First DAILY-type Schedule in the manufacture
  codebase — other recurring work (FBA stuck-plan alerts) still runs
  via host cron per the Deployment Runbook in CLAUDE.md.
- Weekly sanity check: Mondays at 06:42 UTC.
- Weekly audit log purge: Sundays at 05:07 UTC.

All are idempotent via get_or_create on the schedule name.
"""
from __future__ import annotations

from datetime import datetime, timezone

from django.db import migrations


def _next_daily_04_17() -> datetime:
    """Return the next 04:17 UTC after now."""
    now = datetime.now(timezone.utc)
    candidate = now.replace(hour=4, minute=17, second=0, microsecond=0)
    if candidate <= now:
        from datetime import timedelta
        candidate += timedelta(days=1)
    return candidate


def _next_monday_06_42() -> datetime:
    """Return the next Monday 06:42 UTC after now."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    # Monday is weekday 0
    days_ahead = (0 - now.weekday()) % 7
    if days_ahead == 0:
        # Already Monday — schedule next Monday if we're past 06:42
        today_target = now.replace(hour=6, minute=42, second=0, microsecond=0)
        if now > today_target:
            days_ahead = 7
    candidate = (now + timedelta(days=days_ahead)).replace(
        hour=6, minute=42, second=0, microsecond=0,
    )
    return candidate


def _next_sunday_05_07() -> datetime:
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    # Sunday is weekday 6
    days_ahead = (6 - now.weekday()) % 7
    if days_ahead == 0:
        today_target = now.replace(hour=5, minute=7, second=0, microsecond=0)
        if now > today_target:
            days_ahead = 7
    candidate = (now + timedelta(days=days_ahead)).replace(
        hour=5, minute=7, second=0, microsecond=0,
    )
    return candidate


def register_schedules(apps, schema_editor):
    """Create the Schedule rows if they don't already exist."""
    try:
        from django_q.models import Schedule
    except ImportError:
        # Django-Q not installed — migration still runs but no schedule
        # is registered. Developer local runs without Django-Q are OK.
        return

    Schedule.objects.get_or_create(
        name='sales_velocity_daily_refresh',
        defaults={
            'func': 'sales_velocity.services.aggregator.run_daily_aggregation',
            'schedule_type': Schedule.DAILY,
            'next_run': _next_daily_04_17(),
        },
    )

    Schedule.objects.get_or_create(
        name='sales_velocity_weekly_sanity',
        defaults={
            'func': 'sales_velocity.services.aggregator.run_weekly_sanity_check',
            'schedule_type': Schedule.WEEKLY,
            'next_run': _next_monday_06_42(),
        },
    )

    Schedule.objects.get_or_create(
        name='sales_velocity_purge_audit',
        defaults={
            'func': 'sales_velocity.services.aggregator.purge_audit_log',
            'schedule_type': Schedule.WEEKLY,
            'next_run': _next_sunday_05_07(),
        },
    )


def unregister_schedules(apps, schema_editor):
    """Delete the Schedule rows if they exist."""
    try:
        from django_q.models import Schedule
    except ImportError:
        return

    Schedule.objects.filter(name__in=[
        'sales_velocity_daily_refresh',
        'sales_velocity_weekly_sanity',
        'sales_velocity_purge_audit',
    ]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('sales_velocity', '0001_initial'),
        # Depend on django_q so the Schedule table exists when this runs.
        ('django_q', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(register_schedules, unregister_schedules),
    ]
