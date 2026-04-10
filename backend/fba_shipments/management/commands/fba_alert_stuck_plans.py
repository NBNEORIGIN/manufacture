"""
Alert on stuck or errored FBA shipment plans.

Intended to be run on a cron/systemd-timer from the Hetzner host (or via
Django-Q's built-in Schedule model) every 15 minutes. Sends a single email
summarising every plan that is either:

  * in 'error' status — workflow was halted by an unhandled exception; or
  * in a non-terminal, non-paused 'waiting' status but hasn't polled in
    the last FBA_STUCK_THRESHOLD_MINUTES minutes (default: 30). This catches
    the case where the Django-Q cluster died mid-task and no task was re-
    enqueued to pick up the workflow.

Does nothing (exits 0) if no plans are stuck or errored.

Uses the same SMTP_* settings + sendmail pattern as core.views_bugreport,
so no new dependencies. Recipient comes from settings.FBA_ALERT_RECIPIENT.

Usage:
    python manage.py fba_alert_stuck_plans
    python manage.py fba_alert_stuck_plans --threshold-minutes 15
    python manage.py fba_alert_stuck_plans --dry-run
"""

from __future__ import annotations

import smtplib
from datetime import timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from fba_shipments.models import FBAShipmentPlan


# These statuses mean "we've sent work to Amazon, we expect a poll to tick"
# — so if we don't see a recent last_polled_at, something is wrong.
WAITING_STATUSES = {
    'plan_creating',
    'packing_options_generating',
    'packing_info_setting',
    'packing_option_confirming',
    'placement_options_generating',
    'placement_option_confirming',
    'transport_options_generating',
    'delivery_window_generating',
    'transport_confirming',
}

DEFAULT_THRESHOLD_MINUTES = 30


