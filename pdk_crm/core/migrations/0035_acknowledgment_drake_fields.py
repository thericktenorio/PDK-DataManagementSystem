from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0034_productassignment_void_supersede"),
    ]

    operations = [
        migrations.AddField(
            model_name="acknowledgment",
            name="reject_code",
            field=models.CharField(
                blank=True,
                help_text="Drake reject code from the data row or Error Detail block.",
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="acknowledgment",
            name="reject_reason",
            field=models.TextField(
                blank=True,
                help_text="Reject message from the Drake Error Detail block.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="acknowledgment",
            name="submission_id",
            field=models.CharField(
                blank=True,
                help_text="Drake MEF SubmissionId for this transmission.",
                max_length=64,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="ackstaging",
            name="reject_code",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name="ackstaging",
            name="reject_reason",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ackstaging",
            name="submission_id",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
