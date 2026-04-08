from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('production', '0002_productionrecord'),
    ]

    operations = [
        migrations.AddField(
            model_name='productionorder',
            name='simple_stage',
            field=models.CharField(
                blank=True,
                choices=[('on_bench', 'On the bench'), ('in_process', 'In process')],
                max_length=20,
                null=True,
            ),
        ),
    ]
