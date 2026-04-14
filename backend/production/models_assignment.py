"""
Job assignment model — Ivan review #8, items 1+2; review #11 item 3.

Temporary scaffolding for the assignment/inbox/notification feature.
Ivan explicitly said "this table is temporary and we will get rid of
it, or remake it." The model is intentionally simple so it can be
replaced or extended later without a painful migration.

Review #11: up to 4 users per assignment via JobAssignmentUser through model.
"""
from django.db import models

from core.models import TimestampedModel


class JobAssignment(TimestampedModel):
    """A product assigned to one or more users to make."""

    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='assignments',
    )
    assigned_by = models.ForeignKey(
        'auth.User',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='jobs_assigned_out',
    )
    quantity = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=[('pending', 'Pending'), ('completed', 'Completed')],
        default='pending',
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        names = ', '.join(
            au.user.username for au in self.assignment_users.select_related('user')[:2]
        )
        return (
            f'{self.product.m_number} x{self.quantity} '
            f'-> {names or "unassigned"} [{self.status}]'
        )


class JobAssignmentUser(models.Model):
    """Through model: one user assigned to one assignment, with per-user seen flag."""

    assignment = models.ForeignKey(
        JobAssignment,
        on_delete=models.CASCADE,
        related_name='assignment_users',
    )
    user = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='job_assignment_links',
    )
    seen = models.BooleanField(default=False)

    class Meta:
        unique_together = [('assignment', 'user')]
        ordering = ['pk']

    def __str__(self):
        return f'{self.user.username} on assignment #{self.assignment_id}'
