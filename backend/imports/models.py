from django.db import models
from django.contrib.auth.models import User
from core.models import TimestampedModel


class ImportLog(TimestampedModel):
    IMPORT_TYPES = [
        ('master_stock', 'Master Stock'),
        ('assembly', 'Assembly (SKU Mapping)'),
        ('sku_assignment', 'SKU Assignment'),
        ('scratchpad', 'ScratchPad2 (Optimal Stock)'),
        ('fba_inventory', 'FBA Inventory Report'),
        ('sales_traffic', 'Sales & Traffic Report'),
        ('restock', 'Restock Inventory Report'),
        ('procurement', 'Procurement'),
        ('fba_shipments', 'FBA Shipments (Historical)'),
        ('zenstores', 'Zenstores Order Export'),
        ('records', 'Production Records (Historical)'),
    ]

    import_type = models.CharField(max_length=30, choices=IMPORT_TYPES)
    filename = models.CharField(max_length=500)
    rows_processed = models.IntegerField(default=0)
    rows_created = models.IntegerField(default=0)
    rows_updated = models.IntegerField(default=0)
    rows_skipped = models.IntegerField(default=0)
    errors = models.JSONField(default=list)
    imported_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_import_type_display()} — {self.filename} ({self.created_at:%Y-%m-%d %H:%M})'
