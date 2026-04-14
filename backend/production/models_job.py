"""
Multi-step threaded job model (Ivan review #10, item 5).

A Job has an ordered sequence of JobSteps. Each step is assigned to a
user. Steps execute sequentially: step 1 starts as 'active', others
start as 'waiting'. When step N completes, step N+1 becomes 'active'
and the assignee is notified. When the last step completes, the whole
Job is marked 'completed'.

Permission rules:
- Only the job creator or the step's assigned user can mark a step
  as completed.
- All users mentioned across all steps receive a notification at job
  creation time.

The existing JobAssignment model from review #8 is kept for simple
one-shot assignments. Jobs are for multi-step workflows. They coexist
— the inbox polls both.
"""
from django.db import models
from django.contrib.auth.models import User

from core.models import TimestampedModel


class Job(TimestampedModel):
    """A multi-step job container."""

    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='jobs',
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_jobs',
    )
    title = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('in_progress', 'In Progress'),
            ('completed', 'Completed'),
        ],
        default='pending',
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Job #{self.pk}: {self.product.m_number} [{self.status}]'

    @property
    def current_step(self):
        """Return the currently active step, or None if all done."""
        return self.steps.filter(status='active').first()

    @property
    def step_chain_display(self) -> str:
        """
        Reddit-style thread display: "ivan -> ben -> toby"
        """
        steps = self.steps.select_related('assigned_to').order_by('step_number')
        from core.auth_views import _display_name
        parts = []
        for s in steps:
            name = _display_name(s.assigned_to)
            if s.status == 'completed':
                parts.append(f'[{name}]')
            elif s.status == 'active':
                parts.append(f'**{name}**')
            else:
                parts.append(name)
        return ' -> '.join(parts)


class JobStep(TimestampedModel):
    """One step in a multi-step job."""

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='steps')
    step_number = models.PositiveIntegerField()
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='job_steps',
    )
    description = models.TextField(blank=True, help_text='What this person needs to do')
    status = models.CharField(
        max_length=20,
        choices=[
            ('waiting', 'Waiting'),
            ('active', 'Active'),
            ('completed', 'Completed'),
        ],
        default='waiting',
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        User,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='completed_steps',
    )
    # Track whether the assignee has seen the "your step is now active" notification
    seen = models.BooleanField(default=False)

    class Meta:
        ordering = ['job', 'step_number']
        unique_together = [('job', 'step_number')]

    def __str__(self):
        from core.auth_views import _display_name
        return f'Step {self.step_number}: {_display_name(self.assigned_to)} [{self.status}]'
