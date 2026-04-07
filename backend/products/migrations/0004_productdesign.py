from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0003_product_has_design'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductDesign',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rolf', models.BooleanField(default=False)),
                ('mimaki', models.BooleanField(default=False)),
                ('epson', models.BooleanField(default=False)),
                ('mutoh', models.BooleanField(default=False)),
                ('nonename', models.BooleanField(default=False)),
                ('product', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='design',
                    to='products.product',
                )),
            ],
        ),
    ]
