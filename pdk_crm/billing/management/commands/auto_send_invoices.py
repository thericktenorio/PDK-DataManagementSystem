from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from billing.models import Invoice
from billing.policies import is_invoice_eligible_to_send
from billing.services.sender import send_invoice_now_for


class Command(BaseCommand):
    help = "Auto-send draft invoices after the quiet period elapses."

    def handle(self, *args, **options):
        from django.conf import settings

        if not getattr(settings, "FEATURE_AUTO_SEND_INVOICES", False):
            self.stdout.write("FEATURE_AUTO_SEND_INVOICES is disabled; skipping.")
            return

        from core.models import Organization

        if not Organization.objects.filter(
            auto_send_invoices_enabled=True,
            is_active=True,
        ).exists():
            self.stdout.write("No organization has auto-send enabled; skipping.")
            return

        candidates = (Invoice.objects.filter(status__in = [Invoice.INVOICE_STATUS_DRAFT, Invoice.INVOICE_STATUS_ISSUED]).order_by("last_activity_at")[:100])
        
        sent = 0
        for inv in candidates:
            try:
                if not is_invoice_eligible_to_send(inv):
                    continue

                client = inv.client
                #tax year needed... may need to adjust following depending on tax year model implementation
                tax_year = getattr(inv, "qbo_txn_date", None) and inv.qbo_txn_date.year
                #for robust behavior, may store tax_year on the invoice or infer from PA records
                #the following follows PA records

                from billing.selectors import clearing_complete_pas_for_invoice
                from billing.mappers import pa_to_qbo_sales_item

                pa_qs = clearing_complete_pas_for_invoice(inv)
                if not pa_qs.exists():
                    # nothing to send, then skip
                    continue
                send_invoice_now_for(
                    client,
                    tax_year, # your selector can ignore this if it binds by invoice
                    pa_queryset = pa_qs,
                    line_builder = pa_to_qbo_sales_item,
                    private_note = f"Automated send after quiet period for invoice {inv.id}",
                )
                sent += 1

            except Exception as e:
                self.stderr.write(f"Failed auto-send for invoice {inv.id}: {e}")
            
        self.stdout.write(f"Auto-send complete. Sent = {sent}")
                    