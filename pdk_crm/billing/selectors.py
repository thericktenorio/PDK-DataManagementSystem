from django.conf import settings

from core.models import LifecycleState, ProductAssignment
from core.workflows.lifecycle import is_no_fee_payment_method, is_qbo_payment_method

from billing.models import AssignmentInvoiceLink, Invoice
from billing.services.invoice_lifecycle import invoice_is_sent


def get_or_create_qbo_item(api) -> dict:
    '''
    Ensure a Service Item exists for MVP invoices.
    Prefer settings.QBO_DEFAULT_ITEM_ID fast-path if provided.
    '''

    default_id = getattr(settings, "QBO_DEFAULT_ITEM_ID", "").strip()
    default_name = getattr(settings, "QBO_DEFAULT_ITEM_NAME", "Tax Preparation").strip()
    if default_id:
        return {"value": default_id, "name": default_name}

    sql = f"select * from Item where Name = '{default_name}' and type = 'Service'"
    res = api.query(sql)
    items = res.get("QueryResponse", {}).get("Item", [])
    if items:
        it = items[0]
        return {"value": it["Id"], "name": it["Name"]}

    created = api.create("item", {"Name": default_name, "Type": "Service", "IncomeAccountRef": {"value": "1"}, "Taxable": False})
    it = created.get("Item", created)
    return {"value": it["Id"], "name": it["Name"]}


def clearing_complete_qbo_pas_for(client, tax_year=None):
    """
    QBO PAs in CLEARING_COMPLETE linked to a draft (ready to include on send).
    """
    qs = (
        ProductAssignment.objects.filter(
            client=client,
            payment_method=ProductAssignment.PAYMENT_METHOD_QBO,
            lifecycle_state=LifecycleState.CLEARING_COMPLETE,
            invoice_link__isnull=False,
        )
        .select_related("product", "tax_year", "client", "filing_type", "invoice_link__invoice")
    )
    if tax_year is not None:
        qs = qs.filter(tax_year=tax_year)
    return qs


def clearing_complete_pas_for_invoice(invoice: Invoice):
    """PAs on this invoice still in CLEARING_COMPLETE (QBO, pre-send)."""
    return ProductAssignment.objects.filter(
        invoice_link__invoice=invoice,
        lifecycle_state=LifecycleState.CLEARING_COMPLETE,
        payment_method=ProductAssignment.PAYMENT_METHOD_QBO,
    ).select_related("product", "tax_year", "client", "filing_type")


def completed_unlinked_pas_for(client, tax_year=None):
    """Deprecated alias — use clearing_complete_qbo_pas_for."""
    return clearing_complete_qbo_pas_for(client, tax_year)


def completed_unlinked_pas_for_invoice(invoice):
    """Deprecated alias — use clearing_complete_pas_for_invoice."""
    return clearing_complete_pas_for_invoice(invoice)


def pa_billing_context(pa: ProductAssignment) -> dict:
    """Clearing UI: invoice badge, reopen tier, confirm-payment eligibility."""
    state = (pa.lifecycle_state or LifecycleState.IN_CLEARING).strip()

    ctx = {
        "can_confirm_payment": False,
        "can_reopen": False,
        "reopen_tier": "none",
        "invoice_status": "",
        "invoice_sent": False,
        "qbo_invoice_number": "",
        "invoice_badge": "",
        "invoice_id": "",
    }

    if state in {LifecycleState.CLEARING_COMPLETE, LifecycleState.AWAITING_PAYMENT}:
        ctx["can_reopen"] = True
        ctx["reopen_tier"] = "standard"

    if state == LifecycleState.AWAITING_PAYMENT:
        ctx["reopen_tier"] = "strict"

    if (
        state == LifecycleState.CLEARING_COMPLETE
        and not is_qbo_payment_method(pa)
        and not is_no_fee_payment_method(pa)
    ):
        ctx["can_confirm_payment"] = True

    link = (
        AssignmentInvoiceLink.objects.filter(product_assignment=pa)
        .select_related("invoice")
        .first()
    )

    if link and link.invoice_id:
        inv = link.invoice
        ctx["invoice_status"] = inv.status
        ctx["invoice_sent"] = invoice_is_sent(inv)
        ctx["qbo_invoice_number"] = inv.qbo_invoice_number or ""
        ctx["invoice_id"] = str(inv.id)

        if is_qbo_payment_method(pa) and state == LifecycleState.CLEARING_COMPLETE and not ctx["invoice_sent"]:
            ctx["invoice_badge"] = "Draft invoice"
        elif inv.status == Invoice.INVOICE_STATUS_PARTIAL:
            ctx["invoice_badge"] = "Partial payment"
        elif ctx["invoice_sent"]:
            ctx["invoice_badge"] = "Invoice sent"
        elif inv.status == Invoice.INVOICE_STATUS_PAID:
            ctx["invoice_badge"] = "Paid"

        if ctx["invoice_sent"]:
            ctx["reopen_tier"] = "strict"

    return ctx
