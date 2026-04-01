from django.db import models
from django.contrib.auth.models import User
from core.models import TimestampedModel


class Shipment(TimestampedModel):
    COUNTRY_CHOICES = [
        ('UK', 'UK'), ('US', 'USA'), ('CA', 'Canada'), ('AU', 'Australia'),
        ('FR', 'France'), ('DE', 'Germany'),
    ]

    country = models.CharField(max_length=10, choices=COUNTRY_CHOICES, db_index=True)
    shipment_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ['-shipment_date']

    def __str__(self):
        return f'Shipment {self.id} ({self.country}) — {self.shipment_date}'


class ShipmentItem(models.Model):
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('products.Product', on_delete=models.CASCADE)
    quantity = models.IntegerField()
    box_number = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f'{self.product.m_number} x{self.quantity}'
