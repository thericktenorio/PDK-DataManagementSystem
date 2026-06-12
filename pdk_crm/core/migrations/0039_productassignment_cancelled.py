import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0038_organization_auto_send_invoices_enabled"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="productassignment",
            name="cancelled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="productassignment",
            name="cancellation_reason",
            field=models.TextField(
                blank=True,
                help_text="Staff-provided reason when the assignment is cancelled before completion.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="productassignment",
            name="cancelled_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="cancelled_product_assignments",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="productassignment",
            name="lifecycle_state",
            field=models.CharField(
                blank=True,
                choices=[
                    ("IN_CLEARING", "In Clearing"),
                    ("CLEARING_COMPLETE", "Clearing Complete"),
                    ("AWAITING_PAYMENT", "Awaiting Payment"),
                    ("READY_FOR_REVIEW", "Ready for Review"),
                    ("IN_REVIEW", "In Review"),
                    ("FILED", "Filed"),
                    ("ACK_RECONCILING", "Ack Reconciling"),
                    ("CLOSED", "Closed"),
                    ("PENDING_REJECT_CORRECTION", "Pending Reject Correction"),
                    ("CANCELLED", "Cancelled"),
                ],
                help_text="Authoritative workflow state. Set to IN_CLEARING when client enters daily clearing.",
                max_length=32,
                null=True,
            ),
        ),
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
                    ("ASSIGNMENT_CANCELLED", "ASSIGNMENT_CANCELLED"),
                ],
                max_length=64,
            ),
        ),
    ]
