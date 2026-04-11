from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0006_alter_product_blank_family_and_more'),
    ]

    operations = [
        migrations.RenameField(
            model_name='productdesign',
            old_name='nonename',
            new_name='mao',
        ),
    ]
