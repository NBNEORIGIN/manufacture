"""
Data model for the FBA Shipment Automation module.

Implements the state container for Amazon SP-API Fulfillment Inbound v2024-03-20
workflow automation. See FBA_SHIPMENT_AUTOMATION brief for the full 23-step
flow these models track.

Feature 1 (barcodes app) is a dependency: `barcodes.ProductBarcode` must be
populated with FNSKU values per marketplace before a plan can be submitted.
"""

from django.conf import settings
from django.db import models

from core.models import TimestampedModel


# Marketplaces the FBA module supports. Keep in sync with
# barcodes.ProductBarcode.MARKETPLACE_CHOICES (the FBA-relevant subset).
FBA_MARKETPLACE_CHOICES = [
    ('UK', 'Amazon UK'),
    ('US', 'Amazon US'),
    ('CA', 'Amazon CA'),
    ('AU', 'Amazon AU'),
    ('DE', 'Amazon DE'),
]


class FBAShipmentPlan(TimestampedModel):
    """
    Top-level container matching Amazon's inboundPlanId.

    One plan may produce one or more FBAShipment rows after placement
    confirmation (Amazon may split a plan across multiple fulfilment centres).
    """

    STATUS_CHOICES = [
        # Pre-API states
        ('draft',                      'Draft'),
        ('items_added',                'Items added'),
        # API lifecycle (matches the 23-step flow)
        ('plan_creating',              'Creating inbound plan'),
        ('plan_created',               'Inbound plan created'),
        ('packing_generating',         'Generating packing options'),
        ('packing_options_fetching',   'Fetching packing options'),
        ('packing_options_ready',      'Packing options available'),
        ('packing_info_setting',       'Setting packing information'),
        ('packing_info_set',           'Packing information set'),
        ('packing_confirming',         'Confirming packing option'),
        ('packing_confirmed',          'Packing option confirmed'),
        ('placement_generating',       'Generating placement options'),
        ('placement_options_fetching', 'Fetching placement options'),
        ('placement_options_ready',    'Placement options available'),
        ('placement_confirming',       'Confirming placement option'),
        ('placement_confirmed',        'Placement confirmed'),
        ('transport_generating',       'Generating transportation options'),
        ('transport_options_fetching', 'Fetching transportation options'),
        ('transport_options_ready',    'Transportation options available'),
        ('delivery_window_generating', 'Generating delivery windows'),
        ('delivery_window_fetching',   'Fetching delivery windows'),
        ('delivery_window_ready',      'Delivery windows available'),
        ('transport_confirming',       'Confirming transportation'),
        ('transport_confirmed',        'Transportation confirmed'),
        ('labels_fetching',            'Fetching labels'),
        ('ready_to_ship',              'Ready to ship (labels available)'),
        ('dispatched',                 'Dispatched to Amazon'),
        # Terminal states
        ('cancelled',                  'Cancelled'),
        ('error',                      'Error'),
    ]

    TERMINAL_STATUSES = {'ready_to_ship', 'dispatched', 'cancelled', 'error'}
    PAUSE_STATUSES = {'packing_options_ready', 'placement_options_ready'}

    # Pre-API fields
    name = models.CharField(
        max_length=120,
        help_text="Human-readable name, e.g. 'FBA UK 2026-04-15'",
    )
    marketplace = models.CharField(max_length=10, choices=FBA_MARKETPLACE_CHOICES)
    ship_from_address = models.JSONField(
        help_text="Snapshot of NBNE ship-from address at creation time",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fba_plans_created',
    )

    # API state
    status = models.CharField(
        max_length=40,
        choices=STATUS_CHOICES,
        default='draft',
        db_index=True,
    )
    inbound_plan_id = models.CharField(max_length=64, blank=True, db_index=True)

    # Cached selections during the flow
    selected_packing_option_id = models.CharField(max_length=64, blank=True)
    selected_placement_option_id = models.CharField(max_length=64, blank=True)
    selected_transportation_option_id = models.CharField(max_length=64, blank=True)
    selected_delivery_window_id = models.CharField(max_length=64, blank=True)

    # Async operation tracking — each POST returns an operationId we poll
    current_operation_id = models.CharField(max_length=64, blank=True)
    current_operation_started_at = models.DateTimeField(null=True, blank=True)
    last_polled_at = models.DateTimeField(null=True, blank=True)

    # Error log — append-only list of error dicts.
    # NOTE: never .append() this in-place; always reassign (see workflow.advance_plan).
    error_log = models.JSONField(default=list, blank=True)

    # Options snapshots — store the full API response for audit and debugging
    packing_options_snapshot = models.JSONField(null=True, blank=True)
    placement_options_snapshot = models.JSONField(null=True, blank=True)
    transportation_options_snapshot = models.JSONField(null=True, blank=True)
    delivery_window_snapshot = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['marketplace', 'status']),
        ]

    def __str__(self) -> str:
        return f'{self.name} ({self.marketplace}, {self.status})'

    @property
    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL_STATUSES

    @property
    def is_paused(self) -> bool:
        return self.status in self.PAUSE_STATUSES


