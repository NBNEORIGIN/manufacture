from django.db import models
from django.contrib.auth.models import User
from core.models import TimestampedModel


class Shipment(TimestampedModel):
    STATUS_CHOICES = [
        ('planning', 'Planning'),
        ('packing', 'Packing'),
        ('labelled', 'Labelled'),
        ('shipped', 'Shipped'),
    ]
    COUNTRY_CHOICES = [
        ('UK', 'UK'), ('US', 'USA'), ('CA', 'Canada'), ('AU', 'Australia'),
        ('FR', 'France'), ('DE', 'Germany'), ('IT', 'Italy'),
    ]

    country = models.CharField(max_length=10, choices=COUNTRY_CHOICES, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planning', db_index=True)
    shipment_date = models.DateField(null=True, blank=True)
    total_units = models.IntegerField(default=0)
    box_count = models.IntegerField(default=0)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-shipment_date', '-created_at']

    def __str__(self):
        return f'FBA-{self.id} ({self.country}) — {self.shipment_date or "unscheduled"}'

    def recalculate_totals(self):
        agg = self.items.aggregate(
            total=models.Sum('quantity'),
            boxes=models.Max('box_number'),
        )
        self.total_units = agg['total'] or 0
        self.box_count = agg['boxes'] or 0
        self.save(update_fields=['total_units', 'box_count', 'updated_at'])


class ShipmentItem(TimestampedModel):
    # Machine assignment choices (Ivan review #12, items 4/6/7/8)
    MACHINE_CHOICES = [
        ('', '—'),
        ('STOCK', 'STOCK'),
        ('UV', 'UV'),
        ('SUB', 'SUB'),
    ]

    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('products.Product', on_delete=models.CASCADE, related_name='shipment_items')
    sku = models.CharField(max_length=100, blank=True)
    quantity = models.IntegerField()  # required amount for the country
    quantity_shipped = models.IntegerField(default=0)  # actual amount shipped (review #12 item 11)
    box_number = models.IntegerField(null=True, blank=True)
    amz_restock_quantity = models.IntegerField(default=0)
    stock_at_ship = models.IntegerField(default=0)

    # Review #12 item 4/6/7: machine assignment per item
    machine_assignment = models.CharField(
        max_length=10,
        choices=MACHINE_CHOICES,
        blank=True,
        default='',
    )
    # Review #12 item 10: running total of stock taken for this item
    stock_taken = models.IntegerField(default=0)

    class Meta:
        ordering = ['shipment', 'box_number', 'product__m_number']

    def __str__(self):
        return f'{self.product.m_number} x{self.quantity} (box {self.box_number or "?"})'
