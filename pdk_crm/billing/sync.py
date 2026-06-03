from __future__ import annotations
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional

from django.db import IntegrityError, transaction
from django.utils import timezone

from billing.models import Invoice, ClientQboLink
from core.models import Client
from .qbo import QboApi


def _to_cents(amount) -> int:
    '''
    convert a QBO numeric to integer cents with bankers' rounding avoided
    '''
    try:
        return int((Decimal(str(amount)).quantize(Decimal("0.01"), rounding = ROUND_HALF_UP) * 100))
    except (InvalidOperation, TypeError):
        return 0


def _derive_invoice_status(total_cents: int, balance_cents: int) -> str:
    if total_cents > 0 and balance_cents <= 0:
        return Invoice.INVOICE_STATUS_PAID
    if 0 < balance_cents < total_cents:
        return Invoice.INVOICE_STATUS_PARTIAL
    # issued/sent differentiation can be handled by your outbound flow later
    return Invoice.INVOICE_STATUS_ISSUED


def _find_linked_client_by_qbo(realm_id: str, qbo_customer_id: str) -> Optional[Client]:
    '''
    resolve a local Client given a QBO Customer.Id, respecting realm scoping when present.
    '''
    # if ClientQboLink has realm_id (recommended), use it; otherwise fall back to global.
    if hasattr(ClientQboLink, "realm_id"):
        link = ClientQboLink.objects.filter(realm_id = realm_id, qbo_customer_id = qbo_customer_id).first()
    else:
        link = ClientQboLink.objects.filter(qbo_customer_id = qbo_customer_id).first()
    return link.client if link else None


def _ensure_client_link(conn, qbo_customer: dict) -> Client:
    '''
    ensure a local Client <-> QBO mapping exists.
    strategy (conservative, avoids auto-creating duplicate Clients):
    1) if link exists by (realm, qbo_id) -> return linked client.
    2) try soft match by email (PrimaryEmailAddr.Address) or DisplayName.
    3) if a single match is found, create the link and return it
    4) otherwise, raise (let operators resolve by creating/linking explicity)
    '''
    realm_id = conn.realm_id
    qbo_id = str(qbo_customer["Id"])
    client = _find_linked_client_by_qbo(realm_id, qbo_id)
    if client:
        return client
    
    email = ((qbo_customer.get("PrimaryEmailAddr") or {}).get("Address") or "").strip()
    display_name = (qbo_customer.get("DisplayName") or "").strip()

    # soft match (safe best-effort; comment either clause out if you want stricter behavior)
    candidates = Client.objects.none()
    if email and hasattr(Client, "email"):
        candidates = Client.objects.filter(email = email)
    
    if not candidates.exists() and display_name and hasattr(Client, "name"):
        candidates = Client.objects.filter(name = display_name)
    
    if candidates.count() == 1:
        client = candidates.first()
        # create the link
        defaults = {"qbo_customer_id": qbo_id}
        if hasattr(ClientQboLink, "realm_id"):
            link, _ = ClientQboLink.objects.get_or_create(client = client, realm_id = realm_id, defaults = defaults)
        else:
            link, _ = ClientQboLink.objects.get_or_create(client = client, defaults = defaults)
        return client
    
    # at this point we do NOT auto-create a Client (to avoid duplication)
    # let operators resolve this by linking an existing Client or creating one, then reprocess the event
    raise ValueError(f"Unable to resolve a unique Client for QBO Customer {qbo_id} (realm {realm_id}).")


def sync_customer(conn, qbo_customer: dict) -> Client:
    '''
    idempotently ensure a Client is linked to the given QBO customer.
    updates basic fields (name/email) if missing; does not overwrite existing user-entered data.
    '''
    client = _find_linked_client_by_qbo(conn.realm_id, str(qbo_customer["Id"]))
    if not client:
        client = _ensure_client_link(conn, qbo_customer)
    
    # best-effort backfill without clobbering existing data
    fields_to_update = []
    display_name = (qbo_customer.get("DisplayName") or "").strip()
    email = ((qbo_customer.get("PrimaryEmailAddr") or {}).get("Address") or "").strip()

    if hasattr(client, "name") and display_name and not getattr(client, "name"):
        client.name = display_name
        fields_to_update.append("name")
    
    if hasattr(client, "email") and email and not getattr(client, "email"):
        client.email = email
        fields_to_update.append("email")
    
    if fields_to_update:
        client.save(update_fields = fields_to_update)
    

    # ensure a link row exists (realm-aware if field exists)
    defaults = {"qbo_customer_id": str(qbo_customer["Id"])}
    if hasattr(ClientQboLink, "realm_id"):
        ClientQboLink.objects.get_or_create(client = client, realm_id = conn.realm_id, defaults = defaults)
    else:
        ClientQboLink.objects.get_or_create(client = client, defaults = defaults)
    
    return client


