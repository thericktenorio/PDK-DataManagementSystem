from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import cache_control
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db import IntegrityError
from django.contrib import messages
from django.conf import settings

from core.models import Client, TaxYear
from .models import (
    QboConnection,
    QboWebhookDelivery,
    QboEntityEvent,
    DeliveryStatus,
    EventStatus,
    Invoice,
)
from .qbo import oauth_authorize_url, exchange_code_for_tokens, verify_webhook_signature, QboApi
from .services.outbound import create_and_send_invoice
from .services.sender import send_invoice_now_for
from .policies import is_invoice_eligible_to_send
from .selectors import clearing_complete_pas_for_invoice
from .mappers import pa_to_qbo_sales_item

from datetime import datetime
from dateutil import parser as dtparser

import json
import secrets
import base64
import hmac


# To Billing Page
@login_required
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def billing(request):
    org_id = get_current_org_id(request)
    qbo_connected = bool(
        org_id
        and QboConnection.objects.filter(org_id=org_id, is_active=True).exists()
    )

    draft_invoices = (
        Invoice.objects.filter(
            status__in=[Invoice.INVOICE_STATUS_DRAFT, Invoice.INVOICE_STATUS_ISSUED],
        )
        .select_related("client")
        .prefetch_related("assignment_links__product_assignment")
        .order_by("last_activity_at")[:100]
    )

    draft_rows = []
    for inv in draft_invoices:
        pas = [link.product_assignment for link in inv.assignment_links.all()]
        draft_rows.append({
            "invoice": inv,
            "client_name": getattr(inv.client, "name", str(inv.client_id)),
            "line_count": len(pas),
            "eligible_to_send": is_invoice_eligible_to_send(inv) and len(pas) > 0,
        })

    open_invoices = (
        Invoice.objects.filter(
            status__in=[
                Invoice.INVOICE_STATUS_SENT,
                Invoice.INVOICE_STATUS_PARTIAL,
                Invoice.INVOICE_STATUS_ISSUED,
            ],
        )
        .exclude(qbo_balance_cents=0)
        .select_related("client")
        .order_by("-updated_at")[:50]
    )
    open_rows = [
        {
            "invoice": inv,
            "client_name": getattr(inv.client, "name", str(inv.client_id)),
            "balance_display": f"{inv.qbo_balance_cents / 100:.2f}",
        }
        for inv in open_invoices
    ]

    paid_invoices = (
        Invoice.objects.filter(status=Invoice.INVOICE_STATUS_PAID)
        .select_related("client")
        .order_by("-last_synced_at")[:25]
    )
    paid_rows = [
        {
            "invoice": inv,
            "client_name": getattr(inv.client, "name", str(inv.client_id)),
        }
        for inv in paid_invoices
    ]

    recent_errors = (
        QboEntityEvent.objects.filter(status=EventStatus.ERROR)
        .order_by("-last_updated")[:15]
    )

    return render(
        request,
        "billing/billing.html",
        {
            "qbo_connected": qbo_connected,
            "draft_rows": draft_rows,
            "open_rows": open_rows,
            "paid_rows": paid_rows,
            "recent_errors": recent_errors,
            "quiet_period_minutes": getattr(settings, "BILLING_QUIET_PERIOD_MINUTES", 5),
            "auto_send_enabled": getattr(settings, "FEATURE_AUTO_SEND_INVOICES", False),
        },
    )


@login_required
@require_POST
def send_draft_invoice(request, invoice_id):
    invoice = get_object_or_404(Invoice, pk=invoice_id)
    pa_qs = clearing_complete_pas_for_invoice(invoice)
    if not pa_qs.exists():
        messages.error(request, "No clearing-complete QBO lines on this draft.")
        return redirect("billing:billing")

    try:
        send_invoice_now_for(
            invoice.client,
            None,
            pa_queryset=pa_qs,
            line_builder=pa_to_qbo_sales_item,
            private_note=f"Manual send from billing page for invoice {invoice.id}",
        )
        messages.success(request, "Invoice sent to QBO.")
    except Exception as e:
        messages.error(request, f"Send failed: {e}")

    return redirect("billing:billing")


# resolve current org from logged-in user (expects InternalUser.organization to exist)
def get_current_org_id(request):
    return getattr(getattr(request.user, "organization", None), "id", None)


