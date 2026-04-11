"""
Sales Velocity models.

Part of the manufacture app's Phase 2B feature — automates the 60-day
velocity calculation that used to be done by hand in Google Sheets.
Full brief: docs/sales_velocity_brief.md.

Architectural notes worth skimming before editing this file:

1. Channel vocabulary (CHANNEL_CHOICES) is a sales_velocity-local
   namespace that deliberately differs from products.SKU.channel.
   The SKU_CHANNEL_MAP below is informational only — the aggregator
   does NOT use it for join logic. The join is channel-agnostic on
   SKU.sku -> Product. See services/aggregator.py (Phase 2B.4).

2. raw_response lives on SalesVelocityAPICall, not on
   SalesVelocityHistory, so the snapshot table stays small and
   indexable. Audit log is cleanup-policied at 14 days for success
   and 90 days for errors.

3. Etsy OAuth is NOT in this module — it lives in Cairn and is read
   via HTTP at GET /etsy/sales. OAuthCredential is for eBay only.

4. VarianceGateState deliberately does not exist. Shadow mode is
   controlled by settings.SALES_VELOCITY_WRITE_ENABLED (env var),
   and cutover drift is reported via DriftAlert + the Sales Velocity
   tab UI, not email.
"""
from django.db import models

from core.models import TimestampedModel


# ── Channel namespace ─────────────────────────────────────────────────────────

CHANNEL_CHOICES = [
    ('amazon_uk', 'Amazon UK'),
    ('amazon_us', 'Amazon US'),
    ('amazon_ca', 'Amazon CA'),
    ('amazon_au', 'Amazon AU'),
    ('amazon_de', 'Amazon DE'),
    ('amazon_fr', 'Amazon FR'),
    ('amazon_es', 'Amazon ES'),
    ('amazon_nl', 'Amazon NL'),
    ('amazon_it', 'Amazon IT'),
    ('etsy',      'Etsy'),
    ('ebay',      'eBay'),
    ('footfall',  'Footfall'),
    ('shop',      'Shop (stub)'),
]

# Maps sales_velocity channel code -> set of products.SKU.channel values
# attributed to it. Used by the Sales Velocity tab's per-channel breakdown
# columns. The aggregator does NOT use this for join logic — joins are
# channel-agnostic on SKU.sku. See test_channel_coverage for the guardrail
# that ensures new SKU.channel values can't slip through silently.
#
# FR_CRAFTS / FR_DESIGNED / IT_DESIGNED are normalised onto their base
# Amazon marketplace (Option A per 2026-04-11 planning session).
SKU_CHANNEL_MAP = {
    'amazon_uk': {'UK'},
    'amazon_us': {'US'},
    'amazon_ca': {'CA'},
    'amazon_au': {'AU'},
    'amazon_de': {'DE'},
    'amazon_fr': {'FR', 'FR_CRAFTS', 'FR CRAFTS', 'FR_DESIGNED'},
    'amazon_es': {'ES'},
    'amazon_nl': {'NL'},
    'amazon_it': {'IT', 'IT_DESIGNED'},
    'etsy':      {'ETSY'},
    'ebay':      {'EBAY'},
    'footfall':  set(),   # manual entry only
    'shop':      set(),   # stub
}

# Explicitly-ignored SKU.channel values. A new SKU.channel value that is
# neither in SKU_CHANNEL_MAP nor here will fail test_channel_coverage,
# forcing a conscious decision rather than a silent drop.
CHANNELS_OUT_OF_SCOPE = {'SHOPIFY', 'STOCK'}

# Known data-quality issues to be cleaned up in a separate follow-up.
# Keeping them in an explicit set lets the test pass while the cleanup
# is pending, without hiding them from the next engineer who runs the
# coverage query.
CHANNELS_DATA_CLEANUP = {'AMAZON', 'ETSYOD001198', 'M0781 IS FREE TO USE'}


# ── Models ───────────────────────────────────────────────────────────────────

class SalesVelocityHistory(TimestampedModel):
    """Daily snapshot of 30-day rolling units sold per (product, channel)."""

    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='velocity_snapshots',
    )
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, db_index=True)
    snapshot_date = models.DateField(db_index=True)
    units_sold_30d = models.PositiveIntegerField()

    class Meta:
        unique_together = [('product', 'channel', 'snapshot_date')]
        indexes = [models.Index(fields=['product', 'snapshot_date'])]
        verbose_name_plural = 'Sales velocity history'

    def __str__(self):
        return (
            f'{self.product.m_number} {self.channel} '
            f'{self.snapshot_date}: {self.units_sold_30d}'
        )


