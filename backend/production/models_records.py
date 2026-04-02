from django.db import models
from django.contrib.auth.models import User
from core.models import TimestampedModel


class ProductionRecord(TimestampedModel):
    """
    Historical production log — tracks what was printed, errors, and machine used.
    Imported from RECORDS sheet and created going forward from production orders.
    """
    date = models.DateField(db_index=True)
    week_number = models.IntegerField(null=True, blank=True)
    product = models.ForeignKey(
        'products.Product', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='production_records',
    )
    sku = models.CharField(max_length=100, blank=True, db_index=True)
    number_printed = models.IntegerField(default=0)
    errors = models.IntegerField(default=0)
    total_made = models.IntegerField(default=0)
    machine = models.CharField(max_length=50, blank=True, db_index=True)
    failure_reason = models.TextField(blank=True)
    correction = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
    )

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        product_ref = self.product.m_number if self.product else self.sku
        return f'{self.date}: {product_ref} — {self.total_made} made, {self.errors} errors'

    @property
    def error_rate(self):
        if self.number_printed == 0:
            return 0
        return round(self.errors / self.number_printed * 100, 1)
