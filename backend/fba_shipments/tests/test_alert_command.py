"""
Tests for the `fba_alert_stuck_plans` management command.

Covers the three classification branches:
  * 'error' status → always alerted
  * waiting status + stale last_polled_at → alerted as stuck
  * waiting status + fresh last_polled_at → NOT alerted
  * non-terminal draft / paused statuses → NOT alerted
"""

from __future__ import annotations

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from fba_shipments.models import FBAShipmentPlan


@pytest.fixture(autouse=True)
def patched_kickoff():
    """Prevent real Django-Q tasks firing in tests that create plans."""
    with patch('fba_shipments.services.workflow.kick_off'):
        yield


def _make_plan(**overrides):
    defaults = dict(
        name='Test plan',
        marketplace='UK',
        status='draft',
        ship_from_address={},
    )
    defaults.update(overrides)
    return FBAShipmentPlan.objects.create(**defaults)


def _run(**kwargs):
    """Run the command and capture stdout."""
    out = StringIO()
    call_command(
        'fba_alert_stuck_plans',
        dry_run=True,
        stdout=out,
        **kwargs,
    )
    return out.getvalue()


@pytest.mark.django_db
class TestFbaAlertStuckPlans:
    def test_no_plans_emits_no_alert(self):
        out = _run()
        assert 'No stuck or errored plans' in out

    def test_draft_is_not_flagged(self):
        _make_plan(status='draft')
        out = _run()
        assert 'No stuck or errored plans' in out

    def test_paused_is_not_flagged(self):
        # Paused states are waiting for the user, not the workflow
        _make_plan(status='packing_options_ready')
        _make_plan(status='placement_options_ready')
        _make_plan(status='labels_ready')
        out = _run()
        assert 'No stuck or errored plans' in out

    def test_error_status_is_flagged(self):
        p = _make_plan(
            status='error',
            error_log=[
                {'step': 'create_plan', 'message': 'kaboom', 'exc_type': 'RuntimeError'}
            ],
        )
        out = _run()
        assert 'No stuck or errored plans' not in out
        assert f'#{p.id}' in out
        assert 'kaboom' in out

    def test_fresh_waiting_plan_is_not_flagged(self):
        p = _make_plan(status='plan_creating')
        p.last_polled_at = timezone.now()
        p.save()
        out = _run()
        assert 'No stuck or errored plans' in out

    def test_stale_waiting_plan_is_flagged(self):
        p = _make_plan(status='plan_creating')
        stale = timezone.now() - timedelta(hours=2)
        # Need to bypass auto_now by using update()
        FBAShipmentPlan.objects.filter(pk=p.pk).update(
            last_polled_at=stale,
            updated_at=stale,
        )
        out = _run()
        assert 'No stuck or errored plans' not in out
        assert f'#{p.id}' in out

    def test_waiting_plan_with_never_polled_but_recent_update_is_not_flagged(self):
        # A plan that was just enqueued but hasn't had a chance to poll yet
        # should NOT be flagged — it's not stuck, it's just new.
        p = _make_plan(status='plan_creating')
        assert p.last_polled_at is None
        out = _run()
        assert 'No stuck or errored plans' in out

    def test_threshold_override(self):
        # A plan 20 minutes stale should NOT trigger at --threshold-minutes 30
        # but SHOULD at --threshold-minutes 10.
        p = _make_plan(status='plan_creating')
        stale = timezone.now() - timedelta(minutes=20)
        FBAShipmentPlan.objects.filter(pk=p.pk).update(
            last_polled_at=stale,
            updated_at=stale,
        )
        out30 = _run(threshold_minutes=30)
        assert 'No stuck or errored plans' in out30
        out10 = _run(threshold_minutes=10)
        assert f'#{p.id}' in out10

    def test_dry_run_does_not_send(self):
        _make_plan(status='error', error_log=[{'step': 's', 'message': 'x'}])
        with patch('smtplib.SMTP') as smtp_mock:
            _run()
            smtp_mock.assert_not_called()
