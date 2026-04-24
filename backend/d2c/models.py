from django.db import models
from django.contrib.auth.models import User
from core.models import TimestampedModel


class PersonalisedSKU(TimestampedModel):
    """
    Catalogue of SKUs that are made-to-order (personalised).

    Ivan / Ben use the aggregated order counts against this catalogue to
    decide how many blanks to produce in each variant, and on what cadence.

    Seeded from backend/d2c/data/personalised_skus.csv via
    `manage.py import_personalised_skus`.
    """
    DECORATION_CHOICES = [
        ('Graphic', 'Graphic'),
        ('Photo', 'Photo'),
        ('None', 'None'),
    ]

    sku = models.CharField(max_length=100, unique=True, db_index=True)
    colour = models.CharField(max_length=50, blank=True, db_index=True)
    product_type = models.CharField(
        max_length=100, blank=True, db_index=True,
        help_text='Blank shape / family, e.g. "Regular Stake", "Heart Stake", "Large Metal"',
    )
    decoration_type = models.CharField(
        max_length=30, blank=True, choices=DECORATION_CHOICES, db_index=True,
    )
    theme = models.CharField(
        max_length=30, blank=True, db_index=True,
        help_text='Optional theme e.g. Pet, Baby, Islamic',
    )

    class Meta:
        ordering = ['product_type', 'colour', 'sku']

    def __str__(self):
        parts = [self.product_type, self.colour, self.decoration_type, self.theme]
        detail = ' / '.join(p for p in parts if p)
        return f'{self.sku} — {detail}' if detail else self.sku


class ProductTypeBlanks(TimestampedModel):
    """
    Names the underlying blanks that make up a personalised product type.

    The analytics panel on /d2c uses this to show Ben & Ivan which blanks
    need to be cut for a given demand forecast — e.g. "Regular Stake" is
    actually "Tom (acrylic stake)" + "Dick (aluminium face)".

    Free-text so any new product type can have its blanks named without
    a code change. Multiple blanks separated by commas.
    """
    product_type = models.CharField(
        max_length=100, unique=True, db_index=True,
        help_text='Matches PersonalisedSKU.product_type, e.g. "Regular Stake"',
    )
    blank_names = models.CharField(
        max_length=500, blank=True,
        help_text='Comma-separated blank names, e.g. "Tom (acrylic), Dick (aluminium)"',
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['product_type']
        verbose_name_plural = 'Product type blanks'

    def __str__(self):
        return f'{self.product_type} → {self.blank_names or "(unset)"}'


class DispatchOrder(TimestampedModel):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('made', 'Made'),
        ('dispatched', 'Dispatched'),
        ('cancelled', 'Cancelled'),
    ]

    # Order identifiers
    order_id = models.CharField(max_length=50, db_index=True)
    channel = models.CharField(max_length=100, blank=True)  # Amazon: AmazonOD, Etsy: NorthByNorthEastSign
    order_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)

    # Product
    product = models.ForeignKey(
        'products.Product', on_delete=models.SET_NULL,
        related_name='dispatch_orders', null=True, blank=True,
    )
    sku = models.CharField(max_length=100, db_index=True)
    description = models.CharField(max_length=500, blank=True)
    quantity = models.IntegerField(default=1)

    # Customer (minimal — just for reference)
    customer_name = models.CharField(max_length=200, blank=True)

    # Flags — internal staff notes from Zenstores (BW, Large, Photo, etc.)
    flags = models.CharField(max_length=500, blank=True)

    # Personalisation lines (for personalised products)
    line1 = models.CharField(max_length=500, blank=True)
    line2 = models.CharField(max_length=500, blank=True)
    line3 = models.CharField(max_length=500, blank=True)
    line4 = models.CharField(max_length=500, blank=True)
    line5 = models.CharField(max_length=500, blank=True)
    line6 = models.CharField(max_length=500, blank=True)
    line7 = models.CharField(max_length=500, blank=True)
    graphic = models.CharField(max_length=500, blank=True)

    # Tracking
    assigned_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_dispatch_orders',
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='completed_dispatch_orders',
    )
    stock_updated = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-order_date', '-created_at']

    def __str__(self):
        product_ref = self.product.m_number if self.product else self.sku
        return f'D2C-{self.id}: {self.order_id} — {product_ref} x{self.quantity}'

    @property
    def is_personalised(self):
        return bool(self.line1 or self.line2 or self.line3 or self.graphic)

    @property
    def personalisation_text(self):
        lines = [self.line1, self.line2, self.line3, self.line4,
                 self.line5, self.line6, self.line7]
        return ' | '.join(l for l in lines if l)