class Command(BaseCommand):
    help = 'Email alert for stuck or errored FBA shipment plans.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--threshold-minutes',
            type=int,
            default=DEFAULT_THRESHOLD_MINUTES,
            help=(
                'Minutes since last_polled_at before a waiting plan is '
                'flagged as stuck (default: 30).'
            ),
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print the email body instead of sending it.',
        )

    def handle(self, *args, **opts):
        threshold = opts['threshold_minutes']
        dry_run = opts['dry_run']
        cutoff = timezone.now() - timedelta(minutes=threshold)

        errored = list(
            FBAShipmentPlan.objects
            .filter(status='error')
            .order_by('updated_at')
        )

        # "stuck" = in a waiting state but hasn't had a poll in threshold minutes.
        # last_polled_at=None counts as stuck iff the plan is older than threshold
        # (otherwise it's just freshly enqueued and hasn't had a chance yet).
        stuck_waiting = list(
            FBAShipmentPlan.objects
            .filter(status__in=WAITING_STATUSES)
            .filter(updated_at__lt=cutoff)
            .exclude(last_polled_at__gte=cutoff)
            .order_by('updated_at')
        )

        if not errored and not stuck_waiting:
            self.stdout.write('No stuck or errored plans.')
            return

        lines_err = [
            self._fmt_plan(p, kind='error') for p in errored
        ]
        lines_stuck = [
            self._fmt_plan(p, kind='stuck') for p in stuck_waiting
        ]

        subject = (
            f'[Manufacture] FBA plans need attention: '
            f'{len(errored)} error, {len(stuck_waiting)} stuck'
        )

        html_body = self._render_html(
            errored_rows=lines_err,
            stuck_rows=lines_stuck,
            threshold=threshold,
        )

        if dry_run:
            self.stdout.write(self.style.WARNING('[DRY RUN] Would send:'))
            self.stdout.write(f'Subject: {subject}')
            self.stdout.write(html_body)
            return

        self._send(subject=subject, html=html_body)
        self.stdout.write(
            self.style.SUCCESS(
                f'Alert sent: {len(errored)} error, {len(stuck_waiting)} stuck'
            )
        )

    # -------------------------------------------------------------------- #
    # Helpers                                                              #
    # -------------------------------------------------------------------- #

    def _fmt_plan(self, plan: FBAShipmentPlan, kind: str) -> dict:
        last_error = ''
        if plan.error_log:
            last = plan.error_log[-1] if isinstance(plan.error_log, list) else {}
            last_error = f"{last.get('step', '?')}: {last.get('message', '')}"
        return {
            'id': plan.id,
            'name': plan.name,
            'marketplace': plan.marketplace,
            'status': plan.status,
            'kind': kind,
            'last_polled_at': (
                plan.last_polled_at.isoformat() if plan.last_polled_at else '—'
            ),
            'updated_at': plan.updated_at.isoformat(),
            'error': last_error,
            'inbound_plan_id': plan.inbound_plan_id or '—',
        }

    def _render_html(
        self,
        errored_rows: list[dict],
        stuck_rows: list[dict],
        threshold: int,
    ) -> str:
        def row_html(row: dict, colour: str) -> str:
            return (
                f'<tr style="border-bottom:1px solid #ddd;">'
                f'<td style="padding:6px;color:{colour};font-weight:bold;">{row["kind"]}</td>'
                f'<td style="padding:6px;font-family:monospace;">#{row["id"]}</td>'
                f'<td style="padding:6px;">{row["name"]}</td>'
                f'<td style="padding:6px;">{row["marketplace"]}</td>'
                f'<td style="padding:6px;font-family:monospace;font-size:11px;">{row["status"]}</td>'
                f'<td style="padding:6px;font-family:monospace;font-size:11px;">{row["inbound_plan_id"]}</td>'
                f'<td style="padding:6px;font-size:11px;">{row["last_polled_at"]}</td>'
                f'<td style="padding:6px;font-size:11px;color:#900;">{row["error"]}</td>'
                f'</tr>'
            )

        all_rows = (
            [row_html(r, '#c00') for r in errored_rows]
            + [row_html(r, '#a60') for r in stuck_rows]
        )

        return f"""
        <html><body>
        <h2>FBA plans need attention</h2>
        <p>
          {len(errored_rows)} errored plan(s), {len(stuck_rows)} stuck plan(s)
          (no poll in last {threshold} minutes).
        </p>
        <table style="border-collapse:collapse;width:100%;max-width:1000px;font-size:13px;">
          <thead>
            <tr style="background:#eee;">
              <th style="padding:6px;text-align:left;">Kind</th>
              <th style="padding:6px;text-align:left;">ID</th>
              <th style="padding:6px;text-align:left;">Name</th>
              <th style="padding:6px;text-align:left;">Market</th>
              <th style="padding:6px;text-align:left;">Status</th>
              <th style="padding:6px;text-align:left;">Inbound plan</th>
              <th style="padding:6px;text-align:left;">Last poll</th>
              <th style="padding:6px;text-align:left;">Last error</th>
            </tr>
          </thead>
          <tbody>
            {''.join(all_rows)}
          </tbody>
        </table>
        <p style="color:#666;font-size:12px;">
          Open /fba/&lt;id&gt; on the Manufacture UI to retry or cancel.
        </p>
        </body></html>
        """

    def _send(self, *, subject: str, html: str) -> None:
        smtp_host = getattr(settings, 'SMTP_HOST', '')
        smtp_port = int(getattr(settings, 'SMTP_PORT', 587))
        smtp_user = getattr(settings, 'SMTP_USER', '')
        smtp_pass = getattr(settings, 'SMTP_PASSWORD', '')
        recipient = getattr(settings, 'FBA_ALERT_RECIPIENT', '')

        if not smtp_user or not smtp_pass:
            self.stderr.write(
                self.style.WARNING('SMTP not configured — skipping send.')
            )
            return
        if not recipient:
            self.stderr.write(
                self.style.WARNING('FBA_ALERT_RECIPIENT not set — skipping send.')
            )
            return

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = smtp_user
        msg['To'] = recipient
        msg.attach(MIMEText(html, 'html'))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [recipient], msg.as_string())