@login_required
def qbo_connect(request):
    org_id = get_current_org_id(request)
    if not org_id:
        return HttpResponseBadRequest("No organization associated with the current user.")
    state = f"{secrets.token_urlsafe(24)}:{org_id}"
    return redirect(oauth_authorize_url(state))


def qbo_callback(request):
    if (err:= request.GET.get("error")):
        return HttpResponseBadRequest(f"OAuth error: {err}")
    
    code = request.GET.get("code")
    realm_id = request.GET.get("realmId")
    state = request.GET.get("state", "")
    if not code or not realm_id:
        return HttpResponseBadRequest("Missing code or realmId.")
    
    try:
        _, org_id_str = state.split(":")
        org_id = int(org_id_str)
    except Exception:
        return HttpResponseBadRequest("Invalid state.")
    
    payload = exchange_code_for_tokens(code)
    expires_at = timezone.now() + timezone.timedelta(seconds=int(payload.get("expires_in", 3600)))

    QboConnection.objects.update_or_create(
        org_id = org_id,
        defaults = dict(
            realm_id = realm_id,
            access_token = payload["access_token"],
            refresh_token = payload["refresh_token"],
            access_token_expires_at = expires_at,
            is_active = True,
        ),
    )
    return HttpResponse("QBO connected.")   # Note: may redirect to a settings page instead


@csrf_exempt
@require_POST
def qbo_webhook(request):
    sig = request.headers.get("intuit-signature", "")
    raw = request.body or b""
    
    # 1) verify signature
    if not verify_webhook_signature(raw, sig):
        return HttpResponseForbidden("Invalid signature")

    # 2) compute body hash for delivery-level idempotency
    event_hash = QboWebhookDelivery.compute_hash(raw)

    # 3) parse JSON (store even if broken for forensics)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        delivery, _ = QboWebhookDelivery.objects.get_or_create(
            event_hash = event_hash,
            defaults = {
                "intuit_signature": sig,
                "realm_id": "",
                "raw_body": raw.decode("utf-8", errors = "replace"),
                "json_payload": {},
                "status": DeliveryStatus.ERROR,
                "error_message": "Invalid JSON payload",
            },
        )
        return HttpResponse("ok")   # Ack to avoid retries; nothing else to do
    
    # 4) extract realmId (present on each notification)
    notifs = payload.get("eventNotifications", []) or []
    realm_id = ""
    if notifs and isinstance(notifs, list):
        realm_id = notifs[0].get("realmId", "") or ""
    
    # 5) store the delivery once (idempotent on body hash)
    try:    
        delivery, created = QboWebhookDelivery.objects.get_or_create(
            event_hash = event_hash,
            defaults = {
                "intuit_signature": sig,
                "realm_id": realm_id,
                "raw_body": raw.decode("utf-8", errors = "replace"),
                "json_payload": payload,
                "status": DeliveryStatus.RECEIVED,
            },
        )
    except IntegrityError:
        delivery = QboWebhookDelivery.objects.get(event_hash = event_hash)
        created = False

    if not created:
        # duplicate body (QBO retry) -> acknowledge without fanning out again
        return JsonResponse({"ok": True, "duplicate": True, "created_entity_events": 0})
    
    # fast exit if no notifications
    has_entities = any(((n.get("dataChangeEvent") or {}).get("entities") or []) for n in notifs)
    if not has_entities:
        delivery.status = DeliveryStatus.PROCESSED
        delivery.save(update_fields = ["status"])
        return JsonResponse({"ok": True, "created_entity_events": 0, "empty": True})
    
    # 6) fan out per-entity events (entity-level idempotency)
    created_events = 0
    for notif in notifs:
        r_id = notif.get("realmId", "") or ""
        entities = (notif.get("dataChangeEvent") or {}).get("entities", []) or []
        for ent in entities:
            name = (ent.get("name") or "").strip().title()  # eg. "Invoice", "Payment", "Customer"
            if name == "Client":
                name = "Customer"
            entity_id = str(ent.get("id") or "").strip()
            operation = (ent.get("operation") or "").strip().title()    # eg. "Create", "Update", "Delete"
            last_updated_iso = (ent.get("lastUpdated") or "").strip()

            # parse lastUpdated (fall back to now if missing/malformed)
            try:
                last_updated_dt = dtparser.isoparse(last_updated_iso)
                # force UTC for consistent unique_together comparisons
                if timezone.is_naive(last_updated_dt):
                    # treat naive timestamps as UTC (QBO generally sends aware ISO 8601; this is a safe fallback)
                    last_updated_dt = last_updated_dt.replace(tzinfo = timezone.utc)
                else:
                    last_updated_dt = last_updated_dt.astimezone(timezone.utc)

            except Exception:
                # fallback stays, but note: if QBO omits lastUpdated (rare), idempotency relies on body de-dup.
                last_updated_dt = timezone.now()
            
            # stable event hash (prevents duplicates per entity/operation/timestamp)
            eh = QboEntityEvent.compute_event_hash(
                realm_id = r_id,
                entity_name = name,
                entity_id = entity_id,
                operation = operation,
                last_updated_iso = last_updated_iso or last_updated_dt.isoformat(),
            )

            try:
                _, ent_created = QboEntityEvent.objects.get_or_create(
                    event_hash = eh,
                    defaults = {
                        "delivery": delivery,
                        "realm_id": r_id,
                        "entity_name": name,
                        "entity_id": entity_id,
                        "operation": operation,
                        "last_updated": last_updated_dt,
                        "status": EventStatus.RECEIVED,
                    },
                )
            except IntegrityError:
                delivery = QboEntityEvent.objects.get(event_hash = event_hash)
                created = False

            if ent_created:
                created_events += 1

    # 7) mark the delivery as processed (storage + fan-out complete)
    delivery.status = DeliveryStatus.PROCESSED
    delivery.save(update_fields = ["status"])

    return JsonResponse({"ok": True, "created_entity_events": created_events})