class FBAShipmentPlanItem(TimestampedModel):
    """An item (SKU + quantity) within an FBAShipmentPlan."""

    plan = models.ForeignKey(
        FBAShipmentPlan,
        on_delete=models.CASCADE,
        related_name='items',
    )
    sku = models.ForeignKey('products.SKU', on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()

    # Snapshotted at plan creation time — NOT looked up live.
    # FNSKU comes from barcodes.ProductBarcode filtered by marketplace.
    fnsku = models.CharField(max_length=32)
    msku = models.CharField(max_length=80)
    label_owner = models.CharField(max_length=20, default='SELLER')
    prep_owner = models.CharField(max_length=20, default='SELLER')

    class Meta:
        ordering = ['plan', 'msku']
        unique_together = [('plan', 'sku')]

    def __str__(self) -> str:
        return f'{self.msku} × {self.quantity} ({self.fnsku})'


class FBAShipment(TimestampedModel):
    """
    A single shipment created under an FBAShipmentPlan after placement confirmation.
    Amazon may split one plan into multiple shipments — one per destination FC.
    """

    plan = models.ForeignKey(
        FBAShipmentPlan,
        on_delete=models.CASCADE,
        related_name='shipments',
    )
    shipment_id = models.CharField(
        max_length=64,
        help_text="Amazon shipmentId (pre-confirmation)",
    )
    shipment_confirmation_id = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Amazon shipmentConfirmationId, e.g. FBA15ABCDEFG (post-confirmation)",
    )
    destination_fc = models.CharField(
        max_length=16,
        blank=True,
        help_text="Destination fulfilment centre code, e.g. LTN4, BHX1",
    )

    # Downloadable label URL from getLabels (v0 endpoint, PDF)
    labels_url = models.URLField(blank=True, max_length=1000)
    labels_fetched_at = models.DateTimeField(null=True, blank=True)

    # Tracking details (filled after Ben books Evri/carrier and provides the number)
    carrier_name = models.CharField(max_length=80, blank=True)
    tracking_number = models.CharField(max_length=120, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['shipment_id']

    def __str__(self) -> str:
        ref = self.shipment_confirmation_id or self.shipment_id
        return f'{ref} → {self.destination_fc or "?"}'


class FBABox(TimestampedModel):
    """
    A physical box within an FBAShipment.

    Provides weight/dims to setPackingInformation. Created during the pack-into-boxes
    step of the UI wizard BEFORE placement confirmation, so the `shipment` FK is
    populated later once Amazon assigns boxes to specific shipments.
    """

    shipment = models.ForeignKey(
        FBAShipment,
        on_delete=models.CASCADE,
        related_name='boxes',
        null=True,
        blank=True,
        help_text="Populated after placement confirmation assigns boxes to shipments",
    )
    plan = models.ForeignKey(
        FBAShipmentPlan,
        on_delete=models.CASCADE,
        related_name='boxes',
        help_text="Redundant link to allow pre-placement box creation",
    )
    box_number = models.PositiveIntegerField()
    length_cm = models.DecimalField(max_digits=6, decimal_places=1)
    width_cm = models.DecimalField(max_digits=6, decimal_places=1)
    height_cm = models.DecimalField(max_digits=6, decimal_places=1)
    weight_kg = models.DecimalField(max_digits=6, decimal_places=2)
    amazon_box_id = models.CharField(
        max_length=64,
        blank=True,
        help_text="Amazon's assigned box identifier, e.g. FBA15ABCDEFG000001",
    )

    class Meta:
        ordering = ['plan', 'box_number']
        unique_together = [('plan', 'box_number')]

    def __str__(self) -> str:
        return f'Box {self.box_number} ({self.plan.name})'


class FBABoxItem(TimestampedModel):
    """Contents of a box — which plan items and how many of each."""

    box = models.ForeignKey(
        FBABox,
        on_delete=models.CASCADE,
        related_name='contents',
    )
    plan_item = models.ForeignKey(
        FBAShipmentPlanItem,
        on_delete=models.CASCADE,
        related_name='box_placements',
    )
    quantity = models.PositiveIntegerField()

    class Meta:
        ordering = ['box', 'plan_item']
        unique_together = [('box', 'plan_item')]

    def __str__(self) -> str:
        return f'{self.plan_item.msku} × {self.quantity} in box {self.box.box_number}'


class FBAAPICall(TimestampedModel):
    """
    Audit log of every SP-API call made for this module.

    Critical for debugging because the v2024-03-20 workflow is long and failures
    are often cryptic. This is the primary tool for diagnosing a stuck plan.
    """

    plan = models.ForeignKey(
        FBAShipmentPlan,
        on_delete=models.CASCADE,
        related_name='api_calls',
        null=True,
        blank=True,
    )
    operation_name = models.CharField(max_length=80, db_index=True)
    request_body = models.JSONField(null=True, blank=True)
    response_status = models.IntegerField(null=True)
    response_body = models.JSONField(null=True, blank=True)
    operation_id = models.CharField(max_length=64, blank=True, db_index=True)
    duration_ms = models.IntegerField(null=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['plan', '-created_at']),
            models.Index(fields=['operation_name', '-created_at']),
        ]

    def __str__(self) -> str:
        return f'{self.operation_name} @ {self.created_at:%Y-%m-%d %H:%M:%S}'
