from __future__ import annotations

from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("django_hookflow", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowrun",
            name="retry_attempt",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Current retry attempt number for failed steps",
            ),
        ),
    ]
