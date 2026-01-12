from django.db import transaction
from django.utils import timezone
from billing.models import Invoice, AssignmentInvoiceLink


def get_or_create_draft_invoice(client, tax_year) -> Invoice:
    '''
    Keep at most one open draft/issued invoice per (client, tax_year).
    If tax_year is None, this is a multi-year draft bucket for the client.
    '''
    qs = Invoice.objects.filter(client = client)
    if hasattr(Invoice, "tax_year"):
        qs = qs.filter(tax_year = tax_year)     # tax_year may be None for multi-year drafts
    
    inv = (
        qs.exclude(status__in = [
            Invoice.INVOICE_STATUS_SENT,
            Invoice.INVOICE_STATUS_PAID,
            Invoice.INVOICE_STATUS_VOIDED,
            Invoice.INVOICE_STATUS_DELETED,
        ])
        .order_by("-created_at")
        .first()
    )
    if inv:
        return inv
    
    fields = dict (
        client = client,
        status = Invoice.INVOICE_STATUS_DRAFT,
        qbo_amount_cents = 0,
        qbo_balance_cents = 0,
        qbo_currency = "USD",
        last_activity_at = timezone.now(),
    )
    if hasattr(Invoice, "tax_year"):
        fields["tax_year"] = tax_year   # None = multi-year bucket

    return Invoice.objects.create(**fields)


@transaction.atomic
def link_pas_to_draft(invoice: Invoice, pas, *, on_link = None) -> int:
    '''
    Link each ProductAssignment (PA) to the given draft invoice, if not already linked.
    Resets last_activity_at when any new links are created.
    
    'pas' is an iterable of PA objects.
    'on_link' (optional) is a callback(pa) invoked per newly linked PA.
    Returns the count of newly linked PAs.
    '''
    linked = 0
    now = timezone.now()
    for pa in pas:
        #guard: skip if already linked
        if getattr(pa, "invoice_link_id", None):
            continue
        AssignmentInvoiceLink.objects.create(product_assignment = pa, invoice = invoice)
        linked += 1

        if callable(on_link):
            on_link(pa)
    
    if linked:
        invoice.last_activity_at = now
        invoice.save(update_fields = ["last_activity_at", "updated_at"])
    return linked