from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, StreamingHttpResponse, Http404, HttpResponseBadRequest
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST, require_http_methods
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Q
from django.conf import settings

from core.models import (
    TaxSeason,
    Client,
    Intake,
    DailyClearing,
    TaxYear,
    ProductAssignment,
    Product,
    FilingType,
    Appointment,
    LifecycleState,
)
from core.utils import (
    DUPLICATE_ACTIVE_PA_MESSAGE,
    INTAKE_PRODUCT_ASSIGNMENT_ORDERING,
    get_valid_tax_years,
    get_active_tax_season,
    get_or_create_intake,
    get_or_create_product_assignment,
    get_or_create_appointment,
    enforce_pa_not_frozen_for_action,
    pick_product_for_new_active_assignment,
)
from core.workflows.lifecycle import (
    cmd_enter_clearing,
    cmd_complete_clearing,
    cmd_reopen_clearing,
    cmd_confirm_payment_received,
    enter_clearing_for_client_assignments,
    is_pa_locked_for_editing,
    is_qbo_payment_method,
)

from acknowledgments.selectors import build_clearing_status_columns

from billing.selectors import pa_billing_context
from billing.services.post_clearing import on_clearing_completed

from accounts.models import InternalUser

from clearing.services.parse_upload import ParseUploadError, apply_parser_pdf
from clearing.services.parser_outputs import parser_downloads_payload
from clearing.services.pdf_manager_client import PDFManagerClient, PDFManagerError
from clearing.services.enrollment import activate_client_in_clearing
from clearing.services.global_parse import GlobalParseError, commit_global_upload, preview_global_upload

from core.forms import ClientForm
from intake.services.enrollment import enroll_client_in_intake, NoActiveTaxSeasonError

import json


def _pa_status_payload(pa: ProductAssignment) -> dict:
    state = pa.lifecycle_state or LifecycleState.IN_CLEARING
    billing = pa_billing_context(pa)
    payload = {
        "lifecycle_state": state,
        "lifecycle_label": dict(LifecycleState.choices).get(state, state),
        "is_locked": is_pa_locked_for_editing(pa),
        "is_qbo": is_qbo_payment_method(pa),
        "fee": str(pa.fee) if pa.fee is not None else "",
        **billing,
    }
    return payload


# To Clearing Page
@login_required
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def clearing(request):
    active_clearings = DailyClearing.objects.filter(is_active=True).select_related(
        "client", "tax_season"
    )

    current_tax_year = timezone.now().year - 1
    reference_tax_year = current_tax_year

    reference_products = Product.objects.filter(tax_year__year=reference_tax_year)

    seen_types = set()
    reference_valid_products = []

    for p in reference_products:
        if p.product_type not in seen_types:
            reference_valid_products.append({"id": p.id, "product_type": p.product_type})
            seen_types.add(p.product_type)

    clients = []
    for clearing_row in active_clearings:
        client = clearing_row.client

        product_assignments = (
            client.product_assignments.select_related(
                "product", "tax_year", "filing_type", "preparer", "appointment",
                "invoice_link__invoice",
            )
            .prefetch_related("acknowledgments")
            .filter(intake__tax_season=clearing_row.tax_season, is_active=True)
            .order_by(*INTAKE_PRODUCT_ASSIGNMENT_ORDERING)
        )

        for pa in product_assignments:
            if pa.filing_type is None:
                default_filing_type, _ = FilingType.objects.get_or_create(
                    filing_type=FilingType.FILING_TYPE_DEFAULT
                )
                pa.filing_type = default_filing_type
                pa.save(update_fields=["filing_type"])

            if pa.tax_year is None:
                current_year = timezone.now().year - 1
                tax_year, _ = TaxYear.objects.get_or_create(
                    client=client, year=current_year
                )
                pa.tax_year = tax_year
                pa.save(update_fields=["tax_year"])

            if pa.product is None:
                pa.product = Product.objects.create(
                    tax_year=pa.tax_year, product_type=Product.PRODUCT_TYPE_DEFAULT
                )
                pa.save(update_fields=["product"])

            if pa.fee is None and pa.product_id:
                pa.fee = pa.product.default_price
                pa.save(update_fields=["fee"])

            pa.valid_products = reference_valid_products
            pa.appointment = get_or_create_appointment(pa)
            pa.is_row_locked = is_pa_locked_for_editing(pa)
            pa.billing_context = pa_billing_context(pa)
            pa.clearing_status = build_clearing_status_columns(pa)

        client.product_assignments_list = product_assignments
        client.first_product_assignment = (
            product_assignments.first() if product_assignments.exists() else None
        )
        clients.append(client)

    for client in clients:
        for pa in client.product_assignments_list:
            pa.parser_downloads = parser_downloads_payload(pa)

    valid_tax_years = get_valid_tax_years()
    PRODUCT_TYPE_CHOICES = Product.PRODUCT_TYPE_CHOICES
    PAYMENT_METHOD_CHOICES = ProductAssignment.PAYMENT_METHOD_CHOICES
    APPOINTMENT_TYPE_CHOICES = Appointment.APPOINTMENT_TYPE_CHOICES
    PREPARER_OPTIONS = InternalUser.objects.filter(is_active=True).values(
        "id", "first_name", "last_name", "email"
    )

    return render(
        request,
        "clearing/clearing.html",
        {
            "clearing_clients": clients,
            "valid_tax_years": valid_tax_years,
            "filing_type_options": list(FilingType.objects.values("id", "filing_type")),
            "product_type_options": PRODUCT_TYPE_CHOICES,
            "reference_valid_products": reference_valid_products,
            "payment_method_options": PAYMENT_METHOD_CHOICES,
            "appointment_type_options": APPOINTMENT_TYPE_CHOICES,
            "preparer_options": PREPARER_OPTIONS,
            "feature_parser_path_a": getattr(settings, "FEATURE_PARSER_PATH_A", False),
        },
    )


