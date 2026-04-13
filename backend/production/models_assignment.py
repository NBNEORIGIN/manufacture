"""
Job assignment model — Ivan review #8, items 1+2.

Temporary scaffolding for the assignment/inbox/notification feature.
Ivan explicitly said "this table is temporary and we will get rid of
it, or remake it." The model is intentionally simple so it can be
replaced or extended later without a painful migration.
"""
from django.db import models

from core.models import TimestampedModel


class JobAssignment(TimestampedModel):
    """A product assigned to a user to make."""

    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='assignments',
    )
    assigned_to = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='assigned_jobs',
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
    # Track whether the assignee has seen the notification
    seen = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return (
            f'{self.product.m_number} x{self.quantity} '
            f'-> {self.assigned_to.username} [{self.status}]'
        )
