from datetime import datetime
import json
import re

import pandas as pd
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.timezone import now
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST

from acknowledgments.selectors import (
    acknowledgments_for_display,
    pending_unmatched_staging,
)
from acknowledgments.services.reconcile import (
    ack_auto_create_enabled,
    ingest_ack_records,
    set_expected_ack_count,
)
from core.models import (
    AckStaging,
    Acknowledgment,
    Client,
    DailyClearing,
    ProductAssignment,
    TaxSeason,
)
from core.utils import get_or_create_intake, get_or_create_product_assignment_for_tax_year


@login_required
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def acknowledgments(request):
    current_year = now().year
    current_tax_year = current_year - 1
    prior_tax_year = current_year - 2
    prior_prior_tax_year = current_year - 3

    context = {
        "current_tax_year": current_tax_year,
        "prior_tax_year": prior_tax_year,
        "prior_prior_tax_year": prior_prior_tax_year,
        "current_tax_year_acknowledgments": acknowledgments_for_display(
            tax_season_year=current_tax_year
        ),
        "prior_tax_year_acknowledgments": acknowledgments_for_display(
            tax_season_year=prior_tax_year
        ),
        "prior_prior_tax_year_acknowledgments": acknowledgments_for_display(
            tax_season_year=prior_prior_tax_year
        ),
        "unmatched_staging": pending_unmatched_staging(),
        "ack_auto_create_enabled": ack_auto_create_enabled(),
    }
    return render(request, "acknowledgments/acknowledgments.html", context)


def _parse_ack_text(raw_text: str):
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    if not lines:
        return [], "No text provided."

    inferred_year = None
    for ln in lines:
        m = re.search(r"Drake\s+(\d{4})", ln)
        if m:
            inferred_year = int(m.group(1))
            break

    if inferred_year is None:
        return [], "Missing required header."

    records = []
    for ln in lines:
        if ln.startswith("IDNumber") or "IDNumber" in ln:
            continue
        if ln.startswith("Drake "):
            continue

        parts = ln.split()
        if len(parts) < 5:
            continue

        idnumber = parts[0]
        ack_type = parts[1]
        status = parts[2]
        date_str = parts[3]
        name = " ".join(parts[4:])

        try:
            ack_date = datetime.strptime(date_str, "%m-%d-%Y").date()
        except ValueError:
            try:
                ack_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue

        records.append(
            {
                "client_tin": idnumber,
                "type": ack_type,
                "status": status,
                "date": ack_date,
                "client_name": name,
                "year": inferred_year,
            }
        )

    if not records:
        return [], "No valid acknowledgment rows found after parsing."

    return records, None


def _get_active_tax_season():
    return TaxSeason.objects.filter(is_active=True).order_by("-year").first()


def _staging_payload(st: AckStaging, *, candidates=None):
    payload = {
        "id": st.id,
        "match_state": st.match_state,
        "year": st.year,
        "tin": st.client_tin,
        "name": st.client_name,
        "type": st.type,
        "date": st.date.isoformat() if st.date else None,
        "status": st.status,
        "reason": st.reason,
        "suggested_product_type": st.suggested_product_type,
        "suggested_tax_season_year": st.suggested_tax_season_year,
    }
    if candidates is not None:
        payload["candidates"] = candidates
    return payload


@require_POST
@login_required
def post_acknowledgments(request):
    raw_text = ""

    upload = request.FILES.get("file")
    if upload:
        content = upload.read()
        try:
            raw_text = content.decode("utf-8")
        except UnicodeDecodeError:
            raw_text = content.decode("latin-1", errors="ignore")

    pasted = request.POST.get("pasted_data", "").strip()
    if pasted:
        raw_text = f"{raw_text}\n{pasted}" if raw_text else pasted

    if not raw_text:
        return JsonResponse(
            {"status": "error", "message": "No data received to parse."},
            status=400,
        )

    records, parse_error = _parse_ack_text(raw_text)
    if parse_error:
        return JsonResponse({"status": "error", "message": parse_error}, status=400)

    active_season = _get_active_tax_season()
    if not active_season:
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "No active TaxSeason found. Activate a TaxSeason before posting acknowledgments."
                ),
            },
            status=500,
        )

    result = ingest_ack_records(records, active_season=active_season, actor=request.user)
    created_count = result["created"]
    updated_count = result["updated"]

    return JsonResponse(
        {
            "status": "success",
            "message": f"{created_count} acknowledgments created, {updated_count} updated.",
            "created": created_count,
            "updated": updated_count,
            "unmatched": result["unmatched"],
            "ambiguous": result["ambiguous"],
            "needs_filing_type": result["needs_filing_type"],
            "client_not_found": result["client_not_found"],
        }
    )