@login_required
def search_clients(request):
    query = request.GET.get("q", "").strip()

    try:
        clients = Client.objects.filter(
            Q(name__icontains=query) | Q(TIN__icontains=query)
        ).values("id", "name", "TIN")

        intake_clients = set(
            Intake.objects.filter(is_active=True).values_list("client_id", flat=True)
        )
        daily_clearing_clients = set(
            DailyClearing.objects.filter(is_active=True).values_list(
                "client_id", flat=True
            )
        )

        results = []
        for client in clients:
            client_id = client["id"]
            results.append(
                {
                    "id": client["id"],
                    "name": client["name"],
                    "TIN": client["TIN"],
                    "in_intake": client["id"] in intake_clients,
                    "in_daily_clearing": client_id in daily_clearing_clients,
                }
            )
        return JsonResponse(results, safe=False)

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@require_POST
@login_required
def create_new_client(request):
    try:
        form = ClientForm(json.loads(request.body))
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON payload."}, status=400)

    if not form.is_valid():
        return JsonResponse({"status": "error", "errors": form.errors}, status=400)

    client = form.save()

    try:
        enroll_client_in_intake(client)
        activate_client_in_clearing(client, actor=request.user)
    except NoActiveTaxSeasonError as exc:
        return JsonResponse(
            {
                "status": "error",
                "message": (
                    f"{client.name} was created but could not be added to "
                    f"clearing and intake: {exc}"
                ),
                "client_id": client.id,
            },
            status=400,
        )

    return JsonResponse(
        {
            "status": "success",
            "message": f"{client.name} created and added to clearing and intake.",
            "client_id": client.id,
        }
    )


@require_POST
@login_required
def add_client_to_clearing(request, client_id):
    client = get_object_or_404(Client, id=client_id)
    current_tax_season = (
        TaxSeason.objects.filter(is_active=True).order_by("-year").first()
    )

    if not current_tax_season:
        return JsonResponse(
            {"status": "error", "message": "No active tax season"}, status=400
        )

    intake = get_or_create_intake(client)
    product_assignment = get_or_create_product_assignment(client, intake)

    clearing, _ = DailyClearing.objects.get_or_create(
        client=client,
        tax_season=current_tax_season,
        defaults={"is_active": True},
    )

    if not clearing.is_active:
        clearing.is_active = True
        clearing.save()

    enter_clearing_for_client_assignments(
        client_id=client.id,
        intake_id=intake.id,
        actor=request.user,
    )

    seen_types = set()
    filtered_products = []
    products_for_year = Product.objects.filter(tax_year=product_assignment.tax_year)

    for p in products_for_year:
        if p.product_type not in seen_types:
            filtered_products.append({"id": p.id, "product_type": p.product_type})
            seen_types.add(p.product_type)

    product_assignment.refresh_from_db()

    return JsonResponse(
        {
            "status": "success",
            "message": f"{client.name} added to clearing",
            "client": {
                "id": client.id,
                "TIN": client.TIN,
                "name": client.name,
            },
            "product_assignment": {
                "id": product_assignment.id,
                "tax_year": product_assignment.tax_year.year,
                "product_id": product_assignment.product.id,
                "product_type": product_assignment.product.product_type,
                "fee": str(product_assignment.fee)
                if product_assignment.fee is not None
                else "",
                "lifecycle_state": product_assignment.lifecycle_state
                or LifecycleState.IN_CLEARING,
                "filing_type": {
                    "id": product_assignment.filing_type.id,
                    "label": product_assignment.filing_type.filing_type,
                },
            },
            "filing_type_options": list(FilingType.objects.values("id", "filing_type")),
            "product_options": filtered_products,
            "valid_tax_years": get_valid_tax_years(),
        }
    )


