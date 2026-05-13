"""
Add CostConfig.production_overhead_per_unit_gbp + set singleton to £1.00.

Per the Cairn-session COGS brief (8 May 2026, applied 13 May): generic
blank cost values (the per-(M-number, marketplace='') overrides we
populated in earlier briefs) are material+shipping costs at the blank
level and don't include Ben+Ivan production labour.

Validated against the May 2026 weekly throughput snapshot:
  1,122 units shipped in week of 8 May
  ~£1,419/week loaded labour (Ivan FT + Ben FT + Christine + Nyo/Archie)
  → ~£1.33/unit loaded labour
  Existing per-blank bottom-up captured ~£0.30/unit
  Gap: ~£1.00/unit production overhead — added here.

Single CostConfig setting (rather than baking into 2,575 individual
override rows) so future calibration is a one-row update. Refine
once 2-3 more weekly observations are available.

Personalised products (is_personalised=True, ~18 products dominated
by M0634 at £13.12) are NOT affected — their override values already
include the Jo+Gabby personalised labour pool. Skip handled in
costs.models.get_cost_price().

Headline impact: Amazon channel net profit drops ~£3-5k/month
because labour is now being correctly attributed to COGS rather than
sitting unallocated in operating overhead. Cash retention unchanged
— same cost, different bucket.
"""
from decimal import Decimal

from django.db import migrations, models


def _set_singleton_value(apps, schema_editor):
    CostConfig = apps.get_model('costs', 'CostConfig')
    cfg, _ = CostConfig.objects.get_or_create(pk=1)
    cfg.production_overhead_per_unit_gbp = Decimal('1.00')
    cfg.save(update_fields=['production_overhead_per_unit_gbp', 'updated_at'])


def _clear_singleton_value(apps, schema_editor):
    # Reverse path: zero the field so the column can be dropped safely
    # by the schema migration below.
    CostConfig = apps.get_model('costs', 'CostConfig')
    CostConfig.objects.filter(pk=1).update(
        production_overhead_per_unit_gbp=Decimal('0.00'),
    )


class Migration(migrations.Migration):

    dependencies = [
        ('costs', '0005_cost_override_per_marketplace'),
    ]

    operations = [
        migrations.AddField(
            model_name='costconfig',
            name='production_overhead_per_unit_gbp',
            field=models.DecimalField(
                max_digits=6, decimal_places=2,
                default=Decimal('0.00'),
                help_text=(
                    'Production labour overhead added per unit on '
                    'non-personalised products. Validated against Ben+Ivan '
                    'weekly throughput (May 2026: 1,122 units/week, '
                    '~£1.33/unit loaded). Set to £1.00 by the 0006 '
                    'migration which equals the gap between per-blank '
                    'bottom-up labour estimates and top-down weekly cost. '
                    'Applied in get_cost_price() across all three '
                    'resolution paths when product.is_personalised is False.'
                ),
            ),
        ),
        migrations.RunPython(_set_singleton_value, _clear_singleton_value),
    ]
