"""Add cancellation / void audit fields to fact_assignment and bi_assignments view."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0005_agent_query_audit"),
    ]

    operations = [
        migrations.AddField(
            model_name="factassignment",
            name="cancelled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="factassignment",
            name="cancellation_reason",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="factassignment",
            name="voided_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunSQL(
            sql="""
            DROP VIEW IF EXISTS bi_assignments;
            CREATE VIEW bi_assignments AS
            SELECT
                source_pa_id,
                source_client_id,
                tax_season_year,
                source_product_id,
                lifecycle_state,
                payment_method,
                product_type,
                filing_type,
                tax_year,
                is_active,
                is_archived,
                voided_at,
                cancelled_at,
                cancellation_reason,
                preparer_email,
                expected_fee,
                discount,
                expected_fee_at,
                invoice_amount,
                invoice_balance,
                invoice_paid_amount,
                invoice_status,
                invoice_paid_at,
                actual_revenue_recognized,
                actual_paid_at,
                revenue_gap,
                days_to_payment,
                clearing_complete_at,
                ready_for_review_at,
                filed_at,
                closed_at,
                review_started_at,
                ack_count,
                ack_accepted_count,
                ack_rejected_count,
                expected_ack_count,
                tp_comp_date,
                has_parser_snapshot,
                parser_federal_amount,
                parser_states,
                parser_tax_prep_fee,
                intake_created_at,
                etl_synced_at
            FROM analytics_factassignment;
            """,
            reverse_sql="""
            DROP VIEW IF EXISTS bi_assignments;
            CREATE VIEW bi_assignments AS
            SELECT
                source_pa_id,
                source_client_id,
                tax_season_year,
                source_product_id,
                lifecycle_state,
                payment_method,
                product_type,
                filing_type,
                tax_year,
                is_active,
                is_archived,
                preparer_email,
                expected_fee,
                discount,
                expected_fee_at,
                invoice_amount,
                invoice_balance,
                invoice_paid_amount,
                invoice_status,
                invoice_paid_at,
                actual_revenue_recognized,
                actual_paid_at,
                revenue_gap,
                days_to_payment,
                clearing_complete_at,
                ready_for_review_at,
                filed_at,
                closed_at,
                review_started_at,
                ack_count,
                ack_accepted_count,
                ack_rejected_count,
                expected_ack_count,
                tp_comp_date,
                has_parser_snapshot,
                parser_federal_amount,
                parser_states,
                parser_tax_prep_fee,
                intake_created_at,
                etl_synced_at
            FROM analytics_factassignment;
            """,
        ),
    ]
