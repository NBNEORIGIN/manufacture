from django.db import models
from core.models import TimestampedModel


class RestockReport(TimestampedModel):
    """One downloaded restock report per marketplace per sync."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('complete', 'Complete'),
        ('error', 'Error'),
    ]

    marketplace = models.CharField(max_length=10, db_index=True)
    region = models.CharField(max_length=10)   # EU, NA, FE
    report_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    row_count = models.IntegerField(default=0)
    source = models.CharField(max_length=20, default='spapi')  # spapi | manual
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['marketplace', 'created_at']),
        ]

    def __str__(self):
        return f'RestockReport {self.marketplace} {self.created_at:%Y-%m-%d %H:%M} ({self.status})'


class RestockItem(TimestampedModel):
    """One row from a restock report, resolved to M-number where possible."""
    report = models.ForeignKey(
        RestockReport, on_delete=models.CASCADE, related_name='items'
    )
    marketplace = models.CharField(max_length=10, db_index=True)
    merchant_sku = models.CharField(max_length=200, db_index=True)
    asin = models.CharField(max_length=20, blank=True, db_index=True)
    fnsku = models.CharField(max_length=50, blank=True)
    m_number = models.CharField(max_length=20, blank=True, db_index=True)
    product_name = models.CharField(max_length=500, blank=True)

    # Inventory state
    units_total = models.IntegerField(default=0)
    units_available = models.IntegerField(default=0)
    units_inbound = models.IntegerField(default=0)
    units_reserved = models.IntegerField(default=0)
    units_unfulfillable = models.IntegerField(default=0)
    days_of_supply_amazon = models.FloatField(null=True, blank=True)
    days_of_supply_total = models.FloatField(null=True, blank=True)

    # Sales data
    sales_last_30d = models.FloatField(default=0)
    units_sold_30d = models.IntegerField(default=0)

    # Amazon recommendation
    alert = models.CharField(max_length=50, blank=True, db_index=True)
    amazon_recommended_qty = models.IntegerField(null=True, blank=True)
    amazon_ship_date = models.DateField(null=True, blank=True)

    # Newsvendor recommendation
    newsvendor_qty = models.IntegerField(null=True, blank=True)
    newsvendor_confidence = models.FloatField(null=True, blank=True)
    newsvendor_notes = models.TextField(blank=True)

    # Approved send qty (user-edited before creating production orders)
    approved_qty = models.IntegerField(null=True, blank=True)
    approved_by = models.CharField(max_length=100, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    # Production order linkage
    production_order_id = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ['alert', '-newsvendor_qty']
        indexes = [
            models.Index(fields=['marketplace', 'merchant_sku']),
            models.Index(fields=['m_number']),
            models.Index(fields=['alert']),
        ]

    def __str__(self):
        return f'{self.merchant_sku} ({self.marketplace}) — {self.m_number or "unresolved"}'


class RestockExclusion(TimestampedModel):
    """
    M-numbers permanently excluded from restock plans.
    Used for personalised/D2C items that should never be FBA-restocked.
    """
    m_number = models.CharField(max_length=20, unique=True, db_index=True)
    reason = models.CharField(max_length=200, blank=True)
    added_by = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['m_number']

    def __str__(self):
        return f'RestockExclusion {self.m_number}'


class RestockPlan(TimestampedModel):
    """An approved restock plan, ready to dispatch to production."""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('in_production', 'In Production'),
        ('shipped', 'Shipped'),
    ]

    marketplace = models.CharField(max_length=10, db_index=True)
    created_by = models.CharField(max_length=100)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='draft')
    report = models.ForeignKey(
        RestockReport, on_delete=models.SET_NULL, null=True, related_name='plans'
    )
    notes = models.TextField(blank=True)
    total_units = models.IntegerField(default=0)
    item_count = models.IntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'RestockPlan {self.marketplace} {self.created_at:%Y-%m-%d} ({self.status})'
