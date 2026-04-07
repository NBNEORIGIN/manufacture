from django.db import models
from core.models import TimestampedModel


class Product(TimestampedModel):
    m_number = models.CharField(max_length=10, unique=True, db_index=True)
    description = models.CharField(max_length=500)
    blank = models.CharField(max_length=50, db_index=True)
    material = models.CharField(max_length=100, blank=True)
    is_personalised = models.BooleanField(default=False)
    do_not_restock = models.BooleanField(default=False)
    do_not_restock_reason = models.TextField(blank=True)
    image_url = models.URLField(blank=True, max_length=500)
    active = models.BooleanField(default=True, db_index=True)
    in_progress = models.BooleanField(default=False)
    has_design = models.BooleanField(default=False, help_text='Design file is ready for this product')

    class Meta:
        ordering = ['m_number']

    def __str__(self):
        return f'{self.m_number} — {self.description[:60]}'


class SKU(TimestampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='skus')
    sku = models.CharField(max_length=100, db_index=True)
    new_sku = models.CharField(max_length=100, blank=True)
    asin = models.CharField(max_length=20, blank=True, db_index=True)
    fnsku = models.CharField(max_length=20, blank=True)
    channel = models.CharField(max_length=30, db_index=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['product__m_number', 'channel']
        unique_together = [['sku', 'channel']]

    def __str__(self):
        return f'{self.sku} ({self.channel}) → {self.product.m_number}'
