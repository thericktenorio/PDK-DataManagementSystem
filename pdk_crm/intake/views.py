from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from django.db import transaction

from core.models import (
    Client,
    Intake,
    DailyClearing,
    TaxYear,
    Product,
    ProductAssignment,
    FilingType,
)
from core.forms import ClientForm
from core.utils import (
    DUPLICATE_ACTIVE_PA_MESSAGE,
    INTAKE_PRODUCT_ASSIGNMENT_ORDERING,
    active_product_assignment_conflict,
    enforce_pa_not_frozen_for_action,
    get_active_tax_season,
    get_valid_tax_years,
)
from intake.services.enrollment import enroll_client_in_intake, NoActiveTaxSeasonError
from core.workflows.lifecycle import cmd_cancel_assignment

import json


def _ensure_pa_defaults(product_assignments, *, default_filing_type, current_tax_year_value):
    def _ensure_products_seeded_for_tax_year(tax_year_obj):
        for pt, _label in Product.PRODUCT_TYPE_CHOICES:
            Product.objects.get_or_create(
                tax_year=tax_year_obj,
                product_type=pt,
                defaults={"is_product_active": False},
            )

    def _build_valid_products_for_tax_year(tax_year_obj):
        seen = set()
        valid = []
        qs = Product.objects.filter(tax_year=tax_year_obj).order_by("product_type", "id")
        for p in qs:
            if p.product_type in seen:
                continue
            valid.append({"id": p.id, "product_type": p.product_type})
            seen.add(p.product_type)
        return valid

    for pa in product_assignments:
        with transaction.atomic():
            updated_fields = []

            if pa.filing_type_id is None:
                pa.filing_type = default_filing_type
                updated_fields.append("filing_type")

            if pa.tax_year_id is None:
                tax_year_obj, _ = TaxYear.objects.get_or_create(
                    client=pa.client,
                    year=current_tax_year_value,
                )
                pa.tax_year = tax_year_obj
                updated_fields.append("tax_year")
            else:
                tax_year_obj = pa.tax_year

            _ensure_products_seeded_for_tax_year(tax_year_obj)

            if pa.product_id is None:
                default_product, _ = Product.objects.get_or_create(
                    tax_year=tax_year_obj,
                    product_type=Product.PRODUCT_TYPE_DEFAULT,
                    defaults={"is_product_active": False},
                )
                pa.product = default_product
                updated_fields.append("product")

            if updated_fields:
                pa.save(update_fields=updated_fields)

        pa.valid_products = _build_valid_products_for_tax_year(tax_year_obj)


# To Intake Page
@login_required
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def intake(request):
    current_tax_season = get_active_tax_season()
    default_filing_type, _ = FilingType.objects.get_or_create(
        filing_type=FilingType.FILING_TYPE_DEFAULT
    )
    current_tax_year_value = timezone.now().year - 1
    clients = []

    if current_tax_season:
        active_intakes = Intake.objects.filter(
            is_active=True,
            tax_season=current_tax_season,
        ).select_related("client", "tax_season")

        for intake_row in active_intakes:
            client = intake_row.client
            product_assignments = (
                client.product_assignments.select_related(
                    "product", "tax_year", "filing_type"
                )
                .filter(intake=intake_row, is_active=True)
                .order_by(*INTAKE_PRODUCT_ASSIGNMENT_ORDERING)
            )

            _ensure_pa_defaults(
                product_assignments,
                default_filing_type=default_filing_type,
                current_tax_year_value=current_tax_year_value,
            )

            client.product_assignments_list = product_assignments
            client.first_product_assignment = (
                product_assignments.first() if product_assignments.exists() else None
            )
            clients.append(client)

    return render(
        request,
        "intake/intake.html",
        {
            "intake_clients": clients,
            "active_tax_season": current_tax_season,
            "valid_tax_years": get_valid_tax_years(),
            "filing_type_options": list(FilingType.objects.values("id", "filing_type")),
            "product_type_options": Product.PRODUCT_TYPE_CHOICES,
        },
    )


# Search for clients in database that will be added to intake
@login_required
def search_clients(request):
    query = request.GET.get("q", "").strip()
    clients = Client.objects.filter(
        Q(name__icontains=query) | Q(TIN__icontains=query)
    ).values("id", "name", "TIN")

    current_tax_season = get_active_tax_season()
    if current_tax_season:
        intake_clients = set(
            Intake.objects.filter(
                is_active=True,
                tax_season=current_tax_season,
            ).values_list("client_id", flat=True)
        )
        daily_clearing_clients = set(
            DailyClearing.objects.filter(
                is_active=True,
                tax_season=current_tax_season,
            ).values_list("client_id", flat=True)
        )
    else:
        intake_clients = set()
        daily_clearing_clients = set()

    results = []
    for client in clients:
        client_id = client["id"]
        results.append(
            {
                "id": client["id"],
                "name": client["name"],
                "TIN": client["TIN"],
                "in_intake": client_id in intake_clients,
                "in_daily_clearing": client_id in daily_clearing_clients,
            }
        )
    return JsonResponse(results, safe=False)


# Add existing client to intake
@require_POST
@login_required
def add_client_to_intake(request, client_id):
    client = get_object_or_404(Client, id=client_id)

    try:
        payload = enroll_client_in_intake(client)
    except NoActiveTaxSeasonError as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=400)

    return JsonResponse(
        {
            "status": "success",
            "message": f"{client.name} added to intake.",
            **payload,
        }
    )


