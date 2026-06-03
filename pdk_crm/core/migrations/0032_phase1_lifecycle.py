# Phase 1: lifecycle_state, LifecycleTransition, parser snapshot fields

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def reset_sample_workflow_state(apps, schema_editor):
    ProductAssignment = apps.get_model("core", "ProductAssignment")
    ProductAssignment.objects.update(
        lifecycle_state=None,
        completion_state="OPEN",
        is_complete=False,
        parser_status="NOT_STARTED",
        expected_ack_count=None,
        completed_at=None,
        completed_by_id=None,
        parse_job_uuid=None,
        parse_result_json=None,
        parsed_at=None,
        parser_output_refs=None,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0031_productassignmentevent"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
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
                    ("PENDING_REJECT_CODE", "Pending Reject Code"),
                ],
                help_text="Authoritative workflow state. Set to IN_CLEARING when client enters daily clearing.",
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="productassignment",
            name="parse_job_uuid",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="productassignment",
            name="parse_result_json",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="productassignment",
            name="parsed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="productassignment",
            name="parser_output_refs",
            field=models.JSONField(
                blank=True,
                help_text='List of {"kind": "main_packet"|..., "path": "..."} references to parser output files.',
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="productassignment",
            name="expected_ack_count",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Deprecated: used by legacy completion wizard and ack staging only.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="productassignment",
            name="is_complete",
            field=models.BooleanField(
                default=False,
                help_text="Legacy billing/clearing flag. Do not set from lifecycle commands; Phase 6 moves billing to lifecycle_state.",
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
                ],
                max_length=64,
            ),
        ),
        migrations.CreateModel(
            name="LifecycleTransition",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("from_state", models.CharField(blank=True, default="", max_length=32)),
                (
                    "to_state",
                    models.CharField(
                        choices=[
                            ("IN_CLEARING", "In Clearing"),
                            ("CLEARING_COMPLETE", "Clearing Complete"),
                            ("AWAITING_PAYMENT", "Awaiting Payment"),
                            ("READY_FOR_REVIEW", "Ready for Review"),
                            ("IN_REVIEW", "In Review"),
                            ("FILED", "Filed"),
                            ("ACK_RECONCILING", "Ack Reconciling"),
                            ("CLOSED", "Closed"),
                            ("PENDING_REJECT_CODE", "Pending Reject Code"),
                        ],
                        max_length=32,
                    ),
                ),
                ("created_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("note", models.TextField(blank=True, default="")),
                ("payload", models.JSONField(blank=True, null=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lifecycle_transitions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "product_assignment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lifecycle_transitions",
                        to="core.productassignment",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at", "id"],
                "indexes": [
                    models.Index(fields=["product_assignment", "created_at"], name="core_lifecy_product_6e8f0d_idx"),
                    models.Index(fields=["to_state", "created_at"], name="core_lifecy_to_stat_8a1b2c_idx"),
                ],
            },
        ),
        migrations.RunPython(reset_sample_workflow_state, migrations.RunPython.noop),
    ]
