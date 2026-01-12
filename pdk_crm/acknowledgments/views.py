from django.db import transaction
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST
from django.utils.timezone import now
from core.models import Acknowledgment, AckStaging, Client, TaxSeason, Product, ProductAssignment, TaxYear, FilingType, DailyClearing
from core.utils import get_or_create_intake, get_or_create_product_assignment_for_tax_year
from datetime import date, datetime
import pandas as pd
import json


# To Acknowledgments Page
@login_required
@cache_control(no_cache = True, must_revalidate = True, no_store = True)
def acknowledgments(request):
    """
    Render the acknowledgments page with 3 year buckets
    """
    current_year = now().year
    current_tax_year = current_year - 1
    prior_tax_year = current_year - 2
    prior_prior_tax_year = current_year - 3

    current_tax_year_acknowledgments = Acknowledgment.objects.filter(tax_season__year = current_tax_year).order_by("-date", "-created_at")
    prior_tax_year_acknowledgments = Acknowledgment.objects.filter(tax_season__year = prior_tax_year).order_by("-date", "-created_at")
    prior_prior_tax_year_acknowledgments = Acknowledgment.objects.filter(tax_season__year = prior_prior_tax_year).order_by("-date", "-created_at")

    context = {
        'current_tax_year': current_tax_year,
        'prior_tax_year': prior_tax_year,
        'prior_prior_tax_year': prior_prior_tax_year,
        'current_tax_year_acknowledgments': current_tax_year_acknowledgments,
        'prior_tax_year_acknowledgments': prior_tax_year_acknowledgments,
        'prior_prior_tax_year_acknowledgments': prior_prior_tax_year_acknowledgments,
    }
    print(context)
    return render(request, "acknowledgments/acknowledgments.html", context)


def _parse_ack_text(raw_text: str):
    """
    Parse a text blob containing Drake ACK lines.

    Expected shape (example):
        Drake 2024 - State MEF ACK files processed
        IDNumber    Type    Acc Date        Name        Reject Codes
        123456789   CA5440  A   12-09-2025  DOE, JOHN   
    
    Function:
     - infer tax_year from a 'Drake <YYYY>' header if present, or from date year,
     - parse: IDNumber => TIN, Type => ack_type, Acc => status, Date => ack_date, Name => client_name
    """
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    if not lines:
        return []   # "No text provided."
    
    import re

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
        # skip obvious header lines
        if ln.startswith("IDNumber") or "IDNumber" in ln:
            continue
        if ln.startswith("Drake "):
            continue

        parts = ln.split()
        if len(parts) < 5:
            # not enough columns to be a data row
            continue

        idnumber = parts[0]
        ack_type = parts[1]
        status = parts[2]
        date_str = parts[3]
        name = " ".join(parts[4:])  # everything after date is name, eg. "DOE, JOHN"

        # parse date: example '12-09-2025'
        try:
            ack_date = datetime.strptime(date_str, "%m-%d-%Y").date()
        except ValueError:
            # attempt alternative like '2025-12-09'
            try:
                ack_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                # skip row if date is unreadable
                continue
        
        year = inferred_year

        records.append(
            {
                "client_tin": idnumber,
                "type": ack_type,
                "status": status,
                "date": ack_date,
                "client_name": name,
                "year": year,
            }
        )

    if not records:
        return [], "No valid acknowledgment rows found after parsing."
    
    return records, None


# Helper Methods
def _get_active_tax_season():
    ts = TaxSeason.objects.filter(is_active = True).order_by("-year").first()
    return ts


def _map_form_to_family(form_type: str):
    if not form_type:
        return None
    ft = form_type.strip().upper()

    # Amendments
    if ft.endswith("X"):
        return "AMENDMENT"
    
    # Extensions
    if ft in {"4868", "7004", "7004-09", "8868-01"}:
        return "EXTENSION"
    
    # ======= > TODO < ======= #
    # This list of personal and corporate form types MUST be comprehensive
     
    # Personal
    personal = {
        "1040", "1040SR", "CA540", "CA5402EZ", "CA540NR", "CA",
        "AZ140", "AZ140NR", "AR1000F", "CO104", "GA500", "IL1040",
        "IN40PNR", "KS40", "LA540B", "NY203", "OH1040", "OK511NR",
        "OR40P", "RI1040NR", "UT40", "VA763", "WAWFTC",
    }
    if ft in personal:
        return "PERSONAL"

    # Corporate / entity / fiduciary / nonprofit / LLC
    corporate = {
        "1120", "1120S", "1065", "1041", "990", "990EZ",
        "CA100", "CA100S", "CA565", "CA568", "CA199", "CA541",
        "CALLC01", "CALLC02", "CALLC03", "AZ120S", "NCD400",
        "OHSD100", "TN173C",
    }
    if ft in corporate:
        return "CORPORATE"
    
    return None


