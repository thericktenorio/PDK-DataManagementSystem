from django.db import migrations


def seed_templates(apps, schema_editor):
    Template = apps.get_model("core", "Template")
    ReorderRule = apps.get_model("core", "ReorderRule")

    tpl, _ = Template.objects.get_or_create(
        name="W2",
        version="1.0",
        defaults={
            "description": "W-2 extraction rules v1",
            "rules_json": {
                "fields": [
                    {"key": "employer_ein", "pattern": r"EIN[:\u00A0 ]?(\d{2}-\d{7})"},
                    {"key": "employee_ssn", "pattern": r"SSN[:\u00A0 ]?(\d{3}-\d{2}-\d{4})"},
                    {"key": "wages_box1", "pattern": r"Box 1[:\u00A0 ]?\$?([0-9,]+\.?[0-9]{0,2})"},
                ]
            },
        },
    )

    ReorderRule.objects.get_or_create(
        template=tpl,
        defaults={
            "spec_json": {
                "strategy": "by_tag_then_index",
                "order": [
                    {"tage": "cover"},
                    {"tag": "summary"},
                    {"tag": "w2"},
                    {"tag": "other"},
                ],
            }
        },
    )


def unseed_templates(apps, schema_editor):
    Template = apps.get_model("core", "Template")
    ReorderRule = apps.get_model("core", "ReorderRule")
    try:
        tpl = Template.objects.get(name="w2", version="1.0")
        ReorderRule.objects.filter(template=tpl).delete()
        tpl.delete()
    except Template.DoesNotExist:
        pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_templates, unseed_templates),
    ]
