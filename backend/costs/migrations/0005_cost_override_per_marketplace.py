"""
Marketplace-aware MNumberCostOverride.

Existing rows had OneToOneField(product) — one override per product.
The new schema is ForeignKey(product) + marketplace + unique_together
(product, marketplace). Existing rows migrate as marketplace='' so
they keep behaving as the product-level default.

Cairn's /ami/margin/per-sku now passes ?marketplace= through, so
adding a (product, marketplace='UK') row beats the (product, '')
row only on UK calls. Other marketplaces continue to use the default
until a specific row is created.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('costs', '0004_ebay_revenue'),
        ('products', '0001_initial'),
    ]

    operations = [
        # 1. Drop the OneToOneField unique constraint by switching to
        #    ForeignKey. Django generates SQL that preserves the column
        #    and existing rows; the unique index is dropped.
        migrations.AlterField(
            model_name='mnumbercostoverride',
            name='product',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='cost_overrides',
                to='products.product',
            ),
        ),
        # 2. Add the marketplace column. Existing rows default to ''
        #    (= product-level default).
        migrations.AddField(
            model_name='mnumbercostoverride',
            name='marketplace',
            field=models.CharField(
                blank=True,
                default='',
                help_text=(
                    "Manufacture-side marketplace code (UK / US / CA / AU / "
                    "DE / FR / IT / ES / NL). Empty string = product-level "
                    "default that applies to all marketplaces unless a more "
                    "specific row exists. 'GB' is normalised to 'UK' on "
                    "save (use normalise_marketplace before lookup)."
                ),
                max_length=10,
            ),
        ),
        # 3. Composite unique on (product, marketplace) — replaces the
        #    old OneToOneField unique-on-product-only.
        migrations.AddConstraint(
            model_name='mnumbercostoverride',
            constraint=models.UniqueConstraint(
                fields=('product', 'marketplace'),
                name='unique_product_marketplace_override',
            ),
        ),
        # 4. Reflect the new ordering on the Meta.
        migrations.AlterModelOptions(
            name='mnumbercostoverride',
            options={'ordering': ['product__m_number', 'marketplace']},
        ),
    ]