# Filing type gating rule for extensions and amendments
def _bucket_from_filing_type(client: Client, tax_year_value: int):
    """
    Rule:
    - if filing type is TBD -> unmatched
    - if Corporation -> corporate taxes
    - else -> personal taxes

    Try PA filing_type first for that client_tax year, then fallback to client.filing_type string.
    """
    pa = (
        ProductAssignment.objects.filter(client = client, tax_year__year = tax_year_value, is_active = True)
        .select_related("filing_type")
        .order_by("-id")
        .first()
    )

    filing_type_value = None
    if pa and pa.filing_type:
        filing_type_value = pa.filing_type.filing_type
    
    if not filing_type_value:
        filing_type_value = (client.filing_type or "").strip()
    
    if not filing_type_value or filing_type_value == FilingType.FILING_TYPE_DEFAULT:
        return None    # stage as NEEDS_FILING_TYPE
    
    if filing_type_value == FilingType.FILING_TYPE_CORPORATION:
        return Product.PRODUCT_TYPE_CORPORATE_TAXES
    
    return Product.PRODUCT_TYPE_PERSONAL_TAXES


def _staging_payload(st: AckStaging, *, candidates = None):
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
    """
    Ingest acknowledgments from either:
    - an uploaded file under key 'file'
    - pasted text under key 'pasted_data'
    """
    raw_text = ""

    # 1) from file upload (csv/txt)
    upload = request.FILES.get("file")
    if upload:
        # for now, treat as text / CSV. Excel binary support could be added later.
        content = upload.read()
        try:
            raw_text = content.decode("utf-8")
        except UnicodeDecodeError:
            raw_text = content.decode("latin-1", errors = "ignore")
    
    # 2) Data from pasted text area
    pasted = request.POST.get("pasted_data", "").strip()
    if pasted:
        # if both file and pasted exist, append or just overwrite.
        # here we append so a user can combine.
        if raw_text:
            raw_text += "\n" + pasted
        else:
            raw_text = pasted
    
    if not raw_text:
        return JsonResponse(
            {"status": "error", "message": "No data received to parse."}, status = 400
        )

    records, parse_error = _parse_ack_text(raw_text)
    if parse_error:
        return JsonResponse(
            {"status": "error", "message": parse_error}, status = 400
        )
    
    active_season = _get_active_tax_season()
    if not active_season:
        return JsonResponse(
            {"status": "error", "message": "No active TaxSeason found. Activate a TaxSeason before posting acknowledgments."},
            status = 500,
        )
    
    
    created_count = 0
    updated_count = 0

    staged_unmatched = []
    staged_ambiguous = []
    staged_needs_filing_type = []
    staged_client_not_found = []

    for rec in records:
        tin = (rec.get("client_tin") or "").strip()
        tax_year_value = rec.get("year")
        form_type = (rec.get("type") or "").strip()
        ack_date = rec.get("date")
        ack_status = (rec.get("status") or "").strip()
        client_name = (rec.get("client_name") or "").strip()

        # --- Resolve Client --- #
        client = Client.objects.filter(TIN = tin).first()
        if not client:
            st = AckStaging.objects.create(
                year = tax_year_value,
                client_tin = tin,
                client_name = client_name,
                type = form_type,
                date = ack_date,
                status = ack_status,
                match_state = AckStaging.MATCH_CLIENT_NOT_FOUND,
                reason = "Client TIN not found.",
                suggested_tax_season_year = active_season.year,
            )
            staged_client_not_found.append(_staging_payload(st))
            continue

        # --- Determine product_type target --- #
        family = _map_form_to_family(form_type)
        if family in ("EXTENSION", "AMENDMENT"):
            product_type = _bucket_from_filing_type(client, tax_year_value)
            if not product_type:
                st = AckStaging.objects.create(
                    year = tax_year_value,
                    client_tin = tin,
                    client_name = client_name,
                    type = form_type,
                    date = ack_date,
                    status = ack_status,
                    match_state = AckStaging.MATCH_NEEDS_FILING_TYPE,
                    reason = "Can't map extension / amendment without a non-TBD filing type.",
                    suggested_tax_season_year = active_season.year,
                )
                staged_needs_filing_type.append(_staging_payload(st))
                continue
        elif family == "CORPORATE":
            product_type = Product.PRODUCT_TYPE_CORPORATE_TAXES
        elif family == "PERSONAL":
            product_type = Product.PRODUCT_TYPE_PERSONAL_TAXES
        else:
            st = AckStaging.objects.create(
                year = tax_year_value,
                client_tin = tin,
                client_name = client_name,
                type = form_type,
                date = ack_date,
                status = ack_status,
                match_state = AckStaging.MATCH_UNMATCHED,
                reason = "Unknown or unsupported form type; cannot map to a product type.",
                suggested_tax_season_year = active_season.year,
            )
            staged_unmatched.append(_staging_payload(st))
            continue

        # --- Resolve tax year object (do NOT create in Step 2)
        tax_year = TaxYear.objects.filter(client=client, year=tax_year_value).first()
        if not tax_year:
            st = AckStaging.objects.create(
                year=tax_year_value,
                client_tin=tin,
                client_name=client_name,
                type=form_type,
                date=ack_date,
                status=ack_status,
                match_state=AckStaging.MATCH_UNMATCHED,
                reason="TaxYear object not found for client/year.",
                suggested_tax_season_year=active_season.year,
                suggested_product_type=product_type,
            )
            staged_unmatched.append(_staging_payload(st))
            continue

        # --- Resolve product (do NOT create in Step 2)
        product = Product.objects.filter(tax_year=tax_year, product_type=product_type).first()
        if not product:
            st = AckStaging.objects.create(
                year=tax_year_value,
                client_tin=tin,
                client_name=client_name,
                type=form_type,
                date=ack_date,
                status=ack_status,
                match_state=AckStaging.MATCH_UNMATCHED,
                reason="Product not found for client TaxYear + mapped product_type.",
                suggested_tax_season_year=active_season.year,
                suggested_product_type=product_type,
            )
            staged_unmatched.append(_staging_payload(st))
            continue

        # --- Resolve PA candidates (active only)
        candidates = (
            ProductAssignment.objects.filter(client=client, tax_year=tax_year, product=product, is_active=True)
            .select_related("client", "tax_year", "product")
        )

        if candidates.count() == 1:
            pa = candidates.first()

            obj, created = Acknowledgment.objects.update_or_create(
                product_assignment=pa,
                type=form_type,
                date=ack_date,
                defaults={
                    "client_tin": tin,
                    "client_name": client_name,
                    "year": tax_year_value,
                    "status": ack_status,
                    "tax_season": active_season,
                    # keep product populated for now (until we remove it later)
                    "product": product,
                },
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        elif candidates.count() == 0:
            st = AckStaging.objects.create(
                year=tax_year_value,
                client_tin=tin,
                client_name=client_name,
                type=form_type,
                date=ack_date,
                status=ack_status,
                match_state=AckStaging.MATCH_UNMATCHED,
                reason="No matching active ProductAssignment found.",
                suggested_tax_season_year=active_season.year,
                suggested_product_type=product_type,
            )
            staged_unmatched.append(_staging_payload(st))

        else:
            st = AckStaging.objects.create(
                year=tax_year_value,
                client_tin=tin,
                client_name=client_name,
                type=form_type,
                date=ack_date,
                status=ack_status,
                match_state=AckStaging.MATCH_AMBIGUOUS,
                reason=f"Multiple matching active ProductAssignments found ({candidates.count()}).",
                suggested_tax_season_year=active_season.year,
                suggested_product_type=product_type,
            )
            staged_ambiguous.append({**_staging_payload(st), "candidates": [pa.id for pa in candidates],})

    return JsonResponse(
        {
            "status": "success",
            "message": f"{created_count} acknowledgments created, {updated_count} updated.",
            "created": created_count,
            "updated": updated_count,
            "unmatched": staged_unmatched,
            "ambiguous": staged_ambiguous,
            "needs_filing_type": staged_needs_filing_type,
            "client_not_found": staged_client_not_found,
        }
    )


@require_POST
@login_required
def resolve_ack_staging(request):
    """
    Resolve staging rows with action:
    - "create": auto-create Intake + PA + add to clearing + create Acknowledgment
    - "decline": mark staging row as DECLINE (is_matched False equivalent)
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"status": "error", "message": "Invalid JSON payload."}, status = 400)
    
    ids = payload.get("ids") or []
    action = (payload.get("action") or "").strip().lower()

    if not isinstance(ids, list) or not ids:
        return JsonResponse({"status": "error", "message": "No staging ids provided."}, status = 400)
    
    if action not in ("create", "decline"):
        return JsonResponse({"status": "error", "message": "Invalid action. Must be 'create' or 'decline'."}, status = 400)
    
    rows = AckStaging.objects.filter(id__in = ids).order_by("id")
    if not rows.exists():
        return JsonResponse({"status": "error", "message": "No staging rows found for provided ids."}, status = 404)
    
    active_season = TaxSeason.objects.filter(is_active = True).order_by("-year").first()
    if not active_season:
        return JsonResponse({"status": "error", "message": "No active TaxSeason found."}, status = 500)
    
    if action == "decline":
        rows.update(match_state = AckStaging.MATCH_DECLINED, reason = "User declined auto-create.")
        declined = rows.count()
        return JsonResponse({"status": "success", "message": f"Declined {declined} unmatched acknowledgments.", "declined": declined})
    

    created_pa = 0
    created_ack = 0
    decline = 0
    errors = []
    client_missing = []
    resolved_count = 0
    skipped = 0

    # action == "create"
    with transaction.atomic():
        for st in rows.select_for_update():
            # skip already resolved / declined
            if st.match_state in (AckStaging.MATCH_MATCHED, AckStaging.MATCH_DECLINED):
                skipped += 1
                continue

            # hard skip: cannot auto-create PA for missing client (UI handles via create_client_from_ack)
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

            client = Client.objects.filter(TIN = tin).first()
            if not client:
                st.match_state = AckStaging.MATCH_CLIENT_NOT_FOUND
                st.reason = "Client TIN not found in database."
                st.save(update_fields = ["match_state", "reason"])
                client_missing.append(_staging_payload(st))
                continue

            # ensure intake exists / active for current season
            intake = get_or_create_intake(client)

            # ensure at least one PA exists (defaults TBD)
            pa = get_or_create_product_assignment_for_tax_year(client, intake, st.year)

            # ensure clearing row exists / active for current season
            clearing, _ = DailyClearing.objects.get_or_create(
                client = client,
                tax_season = intake.tax_season,
                defaults = {"is_active": True},
            )
            if not clearing.is_active:
                clearing.is_active = True
                clearing.save(update_fields = ["is_active"])
            
            # PA should NOT be completed automatically
            if pa.is_complete:
                pa.is_complete = False
                pa.save(update_fields = ["is_complete"])

            # create / update acknowledgment tied to PA
            ack_obj, ack_created = Acknowledgment.objects.update_or_create(
                product_assignment = pa,
                type = form_type,
                date = ack_date,
                defaults = {
                    "client_tin": tin,
                    "client_name": client_name,
                    "year": tax_year_value,
                    "status": ack_status,
                    "tax_season": intake.tax_season,
                    # keep product populated until we remove it later
                    "product": pa.product,
                },
            )
            if ack_created:
                created_ack += 1
            
            # mark staging matched
            st.resolved_product_assignment = pa
            st.match_state = AckStaging.MATCH_MATCHED
            st.reason = "Auto-created / attached to ProductAssignment."
            st.save(update_fields = ["resolved_product_assignment", "match_state", "reason"])

            created_pa += 1 # counts resovles; optional
            resolved_count += 1
        
        
    return JsonResponse(
        {
            "status": "success",
            "message": f"Resolved {resolved_count} staging rows. Created / updated {created_ack} acknowledgments.",
            "resolved": resolved_count,
            "created_ack": created_ack,
            "skipped": skipped,
            "errors": errors,
            "client_missing": client_missing,
        }
    )


# Limit acknowledgments to 3 years
def annual_acknowledgments_range(request):
    current_year = now().year
    offsets = [1, 2, 3]
    return render(request, 'acknowledgments.html', {'current_year': current_year, 'offsets': offsets})


# Import acknowledgments from excel or csv
def import_acknowledgments(request):
    if request.method == 'POST':
        file = request.FILES.get('acknowledgments_file')
        if not file:
            return JsonResponse({'status': 'error', 'message': 'No file provided.'}, status=400)

        try:
            if file.name.endswith('.xlsx') or file.name.endswith('.xls'):
                data = pd.read_excel(file)
            elif file.name.endswith('.csv'):
                data = pd.read_csv(file)
            else:
                return JsonResponse({'status': 'error', 'message': 'Invalid file format. Use .xls, .xlsx, or .csv.'}, status=400)

            # Validate the required columns
            required_columns = {"TIN", "Year", "Description"}
            if not required_columns.issubset(data.columns):
                missing_columns = required_columns - set(data.columns)
                return JsonResponse({'status': 'error', 'message': f'Missing columns: {", ".join(missing_columns)}'}, status=400)

            acknowledgments_to_create = []

            for _, row in data.iterrows():
                try:
                    year = int(row['Year'])
                    description = row.get('Description', '')

                    acknowledgments_to_create.append(Acknowledgment(
                        year=year,
                        client_tin = str(row["TIN"]),
                        description=description,
                    ))
                except Exception as e:
                    return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

            # Bulk create acknowledgments
            if acknowledgments_to_create:
                Acknowledgment.objects.bulk_create(acknowledgments_to_create)

            return JsonResponse({'status': 'success', 'message': 'Acknowledgments imported successfully.'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status=405)

