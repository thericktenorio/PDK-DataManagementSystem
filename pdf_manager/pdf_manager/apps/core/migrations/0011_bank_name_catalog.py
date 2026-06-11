from django.db import migrations


FIELD_CATALOG = [
    {"key": "taxpayer_first_name", "tier": "A", "source_roles": ["extract_client_letter"]},
    {"key": "tax_year", "tier": "A", "source_roles": ["extract_client_letter"]},
    {"key": "taxpayer_full_name", "tier": "C", "source_roles": ["extract_client_letter"]},
    {
        "key": "taxpayer_tin",
        "tier": "A",
        "source_roles": [
            "extract_diagnostic_invoice",
            "extract_tin_comparison",
            "form_federal",
        ],
    },
    {"key": "federal_amount", "tier": "B", "source_roles": ["extract_client_letter"]},
    {"key": "states", "tier": "B", "source_roles": ["extract_client_letter"]},
    {
        "key": "last_4_of_account",
        "tier": "B",
        "source_roles": ["extract_client_letter", "extract_dd_pmt"],
    },
    {"key": "bank_name", "tier": "B", "source_roles": ["extract_dd_pmt"]},
    {"key": "mailing_address", "tier": "B", "source_roles": ["extract_client_letter"]},
    {"key": "mailing_address_line1", "tier": "C", "source_roles": ["extract_client_letter"]},
    {"key": "mailing_city", "tier": "C", "source_roles": ["extract_client_letter"]},
    {"key": "mailing_state", "tier": "C", "source_roles": ["extract_client_letter"]},
    {"key": "mailing_zip", "tier": "C", "source_roles": ["extract_client_letter"]},
    {
        "key": "tax_prep_fee",
        "tier": "B",
        "source_roles": [
            "extract_tpg_fee",
            "extract_diagnostic_invoice",
            "extract_bill_fee",
        ],
    },
    {"key": "has_tpg_pages", "tier": "B", "source_roles": ["outline"]},
]


def update_drake_template(apps, schema_editor):
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


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_alter_parsejob_status"),
    ]

    operations = [
        migrations.RunPython(update_drake_template, migrations.RunPython.noop),
    ]
