from django.db import migrations, models
import django.db.models.deletion


FIELD_CATALOG = [
    {"key": "taxpayer_first_name", "tier": "A", "source_roles": ["extract_client_letter"]},
    {"key": "tax_year", "tier": "A", "source_roles": ["extract_client_letter"]},
    {"key": "taxpayer_full_name", "tier": "C", "source_roles": ["extract_client_letter"]},
    {"key": "federal_amount", "tier": "B", "source_roles": ["extract_client_letter"]},
    {"key": "states", "tier": "B", "source_roles": ["extract_client_letter"]},
    {"key": "last_4_of_account", "tier": "B", "source_roles": ["extract_client_letter"]},
    {"key": "mailing_address", "tier": "B", "source_roles": ["extract_client_letter"]},
    {"key": "mailing_address_line1", "tier": "C", "source_roles": ["extract_client_letter"]},
    {"key": "mailing_city", "tier": "C", "source_roles": ["extract_client_letter"]},
    {"key": "mailing_state", "tier": "C", "source_roles": ["extract_client_letter"]},
    {"key": "mailing_zip", "tier": "C", "source_roles": ["extract_client_letter"]},
    {"key": "tax_prep_fee", "tier": "B", "source_roles": ["extract_bill"]},
    {"key": "has_tpg_pages", "tier": "B", "source_roles": ["outline"]},
]


def seed_drake_template(apps, schema_editor):
    Template = apps.get_model("core", "Template")
    Template.objects.update_or_create(
        name="DRAKE",
        version="1",
        defaults={
            "description": "Drake tax return packet — schema v1 extraction catalog",
            "rules_json": {
                "schema_version": 1,
                "field_catalog": FIELD_CATALOG,
            },
        },
    )


def unseed_drake_template(apps, schema_editor):
    Template = apps.get_model("core", "Template")
    Template.objects.filter(name="DRAKE", version="1").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_parsejob_payment_voucher_pdf_path"),
    ]

    operations = [
        migrations.AddField(
            model_name="extractedfield",
            name="extraction_method",
            field=models.CharField(
                blank=True,
                help_text="pymupdf, ocr, or outline",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="extractedfield",
            name="source_page_index",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="extractedfield",
            name="parse_job",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="extracted_fields",
                to="core.parsejob",
            ),
        ),
        migrations.AddIndex(
            model_name="extractedfield",
            index=models.Index(fields=["parse_job"], name="ef_parse_job_idx"),
        ),
        migrations.RunPython(seed_drake_template, unseed_drake_template),
    ]
