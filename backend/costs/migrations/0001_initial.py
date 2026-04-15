from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


def seed_initial_data(apps, schema_editor):
    """
    Create CostConfig singleton + one BlankCost per distinct normalised
    Product.blank across active products. Prepopulates materials at £2.50.
    """
    import re

    def normalise_blank(raw):
        if not raw:
            return ''
        cleaned = re.sub(r'[^A-Za-z0-9]+', ' ', raw).strip().upper()
        return re.sub(r'\s+', ' ', cleaned)

    def is_composite(raw):
        if not raw:
            return False
        return bool(re.search(r'[,+&/]', raw))

    CostConfig = apps.get_model('costs', 'CostConfig')
    BlankCost = apps.get_model('costs', 'BlankCost')
    Product = apps.get_model('products', 'Product')

    # Singleton
    CostConfig.objects.update_or_create(
        pk=1,
        defaults=dict(
            labour_rate_gbp_per_hour=Decimal('15.00'),
            overhead_per_unit_gbp=Decimal('6.45'),
            default_material_gbp=Decimal('2.50'),
            vat_rate_uk=Decimal('0.200'),
        ),
    )

    counts = {}
    for raw in Product.objects.filter(active=True).values_list('blank', flat=True):
        norm = normalise_blank(raw)
        if not norm:
            continue
        entry = counts.setdefault(norm, {'count': 0, 'sample': raw or ''})
        entry['count'] += 1

    for norm, info in counts.items():
        BlankCost.objects.get_or_create(
            normalized_name=norm,
            defaults=dict(
                display_name=(info['sample'] or '').strip().upper(),
                material_cost_gbp=Decimal('2.50'),
                labour_minutes=Decimal('0'),
                is_composite=is_composite(info['sample']),
                sample_raw_blank=info['sample'],
                product_count=info['count'],
                notes='',
            ),
        )


def unseed(apps, schema_editor):
    apps.get_model('costs', 'BlankCost').objects.all().delete()
    apps.get_model('costs', 'CostConfig').objects.all().delete()


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('products', '0009_blanktype'),
    ]

    operations = [
        migrations.CreateModel(
            name='CostConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('labour_rate_gbp_per_hour', models.DecimalField(
                    decimal_places=2, default=Decimal('15.00'), max_digits=6)),
                ('overhead_per_unit_gbp', models.DecimalField(
                    decimal_places=2, default=Decimal('6.45'), max_digits=6)),
                ('default_material_gbp', models.DecimalField(
                    decimal_places=2, default=Decimal('2.50'), max_digits=6)),
                ('vat_rate_uk', models.DecimalField(
                    decimal_places=3, default=Decimal('0.200'), max_digits=4)),
            ],
            options={
                'verbose_name': 'cost config',
                'verbose_name_plural': 'cost config',
            },
        ),
        migrations.CreateModel(
            name='BlankCost',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('normalized_name', models.CharField(db_index=True, max_length=120, unique=True)),
                ('display_name', models.CharField(blank=True, max_length=120)),
                ('material_cost_gbp', models.DecimalField(
                    decimal_places=2, default=Decimal('2.50'), max_digits=8)),
                ('labour_minutes', models.DecimalField(
                    decimal_places=2, default=Decimal('0'), max_digits=6)),
                ('is_composite', models.BooleanField(default=False)),
                ('sample_raw_blank', models.CharField(blank=True, max_length=200)),
                ('product_count', models.PositiveIntegerField(default=0)),
                ('notes', models.TextField(blank=True)),
            ],
            options={'ordering': ['normalized_name']},
        ),
        migrations.CreateModel(
            name='MNumberCostOverride',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('cost_price_gbp', models.DecimalField(
                    blank=True, decimal_places=2, max_digits=8, null=True)),
                ('notes', models.TextField(blank=True)),
                ('product', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='cost_override',
                    to='products.product')),
            ],
            options={'ordering': ['product__m_number']},
        ),
        migrations.RunPython(seed_initial_data, reverse_code=unseed),
    ]
