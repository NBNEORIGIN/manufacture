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

    MACHINE_TYPE_CHOICES = [('UV', 'UV'), ('SUB', 'SUB'), ('N/A', 'N/A')]
    BLANK_FAMILY_CHOICES = [
        ('A4s', "A4's"),
        ('A5s', "A5's"),
        ('Dicks', "Dick's"),
        ('Stakes', 'Stakes'),
        ('Myras', "Myra's"),
        ('Donalds', "Donald's"),
        ('Hanging', 'Hanging signs'),
        ('N/A', 'N/A'),
        ('Personalised', 'Personalised'),
    ]
    machine_type = models.CharField(max_length=3, choices=MACHINE_TYPE_CHOICES, blank=True, default='')
    blank_family = models.CharField(max_length=20, choices=BLANK_FAMILY_CHOICES, blank=True, default='')

    # Shipping dimensions (used by FBA shipment automation — setPackingInformation).
    # Normally inherited from blank_type.apply_to_products(); can be overridden per-product
    # (composites like "DICK, TOM" have their own BlankType row; products with add-ons
    # like stands get manual overrides). Nullable until populated.
    shipping_length_cm = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    shipping_width_cm  = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    shipping_height_cm = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    shipping_weight_g  = models.PositiveIntegerField(null=True, blank=True, help_text='Packed weight in grams')
    shipping_dims_overridden = models.BooleanField(
        default=False,
        help_text='True if shipping_* were set manually and should NOT be overwritten by '
                  'BlankType.apply_to_products(). Set automatically by the per-product editor.',
    )
    blank_type = models.ForeignKey(
        'BlankType',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
        help_text='Canonical blank type this product is packaged as. Source of shipping dims '
                  'unless shipping_dims_overridden is True.',
    )

    class Meta:
        ordering = ['m_number']

    def __str__(self):
        return f'{self.m_number} — {self.description[:60]}'


class BlankType(TimestampedModel):
    """
    A canonical packaging blank. Each active Product is packed as (or in some
    combination of) one of these. Dimensions and weight are source-of-truth for
    FBA `setPackingInformation` and drop onto Product.shipping_* via
    `apply_to_products()` unless that product has a manual override.

    Composite blanks (e.g. products shipped as "DICK + TOM") are their own
    BlankType rows with their own measured dims — not a join of two rows.
    """
    name = models.CharField(
        max_length=80,
        unique=True,
        help_text='Canonical name, e.g. SAVILLE, DICK, DICK+TOM. Case preserved but '
                  'matched case-insensitively against Product.blank.',
    )
    length_cm = models.DecimalField(max_digits=6, decimal_places=1)
    width_cm  = models.DecimalField(max_digits=6, decimal_places=1)
    height_cm = models.DecimalField(max_digits=6, decimal_places=1)
    weight_g  = models.PositiveIntegerField(help_text='Packed weight in grams')
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.length_cm}×{self.width_cm}×{self.height_cm}cm, {self.weight_g}g)'

    def apply_to_products(self, force: bool = False) -> int:
        """
        Copy this blank type's dims onto every linked Product.shipping_*,
        skipping products flagged `shipping_dims_overridden` unless force=True.
        Returns the number of products updated.
        """
        qs = self.products.all()
        if not force:
            qs = qs.filter(shipping_dims_overridden=False)
        return qs.update(
            shipping_length_cm=self.length_cm,
            shipping_width_cm=self.width_cm,
            shipping_height_cm=self.height_cm,
            shipping_weight_g=self.weight_g,
        )


class ProductDesign(models.Model):
    MACHINE_FIELDS = ['rolf', 'mimaki', 'epson', 'mutoh', 'mao']

    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name='design')
    rolf = models.BooleanField(default=False)
    mimaki = models.BooleanField(default=False)
    epson = models.BooleanField(default=False)
    mutoh = models.BooleanField(default=False)
    mao = models.BooleanField(default=False)

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
