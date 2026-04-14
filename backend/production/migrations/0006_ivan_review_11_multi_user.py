# Ivan review #11: multi-user assignment (up to 4 users per job/step).
# Adds through models, migrates existing FK data, then removes old fields.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def forwards_copy_fk_to_m2m(apps, schema_editor):
    """Copy existing assigned_to FK values into the new through models."""
    JobAssignment = apps.get_model('production', 'JobAssignment')
    JobAssignmentUser = apps.get_model('production', 'JobAssignmentUser')
    JobStep = apps.get_model('production', 'JobStep')
    JobStepUser = apps.get_model('production', 'JobStepUser')

    for a in JobAssignment.objects.filter(assigned_to__isnull=False):
        JobAssignmentUser.objects.get_or_create(
            assignment=a, user_id=a.assigned_to_id,
            defaults={'seen': a.seen},
        )

    for s in JobStep.objects.filter(assigned_to__isnull=False):
        JobStepUser.objects.get_or_create(
            step=s, user_id=s.assigned_to_id,
            defaults={'seen': s.seen},
        )


class Migration(migrations.Migration):

    dependencies = [
        ("production", "0005_job_jobstep"),
        ("products", "0009_blanktype"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Create through-model tables
        migrations.CreateModel(
            name="JobAssignmentUser",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("seen", models.BooleanField(default=False)),
                ("assignment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assignment_users", to="production.jobassignment")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="job_assignment_links", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["pk"],
                "unique_together": {("assignment", "user")},
            },
        ),
        migrations.CreateModel(
            name="JobStepUser",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("seen", models.BooleanField(default=False)),
                ("step", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="step_users", to="production.jobstep")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="job_step_links", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["pk"],
                "unique_together": {("step", "user")},
            },
        ),

        # 2. Copy existing FK data to through models
        migrations.RunPython(forwards_copy_fk_to_m2m, migrations.RunPython.noop),

        # 3. Remove old FK/seen fields
        migrations.RemoveField(model_name="jobassignment", name="assigned_to"),
        migrations.RemoveField(model_name="jobassignment", name="seen"),
        migrations.RemoveField(model_name="jobstep", name="assigned_to"),
        migrations.RemoveField(model_name="jobstep", name="seen"),

        # 4. Make Job.product nullable (M-number removed from threaded job UI)
        migrations.AlterField(
            model_name="job",
            name="product",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="jobs", to="products.product"),
        ),
        migrations.AlterField(
            model_name="job",
            name="title",
            field=models.CharField(max_length=200),
        ),
    ]
