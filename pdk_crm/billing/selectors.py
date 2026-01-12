from django.conf import settings

from core.models import ProductAssignment

def get_or_create_qbo_item(api) -> dict:
    '''
    Ensure a Service Item exists for MVP invoices.
    Prefer settings.QBO_DEFAULT_ITEM_ID fast-path if provided.
    '''

    default_id = getattr(settings, "QBO_DEFAULT_ITEM_ID", "").strip()
    default_name = getattr(settings, "QBO_DEFAULT_ITEM_NAME", "Tax Preparation").strip()
    if default_id:
        return {"value": default_id, "name": default_name}
    
    # try to find by name
    sql = f"select * from Item where Name = '{default_name}' and type = 'Service'"
    res = api.query(sql)
    items = res.get("QueryResponse", {}).get("Item", [])
    if items:
        it = items[0]
        return {"value": it["Id"], "name": it["Name"]}
    
    #create service item (ensure valid IncomeAccountRef for your sandbox)
    #if your QboApi exposes an account lookup, prefer a real account ID.
    #adjust incomeaccountref if needed for your sandbox chart
    created = api.create("item", {"Name": default_name, "Type": "Service", "IncomeAccountRef": {"value": "1"}, "Taxable": False})
    it = created.get("Item", created)
    return {"value": it["Id"], "name": it["Name"]}


def completed_unlinked_pas_for(client, tax_year = None):
    '''
    Return completed ProductAssignments for a client that are not yet linked to any invoice.
    If tax_year is provided (FK object), limit to that year; else allow multi-year.
    '''
    
    qs = (ProductAssignment.objects.filter(client = client, is_complete = True, invoice_link__isnull = True).select_related("product", "tax_year", "client", "filing_type"))
    
    if tax_year is not None:
        qs = qs.filter(tax_year = tax_year)
    return qs

def completed_unlinked_pas_for_invoice(invoice):
    '''
    For a given invoice:
    - if invoice.tax_year exists (not None): constrain to that year.
    - Else: return all completed/unlinked PAs for the client (multi-year draft_.)
    '''
    tax_year = getattr(invoice, "tax_year", None) if hasattr(invoice, "tax_year") else None

    return completed_unlinked_pas_for(invoice.client, tax_year)