@login_required
def qbo_smoke(request):
    org_id = get_current_org_id(request)
    if not org_id:
        return HttpResponseBadRequest("No organization associated with the current user.")
    try:
        conn = QboConnection.objects.get(org_id = org_id, is_active = True)
    except QboConnection.DoesNotExist:
        return HttpResponseBadRequest("No active QBO connection for this organization.")
    api = QboApi(conn)
    data = api.get(f"companyinfo/{conn.realm_id}")  # authenticated test call
    return JsonResponse(data)


@csrf_protect
@login_required
@require_POST
def create_send_invoice_view(request):
    try:
        client_id = int(request.POST["client_id"])
        amount_cents = int(request.POST["amount_cents"])
        if amount_cents < 0:
            return HttpResponseBadRequest("amount_cents must be non-negative")
        description = request.POST.get("description", "Professional Services")
        due_date = request.POST.get("due_date") # "YYY-MM-DD" or None
        private_note = request.POST.get("private_note")

        inv = create_and_send_invoice(client_id = client_id, amount_cents = amount_cents, description = description, due_date = due_date, private_note = private_note)

        return JsonResponse({"qbo_invoice_id": inv.qbo_invoice_id, "status": inv.status})
    
    except KeyError:
        return HttpResponseBadRequest("Missing required parameters: client_id, amount_cents.")
    except ValueError as e:
        return HttpResponseBadRequest(str(e))
    
    
@login_required
@csrf_protect
@require_POST
def send_invoice_now(request):
    '''
    Body (application/json):
    {
        "client_id": "<uuid/int>",
        "tax_year-id": "<id or null>",  # omit or null for multi-year batching
        "note": "optional private note"
    }
    '''
    try:
        data = getattr(request, "json", None) or getattr(request, "POST", {})
        client_id = data.get("client_id")
        tax_year_id = data.get("tax_year_id", None)
        note = data.get("note")

        if not client_id or not tax_year_id:
            return HttpResponseBadRequest("client_id and tax_year_id are required")
        
        client = get_object_or_404(Client, pd = client_id)
        tax_year = get_object_or_404(TaxYear, pk = tax_year_id) if tax_year_id not in (None, "", "null") else None

        from billing.selectors import clearing_complete_qbo_pas_for
        from billing.mappers import pa_to_qbo_sales_item

        pa_qs = clearing_complete_qbo_pas_for(client, tax_year)
        result = send_invoice_now_for(
            client,
            tax_year,
            pa_queryset = pa_qs,
            line_builder = pa_to_qbo_sales_item,
            private_note = note,
        )
        return JsonResponse(result, status = 200)
    
    except Exception as e:
        return JsonResponse({"error": str(e)}, status = 400)