@require_POST
@login_required
def remove_client_from_clearing(request, client_id):
    clearing = DailyClearing.objects.filter(client_id=client_id, is_active=True).first()
    if clearing:
        clearing.is_active = False
        clearing.save()

    return JsonResponse({"status": "success"})


@require_POST
@login_required
def add_product_assignment(request):
    try:
        data = json.loads(request.body)

        client_id = data.get("client_id")
        if not client_id:
            return JsonResponse(
                {"status": "error", "message": "Client ID missing."}, status=400
            )
        client = get_object_or_404(Client, id=client_id)

        current_tax_season = get_active_tax_season()
        if not current_tax_season:
            return JsonResponse(
                {"status": "error", "message": "No active tax season found."},
                status=400,
            )

        intake = Intake.objects.filter(
            client=client,
            tax_season=current_tax_season,
            is_active=True,
        ).first()
        if not intake:
            return JsonResponse(
                {"status": "error", "message": "Active intake not found."}, status=404
            )

        reference_tax_year = timezone.now().year - 1

        tax_year, _ = TaxYear.objects.get_or_create(
            client=client, year=reference_tax_year
        )
        filing_type, _ = FilingType.objects.get_or_create(
            filing_type=FilingType.FILING_TYPE_DEFAULT
        )

        product = pick_product_for_new_active_assignment(
            client=client,
            intake=intake,
            tax_year=tax_year,
        )
        if product is None:
            return JsonResponse(
                {
                    "status": "error",
                    "code": "DUPLICATE_PA",
                    "message": DUPLICATE_ACTIVE_PA_MESSAGE,
                },
                status=409,
            )

        product_assignment, _ = ProductAssignment.objects.create_product_assignment(
            client=client,
            intake=intake,
            tax_year=tax_year,
            product=product,
            filing_type=filing_type,
            is_active=True,
        )

        if DailyClearing.objects.filter(
            client=client, tax_season=intake.tax_season, is_active=True
        ).exists():
            cmd_enter_clearing(pa_id=product_assignment.id, actor=request.user)

        appointment = get_or_create_appointment(product_assignment)

        seen_types = set()
        reference_products = Product.objects.filter(tax_year__year=reference_tax_year)
        reference_valid_products = []

        for p in reference_products:
            if p.product_type not in seen_types:
                reference_valid_products.append(
                    {"id": p.id, "product_type": p.product_type}
                )
                seen_types.add(p.product_type)

        product_assignment.refresh_from_db()

        return JsonResponse(
            {
                "status": "success",
                "product_assignment": {
                    "id": product_assignment.id,
                    "tax_year": tax_year.year,
                    "product_id": product.id,
                    "product_type": product.product_type,
                    "fee": str(product_assignment.fee)
                    if product_assignment.fee is not None
                    else "",
                    "lifecycle_state": product_assignment.lifecycle_state
                    or LifecycleState.IN_CLEARING,
                    "filing_type": {
                        "id": filing_type.id,
                        "label": filing_type.filing_type,
                    },
                    "appointment_id": appointment.id,
                },
                "filing_type_options": list(
                    FilingType.objects.values("id", "filing_type")
                ),
                "product_options": reference_valid_products,
                "valid_tax_years": get_valid_tax_years(),
                "appointment_type_options": Appointment.APPOINTMENT_TYPE_CHOICES,
            }
        )

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@require_POST
@login_required
def remove_product_assignment(request):
    try:
        data = json.loads(request.body)
        pa_id = data.get("product_assignment_id")

        if not pa_id:
            return JsonResponse(
                {"status": "error", "message": "Missing product assignment ID"},
                status=400,
            )

        pa = get_object_or_404(ProductAssignment, id=pa_id)

        enforce_pa_not_frozen_for_action(pa, action="remove_product_assignment")

        product = pa.product

        product.is_product_active = False
        product.save()

        pa.is_active = False
        pa.save()

        from clearing.services.global_parse import _reconcile_orphan_daily_clearing

        _reconcile_orphan_daily_clearing(pa.client, pa.intake.tax_season if pa.intake_id else None)

        return JsonResponse({"status": "success"})

    except ValidationError as ve:
        return JsonResponse(
            {"status": "error", "code": "PA_FROZEN", "message": ve.message_dict},
            status=409,
        )

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@require_POST
@login_required
def complete_clearing(request, pa_id):
    get_object_or_404(ProductAssignment, id=pa_id)
    try:
        pa = cmd_complete_clearing(pa_id=pa_id, actor=request.user)
        on_clearing_completed(pa_id=pa.id, actor=request.user)
        pa.refresh_from_db()
        payload = _pa_status_payload(pa)
        payload["status"] = "success"
        payload["message"] = "Clearing completed."
        return JsonResponse(payload)
    except ValidationError as ve:
        return JsonResponse(
            {"status": "error", "code": "VALIDATION", "message": ve.message_dict},
            status=400,
        )