def sync_invoice(conn, qbo_invoice: dict) -> Invoice:
    '''
    Idempotently upsert a local Invoice from the QBO 'Invoice' resource.
    - Uses qbo_invoice_id as the stable external key.
    - Ensures a linked Client exists (fetches Customer if needed).
    - Populates qbo_* mirror fields and derives 'status'; sets last_synced_at.
    '''
    qbo_invoice_id = str(qbo_invoice["Id"])
    qbo_sync_token = str(qbo_invoice.get("SyncToken", "")).strip()
    meta = qbo_invoice.get("MetaData") or {}
    qbo_last_updated = meta.get("LastUpdatedTime")

    cust_ref = (qbo_invoice.get("CustomerRef") or {}).get("value")
    qbo_customer_id = str(cust_ref) if cust_ref is not None else None

    # resolve/make sure the local Client mapping exists
    client: Optional[Client] = None
    if qbo_customer_id:
        client = _find_linked_client_by_qbo(conn.realm_id, qbo_customer_id)
        if not client:
            # pull authoritative Customer and create/link locally
            api = QboApi(conn)
            cust_doc = api.get_customer(qbo_customer_id)
            client = sync_customer(conn, cust_doc.get("Customer", {}))
    
    # money and dates
    total_cents = _to_cents(qbo_invoice.get("TotalAmt", 0))
    balance_cents = _to_cents(qbo_invoice.get("Balance", 0))
    currency = (qbo_invoice.get("CurrencyRef") or {}).get("value") or "USD"
    txn_date = qbo_invoice.get("TxnDate") or None         # 'YYYY-MM-DD' ok for DateField
    due_date = qbo_invoice.get("DueDate") or None

    status = _derive_invoice_status(total_cents, balance_cents)
    doc_number = (qbo_invoice.get("DocNumber") or "").strip()

    with transaction.atomic():
        inv, created = Invoice.objects.select_for_update().get_or_create(
            qbo_invoice_id=qbo_invoice_id,
            defaults=dict(
                client=client if client else None,           # client is required by your model; ensure non-null mapping in practice
                status=status,
                qbo_customer_id=qbo_customer_id,
                qbo_sync_token=qbo_sync_token,
                qbo_last_updated=qbo_last_updated,
                qbo_invoice_number=doc_number,
                qbo_amount_cents=total_cents,
                qbo_balance_cents=balance_cents,
                qbo_currency=currency,
                qbo_txn_date=txn_date,
                qbo_due_date=due_date,
                last_synced_at=timezone.now(),
            ),
        )

        # Updates (idempotent; touch only when changed)
        changed = False
        if not created:
            if client and inv.client_id != client.id:
                inv.client = client; changed = True
            if inv.status != status:
                inv.status = status; changed = True
            if inv.qbo_customer_id != qbo_customer_id:
                inv.qbo_customer_id = qbo_customer_id; changed = True
            if inv.qbo_sync_token != qbo_sync_token:
                inv.qbo_sync_token = qbo_sync_token; changed = True
            if inv.qbo_last_updated != qbo_last_updated:
                inv.qbo_last_updated = qbo_last_updated; changed = True
            if inv.qbo_invoice_number != doc_number:
                inv.qbo_invoice_number = doc_number; changed = True
            if inv.qbo_amount_cents != total_cents:
                inv.qbo_amount_cents = total_cents; changed = True
            if inv.qbo_balance_cents != balance_cents:
                inv.qbo_balance_cents = balance_cents; changed = True
            if inv.qbo_currency != currency:
                inv.qbo_currency = currency; changed = True
            if inv.qbo_txn_date != txn_date:
                inv.qbo_txn_date = txn_date; changed = True
            if inv.qbo_due_date != due_date:
                inv.qbo_due_date = due_date; changed = True

            if changed:
                inv.last_synced_at = timezone.now()
                inv.save()

    from billing.services.invoice_lifecycle import advance_pas_when_invoice_paid
    advance_pas_when_invoice_paid(inv)

    return inv