class UnmatchedSKU(TimestampedModel):
    """
    A SKU returned by an adapter that doesn't map to any Product.

    `units_sold_30d` is a ROLLING counter overwritten on each aggregator run
    — it reflects the most recent 30-day window, not a cumulative total.
    `first_seen` / `last_seen` track the full discovery lifecycle; a SKU
    that stops selling retains its last_seen date but its units_sold_30d
    decays to zero as the rolling window moves past it.
    """

    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    external_sku = models.CharField(max_length=120, db_index=True)
    title = models.CharField(max_length=200, blank=True)
    units_sold_30d = models.PositiveIntegerField(default=0)
    first_seen = models.DateField()
    last_seen = models.DateField()
    ignored = models.BooleanField(
        default=False,
        help_text='True if a user explicitly ignored this SKU via the tab UI',
    )
    resolved_to = models.ForeignKey(
        'products.Product',
        null=True, blank=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        unique_together = [('channel', 'external_sku')]
        verbose_name_plural = 'Unmatched SKUs'

    def __str__(self):
        return f'{self.channel}:{self.external_sku} ({self.units_sold_30d}u)'


class ManualSale(TimestampedModel):
    """Footfall or other manually-entered sales not captured by any API."""

    product = models.ForeignKey('products.Product', on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    sale_date = models.DateField()
    channel = models.CharField(
        max_length=20,
        choices=CHANNEL_CHOICES,
        default='footfall',
    )
    notes = models.TextField(blank=True)
    entered_by = models.ForeignKey(
        'auth.User', null=True, on_delete=models.SET_NULL,
    )

    class Meta:
        ordering = ['-sale_date', '-created_at']

    def __str__(self):
        return f'{self.product.m_number} x{self.quantity} on {self.sale_date}'


class SalesVelocityAPICall(TimestampedModel):
    """
    Audit log for every adapter call — parallel to FBAAPICall.

    Raw request and response live here, NOT on SalesVelocityHistory, so the
    snapshot table stays small and indexable.

    Cleanup policy: a Django-Q scheduled command `sales_velocity_purge_audit`
    deletes rows older than 14 days on a weekly cadence. Failed calls
    (response_status >= 400 or error_message set) are retained for 90 days.

    PII: before persisting `response_body`, adapters must strip
    customer-level fields (BuyerName, BuyerEmail, ShippingAddress, etc.).
    Whitelist keys to keep rather than blacklisting what to drop.
    """

    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, db_index=True)
    endpoint = models.CharField(max_length=120)
    request_params = models.JSONField(null=True, blank=True)
    response_status = models.IntegerField(null=True)
    response_body = models.JSONField(
        null=True, blank=True,
        help_text='PII-stripped. Adapters must whitelist keys to persist.',
    )
    duration_ms = models.IntegerField(null=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['channel', '-created_at']),
            models.Index(fields=['response_status']),
        ]

    def __str__(self):
        return f'{self.channel} {self.endpoint} [{self.response_status}]'


class OAuthCredential(TimestampedModel):
    """
    OAuth2 refresh-token storage for providers whose OAuth flow lives in
    manufacture itself.

    Currently only eBay — Etsy OAuth lives in Cairn, and manufacture
    reads Etsy sales via the Cairn /etsy/sales HTTP endpoint, so no
    Etsy row exists in this table.

    One row per provider. The adapter refreshes the access token in-place
    when it's within 5 minutes of expiry, holding a SELECT FOR UPDATE lock
    to avoid refresh races between the qcluster worker and web process.

    client_id/client_secret deliberately do NOT live on this model —
    they come from env vars (EBAY_CLIENT_ID / EBAY_CLIENT_SECRET) so
    rotating the app credentials doesn't need a DB migration.
    """

    PROVIDER_CHOICES = [('ebay', 'eBay')]

    provider = models.CharField(
        max_length=20,
        choices=PROVIDER_CHOICES,
        unique=True,
    )
    refresh_token = models.TextField()
    access_token = models.TextField(blank=True)
    access_token_expires_at = models.DateTimeField(null=True, blank=True)
    last_refreshed_at = models.DateTimeField(null=True, blank=True)
    scope = models.TextField(
        blank=True,
        help_text='Space-separated OAuth scopes granted by the user consent',
    )

    def __str__(self):
        expires = (
            self.access_token_expires_at.isoformat()
            if self.access_token_expires_at else 'never'
        )
        return f'{self.provider} (expires {expires})'


class DriftAlert(TimestampedModel):
    """
    Post-cutover drift warning raised by the weekly sanity check.

    Triggered when today's `units_sold_30d * 2` for a product has moved
    more than 5% from the 7-day rolling average of the same metric in
    SalesVelocityHistory. Surfaced in the Sales Velocity tab's DriftAlert
    panel — no email.

    Does NOT auto-revert StockLevel.sixty_day_sales. Alert-only.
    Retention: 90 days, purged by sales_velocity_purge_audit.
    """

    product = models.ForeignKey('products.Product', on_delete=models.CASCADE)
    detected_at = models.DateTimeField()
    current_velocity = models.PositiveIntegerField()
    rolling_avg_velocity = models.PositiveIntegerField()
    variance_pct = models.DecimalField(max_digits=6, decimal_places=2)
    acknowledged = models.BooleanField(default=False)
    acknowledged_by = models.ForeignKey(
        'auth.User',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='acknowledged_drift_alerts',
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-detected_at']
        indexes = [
            models.Index(fields=['acknowledged', '-detected_at']),
        ]

    def __str__(self):
        state = 'ack' if self.acknowledged else 'unack'
        return (
            f'{self.product.m_number} drift '
            f'{self.variance_pct}% [{state}]'
        )
