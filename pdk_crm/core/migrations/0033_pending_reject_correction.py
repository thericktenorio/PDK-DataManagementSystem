# Phase 8: rename PENDING_REJECT_CODE → PENDING_REJECT_CORRECTION

from django.db import migrations, models


LIFECYCLE_CHOICES = [
    ("IN_CLEARING", "In Clearing"),
    ("CLEARING_COMPLETE", "Clearing Complete"),
    ("AWAITING_PAYMENT", "Awaiting Payment"),
    ("READY_FOR_REVIEW", "Ready for Review"),
    ("IN_REVIEW", "In Review"),
    ("FILED", "Filed"),
    ("ACK_RECONCILING", "Ack Reconciling"),
    ("CLOSED", "Closed"),
    ("PENDING_REJECT_CORRECTION", "Pending Reject Correction"),
]


def rename_pending_reject_state(apps, schema_editor):
    ProductAssignment = apps.get_model("core", "ProductAssignment")
    LifecycleTransition = apps.get_model("core", "LifecycleTransition")

    ProductAssignment.objects.filter(lifecycle_state="PENDING_REJECT_CODE").update(
        lifecycle_state="PENDING_REJECT_CORRECTION"
    )
    LifecycleTransition.objects.filter(from_state="PENDING_REJECT_CODE").update(
        from_state="PENDING_REJECT_CORRECTION"
    )
    LifecycleTransition.objects.filter(to_state="PENDING_REJECT_CODE").update(
        to_state="PENDING_REJECT_CORRECTION"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0032_phase1_lifecycle"),
    ]

    operations = [
        migrations.RunPython(rename_pending_reject_state, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="productassignment",
            name="lifecycle_state",
            field=models.CharField(
                blank=True,
                choices=LIFECYCLE_CHOICES,
                help_text="Authoritative workflow state. Set to IN_CLEARING when client enters daily clearing.",
                max_length=32,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="productassignment",
            name="expected_ack_count",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Staff-set count of expected Drake acks (federal + state forms). Required before CLOSED.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="lifecycletransition",
            name="to_state",
            field=models.CharField(choices=LIFECYCLE_CHOICES, max_length=32),
        ),
    ]