@require_POST
@login_required
def reopen_clearing(request, pa_id):
    get_object_or_404(ProductAssignment, id=pa_id)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON body."}, status=400
        )

    confirmed_fee = data.get("confirmed_fee")
    acknowledge_invoice_sent = bool(data.get("acknowledge_invoice_sent"))

    if confirmed_fee is None or str(confirmed_fee).strip() == "":
        return JsonResponse(
            {
                "status": "error",
                "code": "FEE_REQUIRED",
                "message": "Fee confirmation is required to unlock this row.",
            },
            status=400,
        )

    try:
        pa = cmd_reopen_clearing(
            pa_id=pa_id,
            actor=request.user,
            confirmed_fee=confirmed_fee,
            acknowledge_invoice_sent=acknowledge_invoice_sent,
        )
        payload = _pa_status_payload(pa)
        payload["status"] = "success"
        payload["message"] = "Clearing reopened for editing."
        return JsonResponse(payload)
    except ValidationError as ve:
        return JsonResponse(
            {"status": "error", "code": "VALIDATION", "message": ve.message_dict},
            status=400,
        )


@require_POST
@login_required
def confirm_payment_received(request, pa_id):
    get_object_or_404(ProductAssignment, id=pa_id)
    try:
        pa = cmd_confirm_payment_received(pa_id=pa_id, actor=request.user)
        payload = _pa_status_payload(pa)
        payload["status"] = "success"
        payload["message"] = "Payment confirmed; ready for review."
        return JsonResponse(payload)
    except ValidationError as ve:
        return JsonResponse(
            {"status": "error", "code": "VALIDATION", "message": ve.message_dict},
            status=400,
        )


@require_http_methods(["GET", "POST"])
@login_required
def client_message(request, pa_id):
    pa = get_object_or_404(ProductAssignment, id=pa_id)
    locked = is_pa_locked_for_editing(pa)

    if request.method == "GET":
        return JsonResponse(
            {
                "status": "success",
                "message_text": pa.closing_message_text or "",
                "is_locked": locked,
                "client_name": pa.client.name,
                "product_type": pa.product.product_type if pa.product_id else "",
            }
        )

    if locked:
        return JsonResponse(
            {
                "status": "error",
                "code": "PA_FROZEN",
                "message": "Client message cannot be edited while clearing is complete.",
            },
            status=409,
        )

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON body."}, status=400
        )

    pa.closing_message_text = str(data.get("message_text", ""))
    pa.full_clean()
    pa.save(update_fields=["closing_message_text"])

    return JsonResponse(
        {
            "status": "success",
            "message_text": pa.closing_message_text,
        }
    )


def _parser_path_a_disabled_response():
    return JsonResponse(
        {
            "status": "error",
            "code": "PARSER_DISABLED",
            "message": "Parser upload is disabled.",
        },
        status=403,
    )


