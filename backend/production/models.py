from django.db import models
from django.contrib.auth.models import User
from core.models import TimestampedModel
from .models_records import ProductionRecord  # noqa: F401 — register model
from .models_assignment import JobAssignment  # noqa: F401 — register model


class ProductionOrder(TimestampedModel):
    product = models.ForeignKey(
        'products.Product', on_delete=models.CASCADE, related_name='production_orders'
    )
    quantity = models.IntegerField()
    priority = models.IntegerField(default=0)
    machine = models.CharField(max_length=50, blank=True, db_index=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='created_orders'
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    SIMPLE_STAGE_CHOICES = [
        ('on_bench', 'On the bench'),
        ('in_process', 'In process'),
    ]
    simple_stage = models.CharField(
        max_length=20, choices=SIMPLE_STAGE_CHOICES, null=True, blank=True
    )

    class Meta:
        ordering = ['-priority', '-created_at']

    def __str__(self):
        return f'PO-{self.id}: {self.product.m_number} x{self.quantity}'

    @property
    def is_complete(self):
        return self.completed_at is not None

    @property
    def current_stage(self):
        last = self.stages.filter(completed=True).order_by('-completed_at').first()
        if last:
            return last.stage
        return 'pending'


class ProductionStage(models.Model):
    STAGE_CHOICES = [
        ('designed', 'Designed'),
        ('printed', 'Printed'),
        ('heat_press', 'Heat Press'),
        ('laminate', 'Laminate'),
        ('processed', 'Processed'),
        ('cut', 'Cut'),
        ('labelled', 'Labelled'),
        ('packed', 'Packed'),
        ('shipped', 'Shipped'),
    ]

    order = models.ForeignKey(
        ProductionOrder, on_delete=models.CASCADE, related_name='stages'
    )
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, db_index=True)
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='completed_stages'
    )

    class Meta:
        ordering = ['order', 'id']
        unique_together = [['order', 'stage']]

    def __str__(self):
        status = 'done' if self.completed else 'pending'
        return f'{self.order} — {self.get_stage_display()} ({status})'
