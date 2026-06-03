"""
PostgreSQL views for Power BI / external BI tools (read-only friendly names).
Applied only on the analytics database.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE VIEW bi_seasons AS
            SELECT
                source_tax_season_id,
                year AS tax_season_year,
                start_date,
                end_date,
                is_active,
                is_archived,
                synced_at
            FROM analytics_dimtaxseason;

            CREATE OR REPLACE VIEW bi_clients AS
            SELECT
                source_client_id,
                name AS client_name,
                tin,
                email,
                phone,
                filing_type,
                prior_filing_type,
                appointment_type,
                client_created_at,
                synced_at
            FROM analytics_dimclient;

            CREATE OR REPLACE VIEW bi_assignments AS
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
                has_parser_snapshot,
                parser_federal_amount,
                parser_states,
                parser_tax_prep_fee,
                intake_created_at,
                etl_synced_at
            FROM analytics_factassignment;

            CREATE OR REPLACE VIEW bi_invoices AS
            SELECT
                source_invoice_id,
                source_client_id,
                status,
                qbo_invoice_number,
                amount,
                balance,
                paid_amount,
                is_paid,
                txn_date,
                due_date,
                created_at,
                last_activity_at,
                linked_pa_count,
                etl_synced_at
            FROM analytics_factinvoice;

            CREATE OR REPLACE VIEW bi_last_etl AS
            SELECT
                id,
                started_at,
                finished_at,
                status,
                is_full_refresh,
                rows_assignments,
                rows_invoices,
                rows_acks,
                rows_lifecycle_events,
                rows_dimensions
            FROM analytics_etlrun
            WHERE status = 'SUCCESS'
            ORDER BY finished_at DESC NULLS LAST
            LIMIT 1;
            """,
            reverse_sql="""
            DROP VIEW IF EXISTS bi_last_etl;
            DROP VIEW IF EXISTS bi_invoices;
            DROP VIEW IF EXISTS bi_assignments;
            DROP VIEW IF EXISTS bi_clients;
            DROP VIEW IF EXISTS bi_seasons;
            """,
        ),
    ]
