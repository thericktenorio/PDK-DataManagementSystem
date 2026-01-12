from typing import Optional
from datetime import date
from django.db import transaction
from django.utils import timezone

from ..providers import get_provider
from ..models import Invoice, ClientQboLink
from core.models import Client


@transaction.atomic
def upsert_customer_for_client(client_id: int) -> str:
    try:
        client = Client.objects.select_for_update().get(id = client_id)
    except Client.DoesNotExist:
        raise ValueError(f"Client id {client_id} not found")
    
    provider = get_provider()

    # build display_name and email from your Client fields
    display_name = getattr(client, "display_name", None) or getattr(client, "name", None) or str(client)
    email = getattr(client, "email", None) or getattr(client, "primary_email", None)

    result = provider.upsert_customer(display_name = display_name, email = email)
    qbo_id = result["qbo_customer_id"]

    ClientQboLink.objects.update_or_create(client = client, defaults = {"qbo_customer_id": qbo_id},)

    return qbo_id

@transaction.atomic
def create_and_send_invoice(*, client_id: int, amount_cents: int, description: str, txn_date: Optional[str] = None, due_date: Optional[str] = None, private_note: Optional[str] = None) -> Invoice:
    if amount_cents < 0:
        raise ValueError("amount_cents must be non-negative")
    
    provider = get_provider()
    qbo_customer_id = upsert_customer_for_client(client_id)

    line_items = [{"description": description, "amount_cents": amount_cents, "qty": 1}]
    payload = provider.create_invoice(
        customer_id = qbo_customer_id,
        line_items= line_items,
        txn_date = txn_date or date.today().isoformat(),
        due_date = due_date,
        private_note = private_note,
    )

    inv = Invoice.objects.create(
        client_id = client_id,
        qbo_invoice_id = payload["qbo_invoice_id"],
        qbo_sync_token = payload["qbo_sync_token"],
        qbo_amount_cents = amount_cents,
        qbo_balance_cents = amount_cents,   # corrected by webhook/status later
        qbo_currency = "USD",
        qbo_txn_date = (txn_date or date.today().isoformat()),
        qbo_due_date = due_date,
        status = "Draft",
        last_synced_at = timezone.now(),
    )

    send_res = provider.send_invoice(invoice_id = inv.qbo_invoice_id)
    inv.status = "Sent" if send_res.get("sent") else "Draft"
    inv.save(update_fields = ["status"])

    return inv