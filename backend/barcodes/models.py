from django.db import models
from core.models import TimestampedModel


class ProductBarcode(TimestampedModel):
    """A barcode assigned to an M-number for a specific marketplace."""

    BARCODE_TYPE_CHOICES = [
        ('FNSKU', 'Amazon FNSKU'),
        ('UPC', 'Manufacturer UPC'),
        ('EAN', 'Manufacturer EAN'),
    ]

    MARKETPLACE_CHOICES = [
        ('UK', 'Amazon UK'),
        ('US', 'Amazon US'),
        ('CA', 'Amazon CA'),
        ('AU', 'Amazon AU'),
        ('DE', 'Amazon DE'),
        ('ALL', 'All marketplaces'),
    ]

    SOURCE_CHOICES = [
        ('sp_api', 'SP-API sync'),
        ('manual', 'Manual entry'),
        ('csv_import', 'CSV import'),
    ]

    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='barcodes',
    )
    marketplace = models.CharField(max_length=10, choices=MARKETPLACE_CHOICES)
    barcode_type = models.CharField(max_length=10, choices=BARCODE_TYPE_CHOICES)
    barcode_value = models.CharField(max_length=32, db_index=True)
    label_title = models.CharField(
        max_length=80,
        help_text="Text printed on the label (product title, max 80 chars)",
    )
    condition = models.CharField(max_length=20, default='New')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    last_synced_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = [('product', 'marketplace', 'barcode_type')]
        indexes = [
            models.Index(fields=['product', 'marketplace']),
        ]

    def __str__(self):
        return f"{self.product.m_number} {self.marketplace} {self.barcode_value}"


class Printer(TimestampedModel):
    """
    A physical thermal-label printer the system can route jobs to.

    The print agent on a workstation declares its `slug` when polling, and
    only claims jobs whose `printer_fk` matches (or where printer_fk is null,
    meaning the legacy "any printer" pool).

    Transport tells the agent how to reach the device:
      - `tcp`    — `address` is host:port, the agent opens a socket
      - `serial` — `address` is a tty device (e.g. /dev/rfcomm0 for a
                   Bluetooth-paired PM-2411-BT). Agent writes raw bytes.
      - `cups`   — `address` is the CUPS queue name. Agent shells out to `lp`.

    Command language tells the renderer which dialect to emit:
      - `zpl`    — Zebra programming language (existing default)
      - `tspl`   — TSC Printer Language. Common on Postek / portable BT printers.
      - `escpos` — receipt-printer language; some labellers accept it.
    """
    TRANSPORT_CHOICES = [
        ('tcp', 'TCP socket'),
        ('serial', 'Serial / Bluetooth tty'),
        ('cups', 'CUPS queue'),
    ]
    LANGUAGE_CHOICES = [
        ('zpl', 'ZPL (Zebra)'),
        ('tspl', 'TSPL (TSC / Postek)'),
        ('escpos', 'ESC/POS'),
    ]

    name = models.CharField(max_length=80, help_text='Display name, e.g. "Ben & Ivan PM-2411-BT"')
    slug = models.SlugField(
        max_length=40, unique=True,
        help_text='Stable id agents use to identify themselves, e.g. "pm-2411-bt-fac1"',
    )
    transport = models.CharField(max_length=10, choices=TRANSPORT_CHOICES, default='tcp')
    address = models.CharField(
        max_length=200,
        help_text='host:port (tcp), /dev/rfcomm0 (serial), or queue-name (cups)',
    )
    command_language = models.CharField(max_length=10, choices=LANGUAGE_CHOICES, default='zpl')
    label_width_mm = models.PositiveIntegerField(default=50)
    label_height_mm = models.PositiveIntegerField(default=25)
    label_dpi = models.PositiveIntegerField(default=203)
    active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} [{self.command_language} → {self.transport}]'


class PrintJob(TimestampedModel):
    """A queued or completed thermal print job."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('claimed', 'Claimed by agent'),
        ('printing', 'Printing'),
        ('done', 'Done'),
        ('error', 'Error'),
        ('cancelled', 'Cancelled'),
    ]

    barcode = models.ForeignKey(
        ProductBarcode,
        on_delete=models.PROTECT,
        related_name='print_jobs',
    )
    quantity = models.PositiveIntegerField()
    command_payload = models.TextField(
        help_text="Rendered printer command string (ZPL by default) including quantity directive",
    )
    command_language = models.CharField(
        max_length=10,
        default='zpl',
        help_text="Command language of the payload (for debugging/logging)",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
    )
    agent_id = models.CharField(
        max_length=64,
        blank=True,
        help_text="Hostname of the agent that claimed this job",
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    printed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)
    requested_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    # Optional routing — null means "any agent on the legacy global pool".
    # When set, only an agent declaring this printer's slug will claim it.
    printer = models.ForeignKey(
        Printer,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='jobs',
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"PrintJob #{self.pk} {self.status} ({self.quantity}x {self.barcode})"


class FNSKUSyncLog(TimestampedModel):
    """Record of each SP-API FNSKU sync run."""

    marketplace = models.CharField(max_length=10)
    ran_at = models.DateTimeField()
    created = models.IntegerField(default=0)
    updated = models.IntegerField(default=0)
    unmatched_count = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-ran_at']

    def __str__(self):
        return f"FNSKUSyncLog {self.marketplace} {self.ran_at:%Y-%m-%d %H:%M}"
