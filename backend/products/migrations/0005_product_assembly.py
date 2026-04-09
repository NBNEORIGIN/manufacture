from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0004_productdesign'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='machine_type',
            field=models.CharField(
                blank=True,
                choices=[('UV', 'UV'), ('SUB', 'SUB')],
                default='',
                max_length=3,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='product',
            name='blank_family',
            field=models.CharField(
                blank=True,
                choices=[
                    ('A4s', "A4's"),
                    ('A5s', "A5's"),
                    ('Dicks', "Dick's"),
                    ('Stakes', 'Stakes'),
                    ('Myras', "Myra's"),
                    ('Donalds', "Donald's"),
                    ('Hanging', 'Hanging signs'),
                ],
                default='',
                max_length=20,
            ),
            preserve_default=False,
        ),
    ]
