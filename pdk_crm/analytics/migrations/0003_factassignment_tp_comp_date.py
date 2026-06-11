from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0002_bi_views"),
    ]

    operations = [
        migrations.AddField(
            model_name="factassignment",
            name="tp_comp_date",
            field=models.DateField(
                blank=True,
                help_text="Sunday after latest compensating ack (Pacific); computed on ETL sync.",
                null=True,
            ),
        ),
    ]
