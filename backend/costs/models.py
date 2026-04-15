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
    """A blank is 'composite' if it names two or more sub-blanks (comma/plus/&)."""
    if not raw:
        return False
    return bool(re.search(r'[,+&/]', raw)) or len(normalise_blank(raw).split()) >= 2


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


class MNumberCostOverride(TimestampedModel):
    """
    Per-M-number manual cost override. Used when a product's cost cannot be
    derived from a single blank (composite blanks, special cases) or simply
    needs a manual figure. When set, bypasses BlankCost entirely.

    Confidence is HIGH when cost_price_gbp is non-null.
    """
    product = models.OneToOneField(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='cost_override',
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
        ordering = ['product__m_number']

    def __str__(self):
        val = f'£{self.cost_price_gbp}' if self.cost_price_gbp is not None else 'unset'
        return f'{self.product.m_number} override ({val})'


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


def get_cost_price(product) -> dict:
    """
    Return the cost breakdown for a product. Used by Cairn via
    GET /api/costs/price/{m_number}/ and by the admin UI.

    Shape:
      {
        "m_number": "M0001",
        "cost_gbp": Decimal,          # total all-in cost per unit
        "material_gbp": Decimal,      # materials only (ex-VAT)
        "labour_gbp": Decimal,        # labour only
        "overhead_gbp": Decimal,      # overhead allocation
        "labour_minutes": Decimal,
        "source": "override" | "blank" | "fallback",
        "confidence": "HIGH" | "MEDIUM" | "LOW",
        "blank_raw": "DICK, KIRSTY",
        "blank_normalized": "DICK KIRSTY",
        "is_composite": bool,
        "notes": str,
      }
    """
    cfg = CostConfig.get()
    raw = product.blank or ''
    norm = normalise_blank(raw)
    composite = is_composite_blank(raw)

    # 1. Override takes precedence.
    override = MNumberCostOverride.objects.filter(product=product).first()
    if override and override.cost_price_gbp is not None:
        return {
            'm_number': product.m_number,
            'cost_gbp': override.cost_price_gbp,
            'material_gbp': None,
            'labour_gbp': None,
            'overhead_gbp': None,
            'labour_minutes': None,
            'source': 'override',
            'confidence': 'HIGH',
            'blank_raw': raw,
            'blank_normalized': norm,
            'is_composite': composite,
            'notes': override.notes,
        }

    # 2. BlankCost by normalised name.
    bc = BlankCost.objects.filter(normalized_name=norm).first() if norm else None
    if bc:
        labour_gbp = (bc.labour_minutes / Decimal('60')) * cfg.labour_rate_gbp_per_hour
        overhead_gbp = cfg.overhead_per_unit_gbp
        cost = (bc.material_cost_gbp + labour_gbp + overhead_gbp).quantize(Decimal('0.01'))
        return {
            'm_number': product.m_number,
            'cost_gbp': cost,
            'material_gbp': bc.material_cost_gbp,
            'labour_gbp': labour_gbp.quantize(Decimal('0.01')),
            'overhead_gbp': overhead_gbp,
            'labour_minutes': bc.labour_minutes,
            'source': 'blank',
            'confidence': 'LOW' if composite else 'MEDIUM',
            'blank_raw': raw,
            'blank_normalized': norm,
            'is_composite': composite,
            'notes': bc.notes,
        }

    # 3. Fallback.
    overhead_gbp = cfg.overhead_per_unit_gbp
    cost = (cfg.default_material_gbp + overhead_gbp).quantize(Decimal('0.01'))
    return {
        'm_number': product.m_number,
        'cost_gbp': cost,
        'material_gbp': cfg.default_material_gbp,
        'labour_gbp': Decimal('0.00'),
        'overhead_gbp': overhead_gbp,
        'labour_minutes': Decimal('0'),
        'source': 'fallback',
        'confidence': 'LOW',
        'blank_raw': raw,
        'blank_normalized': norm,
        'is_composite': composite,
        'notes': '',
    }