# Remove client from intake (active tax season only)
@require_POST
@login_required
def remove_client_from_intake(request, client_id):
    current_tax_season = get_active_tax_season()
    if not current_tax_season:
        return JsonResponse(
            {"status": "error", "message": "No active tax season found."},
            status=400,
        )

    try:
        intake = Intake.objects.filter(
            client_id=client_id,
            tax_season=current_tax_season,
            is_active=True,
        ).first()
        if intake is None:
            return JsonResponse(
                {"status": "error", "message": "Active intake not found for this client."},
                status=404,
            )

        product_assignments = list(
            ProductAssignment.objects.filter(
                client_id=client_id,
                intake=intake,
                is_active=True,
            ).select_related("product")
        )

        for pa in product_assignments:
            enforce_pa_not_frozen_for_action(pa, action="remove_client_from_intake")

        try:
            body = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            body = {}
        bulk_reason = (body.get("cancellation_reason") or "").strip() or "Client removed from intake"

        with transaction.atomic():
            for pa in product_assignments:
                cmd_cancel_assignment(
                    pa_id=pa.id,
                    actor=request.user,
                    cancellation_reason=bulk_reason,
                )

            intake.is_active = False
            intake.save(update_fields=["is_active"])

        from clearing.services.global_parse import _reconcile_orphan_daily_clearing

        _reconcile_orphan_daily_clearing(intake.client, current_tax_season)

        return JsonResponse({"status": "success"}, status=200)

    except ValidationError as ve:
        return JsonResponse(
            {"status": "error", "code": "PA_FROZEN", "message": ve.message_dict},
            status=409,
        )

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


# Create new client and add to intake (intake page only; portfolio uses client_portfolio.views)
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
        payload = enroll_client_in_intake(client)
    except NoActiveTaxSeasonError as exc:
        return JsonResponse(
            {
                "status": "error",
                "message": f"{client.name} was created but could not be added to intake: {exc}",
                "client_id": client.id,
            },
            status=400,
        )

    return JsonResponse(
        {
            "status": "success",
            "message": f"{client.name} created and added to intake.",
            "client_id": client.id,
            **payload,
        }
    )


# Add product assignment to a client
@require_POST
@login_required
def add_product_assignment(request):
    try:
        data = json.loads(request.body)
        client_id = data.get("client_id")

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
                {"status": "error", "message": "Active intake not found."},
                status=404,
            )

        reference_tax_year = timezone.now().year - 1

        tax_year, _ = TaxYear.objects.get_or_create(client=client, year=reference_tax_year)
        filing_type, _ = FilingType.objects.get_or_create(
            filing_type=FilingType.FILING_TYPE_DEFAULT
        )
        product, _ = Product.objects.get_or_create(
            tax_year=tax_year,
            product_type=Product.PRODUCT_TYPE_DEFAULT,
            defaults={"is_product_active": False},
        )

        if active_product_assignment_conflict(
            client=client,
            intake=intake,
            tax_year=tax_year,
            product=product,
        ):
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

        seen_types = set()
        reference_valid_products = []
        for p in Product.objects.filter(tax_year__year=reference_tax_year):
            if p.product_type not in seen_types:
                reference_valid_products.append({"id": p.id, "product_type": p.product_type})
                seen_types.add(p.product_type)

        return JsonResponse(
            {
                "status": "success",
                "product_assignment": {
                    "id": product_assignment.id,
                    "tax_year": tax_year.year,
                    "product_id": product.id,
                    "product_type": product.product_type,
                    "filing_type": {"id": filing_type.id, "label": filing_type.filing_type},
                },
                "filing_type_options": list(FilingType.objects.values("id", "filing_type")),
                "product_options": reference_valid_products,
                "valid_tax_years": get_valid_tax_years(),
            }
        )

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


# Cancel product assignment from client subrow
@require_POST
@login_required
def cancel_product_assignment(request):
    try:
        data = json.loads(request.body)
        product_assignment_id = data.get("product_assignment_id")
        cancellation_reason = (data.get("cancellation_reason") or "").strip()

        if not product_assignment_id:
            return JsonResponse(
                {"status": "error", "message": "Missing product assignment ID"},
                status=400,
            )
        if not cancellation_reason:
            return JsonResponse(
                {"status": "error", "message": "Cancellation reason is required."},
                status=400,
            )

        product_assignment = get_object_or_404(ProductAssignment, id=product_assignment_id)

        enforce_pa_not_frozen_for_action(product_assignment, action="cancel_product_assignment")

        cmd_cancel_assignment(
            pa_id=product_assignment.id,
            actor=request.user,
            cancellation_reason=cancellation_reason,
        )

        from clearing.services.global_parse import _reconcile_orphan_daily_clearing

        tax_season = (
            product_assignment.intake.tax_season
            if product_assignment.intake_id
            else None
        )
        _reconcile_orphan_daily_clearing(product_assignment.client, tax_season)

        return JsonResponse({"status": "success"})

    except ValidationError as ve:
        return JsonResponse(
            {"status": "error", "code": "PA_FROZEN", "message": ve.message_dict},
            status=409,
        )

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
