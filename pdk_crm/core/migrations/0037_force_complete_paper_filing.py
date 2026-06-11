from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0036_alter_productassignmentevent_event_type"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="productassignment",
            name="force_completed_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When set, PA was force-closed despite reject acks; counts as A for TP Comp Dt.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="product",
            name="product_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("TBD", "TBD"),
                    ("Personal Taxes", "Personal Taxes"),
                    ("Corporate Taxes", "Corporate Taxes"),
                    ("Free Extension", "Free Extension"),
                    ("Paid Extension", "Paid Extension"),
                    ("Amendment 1", "Amendment 1"),
                    ("Amendment 2", "Amendment 2"),
                    ("Amendment 3", "Amendment 3"),
                    ("Withholdings Adjustment", "Withholdings Adjustment"),
                    ("Advisory", "Advisory"),
                    ("Reject Correction", "Reject Correction"),
                    ("Paper Filing", "Paper Filing"),
                ],
                default="TBD",
                max_length=100,
                null=True,
            ),
        ),
        migrations.CreateModel(
            name="PaperFilingDetail",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "jurisdiction",
                    models.CharField(
                        choices=[("federal", "Federal"), ("state", "State")],
                        max_length=16,
                    ),
                ),
                ("form_type", models.CharField(help_text="Form code (1040, CA540, …)", max_length=15)),
                (
                    "mailed_by",
                    models.CharField(
                        choices=[("firm", "Firm"), ("client", "Client")],
                        max_length=16,
                    ),
                ),
                ("sent_date", models.DateField()),
                ("tracking", models.CharField(blank=True, default="", max_length=64)),
                ("notes", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="paper_filing_details",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "product_assignment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="paper_filing_details",
                        to="core.productassignment",
                    ),
                ),
            ],
            options={
                "ordering": ["sent_date", "id"],
            },
        ),
    ]
