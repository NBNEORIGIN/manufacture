from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0008_shipping_dimensions'),
    ]

    operations = [
        migrations.CreateModel(
            name='BlankType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(
                    max_length=80,
                    unique=True,
                    help_text='Canonical name, e.g. SAVILLE, DICK, DICK+TOM. Case preserved but '
                              'matched case-insensitively against Product.blank.',
                )),
                ('length_cm', models.DecimalField(max_digits=6, decimal_places=1)),
                ('width_cm', models.DecimalField(max_digits=6, decimal_places=1)),
                ('height_cm', models.DecimalField(max_digits=6, decimal_places=1)),
                ('weight_g', models.PositiveIntegerField(help_text='Packed weight in grams')),
                ('notes', models.TextField(blank=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='product',
            name='shipping_dims_overridden',
            field=models.BooleanField(
                default=False,
                help_text='True if shipping_* were set manually and should NOT be overwritten by '
                          'BlankType.apply_to_products(). Set automatically by the per-product editor.',
            ),
        ),
        migrations.AddField(
            model_name='product',
            name='blank_type',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='products',
                to='products.blanktype',
                help_text='Canonical blank type this product is packaged as. Source of shipping dims '
                          'unless shipping_dims_overridden is True.',
            ),
        ),
    ]
