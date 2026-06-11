from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0004_bi_views_tp_comp_date"),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentQueryAudit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("user_email", models.CharField(blank=True, default="", max_length=254)),
                ("user_role", models.CharField(blank=True, default="", max_length=50)),
                ("question", models.TextField(blank=True, default="")),
                ("sql_hash", models.CharField(blank=True, db_index=True, default="", max_length=64)),
                ("sql_text", models.TextField(blank=True, default="")),
                ("row_count", models.PositiveIntegerField(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[("SUCCESS", "Success"), ("FAILED", "Failed")],
                        default="SUCCESS",
                        max_length=16,
                    ),
                ),
                ("error_message", models.TextField(blank=True, default="")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
