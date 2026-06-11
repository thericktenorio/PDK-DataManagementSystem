from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0035_acknowledgment_drake_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="productassignmentevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("PA_COMPLETED", "PA_COMPLETED"),
                    ("CLEARING_COMPLETED", "CLEARING_COMPLETED"),
                    ("READY_FOR_REVIEW", "READY_FOR_REVIEW"),
                    ("FILED", "FILED"),
                    ("CLOSED", "CLOSED"),
                    ("PARSE_SUPERSEDED", "PARSE_SUPERSEDED"),
                ],
                max_length=64,
            ),
        ),
    ]
