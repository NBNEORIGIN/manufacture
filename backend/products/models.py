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

    MACHINE_TYPE_CHOICES = [('UV', 'UV'), ('SUB', 'SUB')]
    BLANK_FAMILY_CHOICES = [
        ('A4s', "A4's"),
        ('A5s', "A5's"),
        ('Dicks', "Dick's"),
        ('Stakes', 'Stakes'),
        ('Myras', "Myra's"),
        ('Donalds', "Donald's"),
        ('Hanging', 'Hanging signs'),
    ]
    machine_type = models.CharField(max_length=3, choices=MACHINE_TYPE_CHOICES, blank=True, default='')
    blank_family = models.CharField(max_length=20, choices=BLANK_FAMILY_CHOICES, blank=True, default='')

    class Meta:
        ordering = ['m_number']

    def __str__(self):
        return f'{self.m_number} — {self.description[:60]}'


class ProductDesign(models.Model):
    MACHINE_FIELDS = ['rolf', 'mimaki', 'epson', 'mutoh', 'nonename']

    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name='design')
    rolf = models.BooleanField(default=False)
    mimaki = models.BooleanField(default=False)
    epson = models.BooleanField(default=False)
    mutoh = models.BooleanField(default=False)
    nonename = models.BooleanField(default=False)

    def machines_ready(self):
        return [m.upper() for m in self.MACHINE_FIELDS if getattr(self, m)]

    def __str__(self):
        return f'Design: {self.product.m_number} [{", ".join(self.machines_ready()) or "none"}]'


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
