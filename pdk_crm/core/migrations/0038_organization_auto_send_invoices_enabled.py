from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0037_force_complete_paper_filing"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="auto_send_invoices_enabled",
            field=models.BooleanField(
                default=False,
                help_text="When True, draft invoices auto-send after the quiet period elapses.",
            ),
        ),
    ]
