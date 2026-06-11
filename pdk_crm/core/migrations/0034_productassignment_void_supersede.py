from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0033_pending_reject_correction"),
    ]

    operations = [
        migrations.AddField(
            model_name="productassignment",
            name="voided_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="productassignment",
            name="voided_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="voided_product_assignments",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="productassignment",
            name="void_reason",
            field=models.CharField(
                blank=True,
                choices=[("PDF_REPLACED", "PDF replaced via global upload")],
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="productassignment",
            name="superseded_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="supersedes",
                to="core.productassignment",
            ),
        ),
    ]
