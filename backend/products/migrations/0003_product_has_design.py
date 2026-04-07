from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('products', '0002_alter_sku_channel'),
    ]
    operations = [
        migrations.AddField(
            model_name='product',
            name='has_design',
            field=models.BooleanField(default=False, help_text='Design file is ready for this product'),
        ),
    ]
