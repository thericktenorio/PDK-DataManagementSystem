"""
Sync CRM operational data into the analytics warehouse database.

Usage:
  python manage.py sync_analytics_warehouse
  python manage.py sync_analytics_warehouse --full
"""
from django.core.management.base import BaseCommand, CommandError

from analytics.models import EtlRun
from analytics.services.etl import analytics_enabled, run_analytics_etl


class Command(BaseCommand):
    help = "ETL tax_operations → analytics warehouse (incremental by default)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--full",
            action="store_true",
            help="Full refresh of all fact tables (use for initial load or repair).",
        )

    def handle(self, *args, **options):
        if not analytics_enabled():
            raise CommandError(
                "ANALYTICS_ENABLED is false or analytics database is not configured."
            )

        full = options["full"]
        if not full:
            has_success = (
                EtlRun.objects.using("analytics")
                .filter(status=EtlRun.Status.SUCCESS)
                .exists()
            )
            if not has_success:
                full = True
                self.stdout.write(
                    self.style.WARNING("No successful ETL run yet; performing full refresh.")
                )

        run = run_analytics_etl(full=full)
        if run.status == EtlRun.Status.FAILED:
            raise CommandError(run.error_message or "ETL failed")

        self.stdout.write(
            self.style.SUCCESS(
                f"ETL {run.status} (full={run.is_full_refresh}): "
                f"assignments={run.rows_assignments} invoices={run.rows_invoices} "
                f"acks={run.rows_acks} lifecycle_events={run.rows_lifecycle_events} "
                f"dimensions={run.rows_dimensions}"
            )
        )
