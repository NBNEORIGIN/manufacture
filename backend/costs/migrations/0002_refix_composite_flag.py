"""
Recompute BlankCost.is_composite under the stricter rule: only flag composites
that contain an explicit separator (, + & /), not every multi-word name.
"""
import re

from django.db import migrations


def recompute(apps, schema_editor):
    BlankCost = apps.get_model('costs', 'BlankCost')
    for bc in BlankCost.objects.all():
        should_be = bool(re.search(r'[,+&/]', bc.sample_raw_blank or ''))
        if bc.is_composite != should_be:
            bc.is_composite = should_be
            bc.save(update_fields=['is_composite', 'updated_at'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('costs', '0001_initial')]
    operations = [migrations.RunPython(recompute, reverse_code=noop)]
