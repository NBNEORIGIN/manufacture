"""
Cost Price Engine (Phase 1 of margin intelligence).

Cost for a product is computed by `get_cost_price(product)` which Cairn will
call for every ASIN when building the margin brief. Three sources of truth, in
priority order:

  1. MNumberCostOverride.cost_price_gbp          -> HIGH confidence
  2. BlankCost keyed by normalise(Product.blank)  -> MEDIUM confidence
  3. Fallback (CostConfig.default_material_gbp)   -> LOW  confidence

The material + labour + overhead breakdown is always returned so the UI can
show the calc without Cairn re-deriving it.

See MARGIN_INTELLIGENCE_SPEC phase 1. Dimensions/packing remain on BlankType;
this module is strictly the £-per-unit engine.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from django.db import models

from core.models import TimestampedModel


def normalise_blank(raw: Optional[str]) -> str:
    """
    Collapse the messy free-text `Product.blank` field into a canonical key.

    Examples:
      "DICK , KIRSTY" / "DICK, KIRSTY" / "DICK - KIRSTY" -> "DICK KIRSTY"
      "GARY GLITTER"                                     -> "GARY GLITTER"
      "  saville  "                                      -> "SAVILLE"
      "JOSEPH,FRED"                                      -> "JOSEPH FRED"

    Strategy: uppercase, strip non-alphanumeric (replace with space), collapse
    whitespace. Result is the unique key for BlankCost.normalized_name.

    Note this intentionally merges "DICK" (single blank) with nothing else, but
    composites like "DICK KIRSTY" stay distinct. Composites still get flagged
    via `is_composite` because the resulting cost estimate is low confidence —
    the user should add an MNumberCostOverride for each M-number that uses it.
    """
    if not raw:
        return ''
    cleaned = re.sub(r'[^A-Za-z0-9]+', ' ', raw).strip().upper()
    return re.sub(r'\s+', ' ', cleaned)


def is_composite_blank(raw: Optional[str]) -> bool:
    """
    A blank is 'composite' only if it contains an explicit separator (, + & /).
    Multi-word names like "BABY JESUS" or "GARY GLITTER" are single blanks.
    """
    if not raw:
        return False
    return bool(re.search(r'[,+&/]', raw))


class BlankCost(TimestampedModel):
    """
    Per-blank material cost and labour time estimate.

    Keyed by `normalized_name` (see `normalise_blank`) not by FK to BlankType,
    because BlankType is empty and product→blank mapping happens via free-text
    Product.blank. Populated initially by the bootstrap migration; editable
    via the cost-config UI.

    Cost formula (per unit):
        material_cost_gbp
      + (labour_minutes / 60) * CostConfig.labour_rate_gbp_per_hour
      + CostConfig.overhead_per_unit_gbp

    The VAT treatment is applied in Cairn at margin-calc time, not here.
    """
    normalized_name = models.CharField(
        max_length=120,
        unique=True,
        db_index=True,
        help_text='Canonical key produced by costs.models.normalise_blank. '
                  'Look up via normalise_blank(product.blank).',
    )
    display_name = models.CharField(
        max_length=120,
        blank=True,
        help_text='Human-friendly label, e.g. "Dick + Kirsty". Display only.',
    )
    material_cost_gbp = models.DecimalField(
        max_digits=8, decimal_places=2,
        default=Decimal('2.50'),
        help_text='Materials cost per unit, in GBP, ex-VAT. Prepopulated at £2.50.',
    )
    labour_minutes = models.DecimalField(
        max_digits=6, decimal_places=2,
        default=Decimal('0'),
        help_text='Blended labour minutes per unit (all stages combined).',
    )
    is_composite = models.BooleanField(
        default=False,
        help_text='True for multi-blank names (e.g. "DICK, KIRSTY"). Cost lookup '
                  'returns LOW confidence for composites unless an M-number '
                  'override is defined.',
    )
    sample_raw_blank = models.CharField(
        max_length=200, blank=True,
        help_text='One example of the raw Product.blank string that collapses to '
                  'this row, for editor context.',
    )
    product_count = models.PositiveIntegerField(
        default=0,
        help_text='Cached count of active products whose normalised blank matches. '
                  'Recomputed by the resync action.',
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['normalized_name']

    def __str__(self):
        return f'{self.display_name or self.normalized_name} (£{self.material_cost_gbp}, {self.labour_minutes}min)'


def normalise_marketplace(raw: Optional[str]) -> str:
    """
    Canonicalise marketplace codes for cost overrides.

    The catalogue uses Manufacture-side codes ('UK', 'US', 'CA', 'AU',
    'DE', 'FR', 'IT', 'ES', 'NL'). Cairn occasionally hands us 'GB'
    instead of 'UK' (Amazon's marketplaceId vs the user-facing label);
    we normalise both to 'UK' so a single override row covers either.

    Empty / None / whitespace → '' (= "default for this product, applies
    when no marketplace-specific override exists"). Anything unrecognised
    is uppercased and returned as-is — the lookup will then naturally
    fall through to the product default.
    """
    if not raw:
        return ''
    code = str(raw).strip().upper()
    if not code:
        return ''
    if code == 'GB':
        return 'UK'
    return code


class MNumberCostOverride(TimestampedModel):
    """
    Per-(M-number, marketplace) manual cost override. The cost engine's
    resolution order:

      1. (product, marketplace=requested)  — marketplace-specific override
      2. (product, marketplace='')         — product-level default override
      3. BlankCost on the normalised blank — engine math
      4. CostConfig.default_material_gbp   — fallback

    Empty marketplace = "applies to every marketplace unless a more
    specific row beats it." Adding a US-specific row (£14) on top of an
    existing global row (£12) routes the US channel to £14 while every
    other marketplace keeps using £12.

    Confidence is HIGH when cost_price_gbp is non-null.
    """
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='cost_overrides',
    )
    marketplace = models.CharField(
        max_length=10, blank=True, default='',
        help_text="Manufacture-side marketplace code (UK / US / CA / AU / "
                  "DE / FR / IT / ES / NL). Empty string = product-level "
                  "default that applies to all marketplaces unless a more "
                  "specific row exists. 'GB' is normalised to 'UK' on "
                  "save (use normalise_marketplace before lookup).",
    )
    cost_price_gbp = models.DecimalField(
        max_digits=8, decimal_places=2,
        null=True, blank=True,
        help_text='Total all-in cost per unit (material + labour + overhead). '
                  'Null means the row exists as a placeholder flagged for the '
                  'user to fill in; cost lookup falls through to BlankCost until set.',
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['product__m_number', 'marketplace']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'marketplace'],
                name='unique_product_marketplace_override',
            ),
        ]

    def save(self, *args, **kwargs):
        # Always normalise on the way in so 'GB' → 'UK', whitespace stripped.
        self.marketplace = normalise_marketplace(self.marketplace)
        super().save(*args, **kwargs)

    def __str__(self):
        val = f'£{self.cost_price_gbp}' if self.cost_price_gbp is not None else 'unset'
        scope = self.marketplace or 'all'
        return f'{self.product.m_number} {scope} ({val})'


class CostConfig(TimestampedModel):
    """
    Singleton configuration row. Created by the bootstrap migration. Fetch
    via `CostConfig.get()`.
    """
    SINGLETON_ID = 1

    labour_rate_gbp_per_hour = models.DecimalField(
        max_digits=6, decimal_places=2,
        default=Decimal('15.00'),
        help_text='Blended labour rate, £/hr. Spec value: £15.',
    )
    overhead_per_unit_gbp = models.DecimalField(
        max_digits=6, decimal_places=2,
        default=Decimal('6.45'),
        help_text='Fixed overhead allocation per unit, £. Spec value: £6.45 '
                  '(£24,500 monthly overhead ÷ 3,800 units/month).',
    )
    production_overhead_per_unit_gbp = models.DecimalField(
        max_digits=6, decimal_places=2,
        default=Decimal('0.00'),
        help_text=(
            'Production labour overhead added per unit on non-personalised '
            'products. Validated against Ben+Ivan weekly throughput (May '
            "2026: 1,122 units/week, ~£1.33/unit loaded). Set to £1.00 by "
            'the 0009 migration which equals the gap between per-blank '
            'bottom-up labour estimates and top-down weekly cost. Applied '
            'in get_cost_price() across all three resolution paths '
            '(override / blank / fallback) when product.is_personalised '
            'is False. Personalised products use the separate Jo+Gabby '
            'labour pool and are unaffected. Refine this value once 2-3 '
            'more weekly throughput observations are available — easier '
            'to tune one CostConfig setting than 2,575 individual '
            'MNumberCostOverride rows.'
        ),
    )
    default_material_gbp = models.DecimalField(
        max_digits=6, decimal_places=2,
        default=Decimal('2.50'),
        help_text='Material cost used when no BlankCost row matches. Low confidence.',
    )
    vat_rate_uk = models.DecimalField(
        max_digits=4, decimal_places=3,
        default=Decimal('0.200'),
        help_text='UK VAT rate used by Cairn margin engine to reclaim input VAT '
                  'on materials. EU VAT is deducted at source by Amazon.',
    )
    monthly_overhead_gbp = models.DecimalField(
        max_digits=10, decimal_places=2,
        default=Decimal('24500.00'),
        help_text='Total monthly fixed overhead (rent, utilities, salaries, etc). '
                  'Used to compute per-channel overhead allocation.',
    )
    b2b_monthly_revenue_gbp = models.DecimalField(
        max_digits=10, decimal_places=2,
        default=Decimal('0.00'),
        help_text='Manual monthly B2B/local/footfall revenue estimate in GBP. '
                  'Used alongside Amazon, Etsy, and eBay revenue for overhead allocation.',
    )
    ebay_monthly_revenue_gbp = models.DecimalField(
        max_digits=10, decimal_places=2,
        default=Decimal('0.00'),
        help_text='Manual monthly eBay revenue estimate in GBP. '
                  'Will be replaced by API-sourced data when eBay pricing is integrated.',
    )

    class Meta:
        verbose_name = 'cost config'
        verbose_name_plural = 'cost config'

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_ID
        super().save(*args, **kwargs)

    @classmethod
    def get(cls) -> 'CostConfig':
        obj, _ = cls.objects.get_or_create(pk=cls.SINGLETON_ID)
        return obj

    def __str__(self):
        return (f'CostConfig(labour=£{self.labour_rate_gbp_per_hour}/hr, '
                f'overhead=£{self.overhead_per_unit_gbp}/unit)')


def get_cost_price(product, marketplace: Optional[str] = None) -> dict:
    """
    Return the cost breakdown for a product, optionally scoped to a
    marketplace.

    Resolution order:
      1. MNumberCostOverride (product, marketplace=normalised)
      2. MNumberCostOverride (product, marketplace='')
      3. BlankCost on normalised blank
      4. CostConfig.default_material_gbp fallback

    `marketplace=None` skips step 1 entirely (legacy callers, chat tools).
    `marketplace='UK'` (or 'GB' — aliased to 'UK') tries step 1 first,
    then falls through to step 2 cleanly when no marketplace-specific
    row exists. Unknown marketplace values (e.g. 'BOGUS') just miss
    step 1 and continue normally — they don't 500.

    Source field — Cairn matches `source == 'override'` exactly to skip
    engine math and use cost_gbp directly. Any other value falls through
    to Cairn's engine path (which expects BlankCost + labour + overhead),
    so we MUST emit the bare 'override' for both default and
    marketplace-specific hits until Cairn's match is widened to a
    prefix check.

    Audit signal lives in the notes field instead of the source string;
    notes carry the exact provenance ("Personalised flat-rate £18.20",
    "Per-marketplace shipping delta US +£0.305", etc).

      'override' — any override row hit (default or marketplace-specific)
      'blank'    — engine math from BlankCost
      'fallback' — no blank, no override
    """
    cfg = CostConfig.get()
    raw = product.blank or ''
    norm = normalise_blank(raw)
    composite = is_composite_blank(raw)
    norm_mp = normalise_marketplace(marketplace)

    # Production overhead applies to GENERIC products only. Personalised
    # SKUs (Jo+Gabby labour pool) are unaffected — their flat-rate
    # override values already incorporate their own labour. See
    # CostConfig.production_overhead_per_unit_gbp docstring.
    prod_overhead = (
        Decimal('0.00') if getattr(product, 'is_personalised', False)
        else cfg.production_overhead_per_unit_gbp
    )

    def _apply_prod_overhead(base_notes: str) -> str:
        if prod_overhead <= 0:
            return base_notes
        suffix = f' +£{prod_overhead} production overhead'
        return (base_notes + suffix) if base_notes else suffix.lstrip(' +') + ' added'

    # 1 + 2. Override (marketplace-specific first, then product-level default).
    override = None
    matched_mp = ''
    if norm_mp:
        override = MNumberCostOverride.objects.filter(
            product=product, marketplace=norm_mp,
        ).first()
        if override and override.cost_price_gbp is not None:
            matched_mp = norm_mp
        else:
            override = None  # try product-level next
    if override is None:
        override = MNumberCostOverride.objects.filter(
            product=product, marketplace='',
        ).first()
    if override and override.cost_price_gbp is not None:
        # MUST emit the bare string 'override' for Cairn's exact-match
        # check (`source == 'override'`). The earlier 'override_default' /
        # 'override_uk' suffixed forms broke Cairn's override detection
        # — it fell through to engine math and lost the actual cost. Audit
        # provenance is tracked in the notes field instead.
        #
        # Production overhead (+£N for generic products) is applied here
        # on top of the stored override value. The override values were
        # set per the per-marketplace COGS briefs from earlier (US +£0.305,
        # CA/AU +£0.305, EU +£0.12) — they're material+shipping at the
        # blank level, not yet inclusive of Ben+Ivan production labour.
        # Adding prod_overhead here closes that gap consistently across
        # all override marketplaces.
        cost = (override.cost_price_gbp + prod_overhead).quantize(Decimal('0.01'))
        return {
            'm_number': product.m_number,
            'cost_gbp': cost,
            'material_gbp': override.cost_price_gbp,
            'labour_gbp': None,
            'overhead_gbp': None,
            'production_overhead_gbp': prod_overhead if prod_overhead > 0 else None,
            'labour_minutes': None,
            'source': 'override',
            'confidence': 'HIGH',
            'blank_raw': raw,
            'blank_normalized': norm,
            'is_composite': composite,
            'notes': _apply_prod_overhead(override.notes or ''),
        }

    # 2. BlankCost by normalised name.
    bc = BlankCost.objects.filter(normalized_name=norm).first() if norm else None
    if bc:
        labour_gbp = (bc.labour_minutes / Decimal('60')) * cfg.labour_rate_gbp_per_hour
        overhead_gbp = cfg.overhead_per_unit_gbp
        cost = (
            bc.material_cost_gbp + labour_gbp + overhead_gbp + prod_overhead
        ).quantize(Decimal('0.01'))
        return {
            'm_number': product.m_number,
            'cost_gbp': cost,
            'material_gbp': bc.material_cost_gbp,
            'labour_gbp': labour_gbp.quantize(Decimal('0.01')),
            'overhead_gbp': overhead_gbp,
            'production_overhead_gbp': prod_overhead if prod_overhead > 0 else None,
            'labour_minutes': bc.labour_minutes,
            'source': 'blank',
            'confidence': 'LOW' if composite else 'MEDIUM',
            'blank_raw': raw,
            'blank_normalized': norm,
            'is_composite': composite,
            'notes': _apply_prod_overhead(bc.notes or ''),
        }

    # 3. Fallback.
    overhead_gbp = cfg.overhead_per_unit_gbp
    cost = (
        cfg.default_material_gbp + overhead_gbp + prod_overhead
    ).quantize(Decimal('0.01'))
    return {
        'm_number': product.m_number,
        'cost_gbp': cost,
        'material_gbp': cfg.default_material_gbp,
        'labour_gbp': Decimal('0.00'),
        'overhead_gbp': overhead_gbp,
        'production_overhead_gbp': prod_overhead if prod_overhead > 0 else None,
        'labour_minutes': Decimal('0'),
        'source': 'fallback',
        'confidence': 'LOW',
        'blank_raw': raw,
        'blank_normalized': norm,
        'is_composite': composite,
        'notes': _apply_prod_overhead(''),
    }
