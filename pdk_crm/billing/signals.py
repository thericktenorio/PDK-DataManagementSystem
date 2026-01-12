from django.db.models.signals import post_save
from django.dispatch import receiver

from core.models import ProductAssignment
from .services.drafts import get_or_create_draft_invoice, link_pas_to_draft


@receiver(post_save, sender = ProductAssignment)
def on_product_assignment_completion(sender, instance: ProductAssignment, created: bool, **kwargs):
    """
    Completion hook:
    - Whenever a ProductAssignment is saved with is_complete = True, and is_active not archived,
        attach it to a draft invoice and reset the quiet-period clock.
    
    This does NOT send the invoice. It ony prepares/updates the draft.
    Sending still happens via:
        - manual "Send Invoice" endpoint, or
        - auto_send_invoices management command after quiet period.
    """
    # Only care about completed, active, non-archived assignments
    if not instance.is_complete:
        return
    if not instance.is_active or instance.is_archived:
        return
    
    # multi-year draft bucket: tax_year = None
    # if you later want one invoice per tax_year, change to instance.tax_year.
    invoice = get_or_create_draft_invoice(instance.client, tax_year = None)

    # this is idempotent: if there's already a link, it will skip.
    link_pas_to_draft(invoice, [instance])