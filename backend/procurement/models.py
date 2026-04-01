from django.db import models
from core.models import TimestampedModel


class Material(TimestampedModel):
    material_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True)
    unit_of_measure = models.CharField(max_length=50, blank=True)
    current_stock = models.IntegerField(default=0)
    reorder_point = models.IntegerField(default=0)
    standard_order_quantity = models.IntegerField(default=0)
    preferred_supplier = models.CharField(max_length=200, blank=True)
    product_page_url = models.URLField(blank=True, max_length=500)
    lead_time_days = models.IntegerField(default=0)
    safety_stock = models.IntegerField(default=0)
    in_house_description = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    current_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.material_id}: {self.name}'

    @property
    def needs_reorder(self):
        return self.current_stock <= self.reorder_point