@require_POST
@login_required
def parse_pdf_global_preview(request):
    if not getattr(settings, "FEATURE_PARSER_PATH_A", False):
        return _parser_path_a_disabled_response()

    if "file" not in request.FILES:
        return JsonResponse(
            {"status": "error", "message": "No PDF file provided."},
            status=400,
        )

    uploaded = request.FILES["file"]
    if not (uploaded.name or "").lower().endswith(".pdf"):
        return JsonResponse(
            {"status": "error", "message": "Only PDF files are allowed."},
            status=400,
        )

    try:
        payload = preview_global_upload(uploaded)
    except GlobalParseError as exc:
        return JsonResponse(
            {
                "status": "error",
                "code": "PARSE_FAILED",
                "message": str(exc),
            },
            status=400,
        )

    return JsonResponse(payload)


@require_POST
@login_required
def parse_pdf_global_commit(request):
    if not getattr(settings, "FEATURE_PARSER_PATH_A", False):
        return _parser_path_a_disabled_response()

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON payload."},
            status=400,
        )

    parse_job_uuid = data.get("parse_job_uuid")
    action = data.get("action")
    if not parse_job_uuid or not action:
        return JsonResponse(
            {"status": "error", "message": "parse_job_uuid and action are required."},
            status=400,
        )

    try:
        payload = commit_global_upload(
            parse_job_uuid=str(parse_job_uuid),
            action=str(action),
            actor=request.user,
            client_id=data.get("client_id"),
            pa_id=data.get("pa_id") or data.get("product_assignment_id"),
            filing_type_id=data.get("filing_type_id"),
            product_id=data.get("product_id"),
            tax_year=data.get("tax_year"),
        )
    except GlobalParseError as exc:
        message = str(exc)
        code = "REPLACE_BLOCKED" if "already completed clearing" in message else "COMMIT_FAILED"
        status = 409 if code == "REPLACE_BLOCKED" else 400
        return JsonResponse(
            {
                "status": "error",
                "code": code,
                "message": message,
            },
            status=status,
        )

    return JsonResponse(payload)


@require_POST
@login_required
def parse_pdf_upload(request, pa_id):
    if not getattr(settings, "FEATURE_PARSER_PATH_A", False):
        return _parser_path_a_disabled_response()

    pa = get_object_or_404(ProductAssignment, id=pa_id)

    if "file" not in request.FILES:
        return JsonResponse(
            {"status": "error", "message": "No PDF file provided."},
            status=400,
        )

    uploaded = request.FILES["file"]
    if not (uploaded.name or "").lower().endswith(".pdf"):
        return JsonResponse(
            {"status": "error", "message": "Only PDF files are allowed."},
            status=400,
        )

    try:
        result = apply_parser_pdf(pa, uploaded)
    except ParseUploadError as exc:
        return JsonResponse(
            {
                "status": "error",
                "code": "PARSE_FAILED",
                "message": str(exc),
            },
            status=400,
        )

    payload = {
        "status": "success",
        "message": "PDF parsed; clearing fields updated.",
        "downloads": parser_downloads_payload(pa),
        **result,
    }
    return JsonResponse(payload)


@login_required
def parser_outputs(request, pa_id):
    pa = get_object_or_404(ProductAssignment, id=pa_id)
    return JsonResponse(
        {
            "status": "success",
            "parse_job_uuid": str(pa.parse_job_uuid) if pa.parse_job_uuid else None,
            "downloads": parser_downloads_payload(pa),
        }
    )


@login_required
def parser_output_download(request, pa_id, kind):
    pa = get_object_or_404(ProductAssignment, id=pa_id)
    if not pa.parse_job_uuid:
        raise Http404("No parser job linked to this assignment.")

    allowed = {item["kind"] for item in parser_downloads_payload(pa)}
    if kind not in allowed:
        raise Http404("Unknown parser output type.")

    client = PDFManagerClient()
    try:
        upstream = client.download_output(pa.parse_job_uuid, bundle=(kind == "all_outputs"))
    except PDFManagerError as exc:
        return HttpResponseBadRequest(str(exc))

    content_type = upstream.headers.get("Content-Type", "application/pdf")
    if kind == "all_outputs" and "zip" not in content_type.lower():
        content_type = "application/zip"

    default_name = "parser_outputs.zip" if kind == "all_outputs" else "tax_document.pdf"
    filename = default_name
    disposition = upstream.headers.get("Content-Disposition", "")
    if "filename=" in disposition:
        filename = disposition.split("filename=", 1)[-1].strip('" ')

    response = StreamingHttpResponse(
        upstream.iter_content(chunk_size=8192),
        content_type=content_type,
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
