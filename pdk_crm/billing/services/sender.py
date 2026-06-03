from django.db import transaction
from django.utils import timezone
from billing.models import Invoice, AssignmentInvoiceLink
from billing.services.drafts import get_or_create_draft_invoice, link_pas_to_draft
from billing.services.invoice_lifecycle import advance_pas_when_invoice_sent
from billing.providers import get_provider


@transaction.atomic
def send_invoice_now_for(client, tax_year, *, pa_queryset, line_builder, private_note = None):
    '''
    Manually send an invoice for the client (multi-year by passing tax_year = None).
    Steps:
    - get/create draft (by client + tax_year or multi-year)
    - build lines from provided PAs (must be completed & unlinked)
    - create & send in QBO
    - update local invoice and freeze (status = Sent)
    - create AssignmentInvoiceLink rows
    
    Send invoice immediately (manual trigger).
    - 'pa_queryset': a queryset or iterable of completed/unlinked PAs for this client/year.
    - 'line_builder': callable(pa) -> QBO SalesItem line dict.
    '''
    invoice = get_or_create_draft_invoice(client, tax_year)

    #collect PAs we're about to include (must be unlinked and completed)
    pas = list(pa_queryset)
    if not pas:
        #nothing to send; return current status
        return {"invoice_id": str(invoice.id), "status": invoice.status, "qbo_invoice_id": invoice.qbo_invoice_id, "lines": 0}
    
    # provider
    provider = get_provider()

    # ensure client exists/up-to-date in QBO
    display = getattr(client, "display_name", None) or getattr(client, "name", str(client.id))
    email= getattr(client, "email", None) or getattr(client, "primary_email", None)
    qbo_customer_id = provider.upsert_customer(display, email)

    # build QBO line items
    line_items = [line_builder(pa) for pa in pas]

    # ========== Create Invoice & Send Upstream ========== #
    qbo_id, qbo_doc, totals = provider.create_invoice(
        customer_id = qbo_customer_id,
        line_items = line_items,
        txn_date = timezone.now().date(),
        due_date = None,
        private_note = private_note or f"Automated invoice for {display}",
    )
    provider.send_invoice(qbo_id)

    # ========== Update local invoice and FREEZE ========== #
    invoice.qbo_invoice_id = str(qbo_id)
    if totals:
        invoice.qbo_amount_cents = int(round(float(totals.get("total", 0)) * 100))
        invoice.qbo_balance_cents = int(round(float(totals.get("balance", 0)) * 100))
    invoice.status = Invoice.INVOICE_STATUS_SENT
    invoice.last_synced_at = timezone.now()
    invoice.qbo_txn_date = timezone.now().date()
    invoice.save()

    # Idempotency links after client has been billed
    link_pas_to_draft(invoice, pas)

    advance_pas_when_invoice_sent(invoice, pas)

    return {"invoice_id": str(invoice.id), "status": invoice.status, "qbo_invoice_id": invoice.qbo_invoice_id, "lines": len(pas)}