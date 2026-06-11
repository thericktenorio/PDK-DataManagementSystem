from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_alter_internaluser_organization"),
    ]

    operations = [
        migrations.AddField(
            model_name="internaluser",
            name="rotate_background",
            field=models.BooleanField(
                default=False,
                help_text="When enabled, the app background rotates daily. When disabled, the classic beach photo is always used.",
            ),
        ),
    ]