@require_POST
@login_required
def resolve_ack_staging(request):
    if not ack_auto_create_enabled():
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    "Auto-create from unmatched acks is disabled. "
                    "Update tax services in Clearing and re-import."
                ),
            },
            status=403,
        )

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"status": "error", "message": "Invalid JSON payload."}, status=400)

    ids = payload.get("ids") or []
    action = (payload.get("action") or "").strip().lower()

    if not isinstance(ids, list) or not ids:
        return JsonResponse({"status": "error", "message": "No staging ids provided."}, status=400)

    if action not in ("create", "decline"):
        return JsonResponse(
            {"status": "error", "message": "Invalid action. Must be 'create' or 'decline'."},
            status=400,
        )

    rows = AckStaging.objects.filter(id__in=ids).order_by("id")
    if not rows.exists():
        return JsonResponse(
            {"status": "error", "message": "No staging rows found for provided ids."},
            status=404,
        )

    active_season = TaxSeason.objects.filter(is_active=True).order_by("-year").first()
    if not active_season:
        return JsonResponse({"status": "error", "message": "No active TaxSeason found."}, status=500)

    if action == "decline":
        rows.update(match_state=AckStaging.MATCH_DECLINED, reason="User declined auto-create.")
        return JsonResponse(
            {
                "status": "success",
                "message": f"Declined {rows.count()} unmatched acknowledgments.",
                "declined": rows.count(),
            }
        )

    created_ack = 0
    client_missing = []
    resolved_count = 0
    skipped = 0

    with transaction.atomic():
        for st in rows.select_for_update():
            if st.match_state in (AckStaging.MATCH_MATCHED, AckStaging.MATCH_DECLINED):
                skipped += 1
                continue

            if st.match_state == AckStaging.MATCH_CLIENT_NOT_FOUND:
                client_missing.append(_staging_payload(st))
                skipped += 1
                continue

            tin = (st.client_tin or "").strip()
            tax_year_value = st.year
            form_type = (st.type or "").strip()
            ack_date = st.date
            ack_status = (st.status or "").strip()
            client_name = (st.client_name or "").strip()

            client = Client.objects.filter(TIN=tin).first()
            if not client:
                st.match_state = AckStaging.MATCH_CLIENT_NOT_FOUND
                st.reason = "Client TIN not found in database."
                st.save(update_fields=["match_state", "reason"])
                client_missing.append(_staging_payload(st))
                continue

            intake = get_or_create_intake(client)
            pa = get_or_create_product_assignment_for_tax_year(client, intake, st.year)

            clearing, _ = DailyClearing.objects.get_or_create(
                client=client,
                tax_season=intake.tax_season,
                defaults={"is_active": True},
            )
            if not clearing.is_active:
                clearing.is_active = True
                clearing.save(update_fields=["is_active"])

            if pa.is_complete:
                pa.is_complete = False
                pa.save(update_fields=["is_complete"])

            _ack_obj, ack_created = Acknowledgment.objects.update_or_create(
                product_assignment=pa,
                type=form_type,
                date=ack_date,
                defaults={
                    "client_tin": tin,
                    "client_name": client_name,
                    "year": tax_year_value,
                    "status": ack_status,
                    "tax_season": intake.tax_season,
                    "product": pa.product,
                },
            )
            if ack_created:
                created_ack += 1

            st.resolved_product_assignment = pa
            st.match_state = AckStaging.MATCH_MATCHED
            st.reason = "Auto-created / attached to ProductAssignment."
            st.save(update_fields=["resolved_product_assignment", "match_state", "reason"])
            resolved_count += 1

    return JsonResponse(
        {
            "status": "success",
            "message": (
                f"Resolved {resolved_count} staging rows. "
                f"Created / updated {created_ack} acknowledgments."
            ),
            "resolved": resolved_count,
            "created_ack": created_ack,
            "skipped": skipped,
            "client_missing": client_missing,
        }
    )


@require_POST
@login_required
def set_pa_expected_ack_count(request, pa_id):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON payload."}, status=400)

    try:
        pa = set_expected_ack_count(
            pa_id=pa_id,
            expected_ack_count=payload.get("expected_ack_count"),
        )
    except ValidationError as ve:
        return JsonResponse(
            {"status": "error", "message": ve.message_dict},
            status=400,
        )
    except ProductAssignment.DoesNotExist:
        return JsonResponse({"status": "error", "message": "ProductAssignment not found."}, status=404)

    return JsonResponse(
        {
            "status": "success",
            "message": "Expected ack count updated.",
            "pa_id": pa.id,
            "expected_ack_count": pa.expected_ack_count,
        }
    )


def import_acknowledgments(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid request method."}, status=405)

    file = request.FILES.get("acknowledgments_file")
    if not file:
        return JsonResponse({"status": "error", "message": "No file provided."}, status=400)

    try:
        if file.name.endswith((".xlsx", ".xls")):
            data = pd.read_excel(file)
        elif file.name.endswith(".csv"):
            data = pd.read_csv(file)
        else:
            return JsonResponse(
                {"status": "error", "message": "Invalid file format. Use .xls, .xlsx, or .csv."},
                status=400,
            )

        required_columns = {"TIN", "Year", "Description"}
        if not required_columns.issubset(data.columns):
            missing_columns = required_columns - set(data.columns)
            return JsonResponse(
                {"status": "error", "message": f"Missing columns: {', '.join(missing_columns)}"},
                status=400,
            )

        acknowledgments_to_create = []
        for _, row in data.iterrows():
            year = int(row["Year"])
            description = row.get("Description", "")
            acknowledgments_to_create.append(
                Acknowledgment(
                    year=year,
                    client_tin=str(row["TIN"]),
                    description=description,
                )
            )

        if acknowledgments_to_create:
            Acknowledgment.objects.bulk_create(acknowledgments_to_create)

        return JsonResponse({"status": "success", "message": "Acknowledgments imported successfully."})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
