"""
Multi-step threaded job model (Ivan review #10, item 5; #11 items 3-6).

A Job has an ordered sequence of JobSteps. Each step is assigned to one
or more users (up to 4). Steps execute sequentially: step 1 starts as
'active', others start as 'waiting'. When step N completes, step N+1
becomes 'active' and the assignees are notified. When the last step
completes, the whole Job is marked 'completed'.

Permission rules:
- Only the job creator or one of the step's assigned users can mark a
  step as completed.
- All users mentioned across all steps receive a notification at job
  creation time.

Review #11 changes:
- product FK removed (M-number field removed from UI, title is the anchor)
- Multi-user per step via JobStepUser through model
- Description field on each step shown in expanded view
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
        null=True, blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_jobs',
    )
    title = models.CharField(max_length=200)
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
        return f'Job #{self.pk}: {self.title} [{self.status}]'

    @property
    def current_step(self):
        """Return the currently active step, or None if all done."""
        return self.steps.filter(status='active').first()

    @property
    def step_chain_display(self) -> str:
        """
        Reddit-style thread display: "Ivan -> Ben -> Toby"
        Multi-user steps show "Ivan, Ben" etc.
        """
        steps = self.steps.prefetch_related('step_users__user').order_by('step_number')
        from core.auth_views import _display_name
        parts = []
        for s in steps:
            names = ', '.join(
                _display_name(su.user) for su in s.step_users.select_related('user').all()
            )
            name = names or 'unassigned'
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

    class Meta:
        ordering = ['job', 'step_number']
        unique_together = [('job', 'step_number')]

    def __str__(self):
        from core.auth_views import _display_name
        names = ', '.join(
            _display_name(su.user)
            for su in self.step_users.select_related('user').all()
        )
        return f'Step {self.step_number}: {names or "unassigned"} [{self.status}]'


class JobStepUser(models.Model):
    """Through model: one user assigned to one step, with per-user seen flag."""

    step = models.ForeignKey(
        JobStep,
        on_delete=models.CASCADE,
        related_name='step_users',
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='job_step_links',
    )
    seen = models.BooleanField(default=False)

    class Meta:
        unique_together = [('step', 'user')]
        ordering = ['pk']

    def __str__(self):
        return f'{self.user.username} on step #{self.step_id}'
