"""
Path A global PDF upload: preview (parse + TIN match) and commit (enrollment + apply).
"""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import (
    Client,
    DailyClearing,
    FilingType,
    Intake,
    LifecycleState,
    Product,
    ProductAssignment,
    TaxYear,
)
from core.utils import (
    DUPLICATE_ACTIVE_PA_MESSAGE,
    active_product_assignment_conflict,
    get_active_tax_season,
    get_or_create_appointment,
    get_or_create_intake,
    get_valid_tax_years,
    seed_products_for_tax_year,
)
from core.workflows.lifecycle import (
    cmd_enter_clearing,
    cmd_void_pa_for_parse_replace,
    is_pa_locked_for_editing,
)

from clearing.services.enrollment import activate_client_in_clearing
from clearing.services.enrollment_inference import build_suggested_enrollment
from clearing.services.parse_upload import (
    ParseUploadError,
    apply_parser_from_job,
)
from clearing.services.pdf_manager_client import PDFManagerClient, PDFManagerError
from clearing.services.parser_outputs import parser_downloads_payload

from intake.services.enrollment import NoActiveTaxSeasonError


class GlobalParseError(Exception):
    """User-facing global upload failure."""


_TIN_RE = re.compile(r"\D+")


def normalize_tin(value: str | None) -> str | None:
    if not value:
        return None
    digits = _TIN_RE.sub("", str(value))
    return digits if len(digits) == 9 else None


def _parse_tax_year(fields: dict[str, Any]) -> int | None:
    raw = fields.get("tax_year")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def build_extracted_preview(detail: dict[str, Any]) -> dict[str, Any]:
    fields = detail.get("fields") or {}
    if not isinstance(fields, dict):
        fields = {}
    quality = fields.get("message_ready")
    return {
        "taxpayer_tin": normalize_tin(fields.get("taxpayer_tin")),
        "taxpayer_full_name": (fields.get("taxpayer_full_name") or "").strip(),
        "tax_year": str(fields.get("tax_year") or "").strip() or None,
        "message_ready": bool(quality),
    }


def _validate_pdf_tin_matches_client(
    tin: str | None,
    client: Client,
    *,
    error_cls: type[Exception] = GlobalParseError,
) -> None:
    """Reject when extracted TIN disagrees with the target CRM client."""
    if not tin or not client.TIN:
        return
    if client.TIN != tin:
        raise error_cls("Uploaded TIN does not match the selected client.")


def _reconcile_orphan_daily_clearing(client: Client, tax_season) -> None:
    """
    Deactivate DailyClearing when the client has no active board PAs.

    Prevents stale clearing flags after cancelled uploads or voided rows.
    """
    if not tax_season:
        return
    has_board_pas = ProductAssignment.objects.filter(
        client=client,
        intake__tax_season=tax_season,
        is_active=True,
    ).exists()
    if has_board_pas:
        return
    DailyClearing.objects.filter(
        client=client,
        tax_season=tax_season,
        is_active=True,
    ).update(is_active=False)


def _is_empty_manual_placeholder(pa: ProductAssignment) -> bool:
    """Path B row with no parser job — safe to auto-apply a global PDF upload."""
    return (
        pa.is_active
        and not pa.parse_job_uuid
        and not is_pa_locked_for_editing(pa)
    )


def _resolve_auto_apply_pa(assignments: list[ProductAssignment]) -> int | None:
    """When exactly one unlocked manual placeholder exists, skip conflict modal."""
    placeholders = [pa for pa in assignments if _is_empty_manual_placeholder(pa)]
    if len(placeholders) == 1 and len(assignments) == 1:
        return placeholders[0].id
    return None


def _active_clearing_pas(client: Client, tax_season) -> list[ProductAssignment]:
    intake = Intake.objects.filter(
        client=client,
        tax_season=tax_season,
        is_active=True,
    ).first()
    if not intake:
        return []
    return list(
        ProductAssignment.objects.filter(
            client=client,
            intake=intake,
            is_active=True,
        )
        .select_related("tax_year", "filing_type", "product")
        .order_by("-tax_year__year", "product__product_type")
    )


def build_match_payload(client: Client | None) -> dict[str, Any]:
    if client is None:
        return {
            "client_id": None,
            "client_name": None,
            "on_clearing": False,
            "auto_apply_pa_id": None,
            "product_assignments": [],
        }

    tax_season = get_active_tax_season()
    assignments = _active_clearing_pas(client, tax_season) if tax_season else []
    if tax_season:
        _reconcile_orphan_daily_clearing(client, tax_season)
    # Board presence requires at least one active PA, not DailyClearing alone.
    on_clearing = bool(assignments)
    auto_apply_pa_id = _resolve_auto_apply_pa(assignments)
    return {
        "client_id": client.id,
        "client_name": client.name,
        "on_clearing": on_clearing,
        "auto_apply_pa_id": auto_apply_pa_id,
        "product_assignments": [
            {
                "id": pa.id,
                "tax_year": pa.tax_year.year if pa.tax_year_id else None,
                "filing_type": pa.filing_type.filing_type if pa.filing_type_id else "",
                "product_type": pa.product.product_type if pa.product_id else "",
                "is_locked": is_pa_locked_for_editing(pa),
                "is_empty_placeholder": _is_empty_manual_placeholder(pa),
            }
            for pa in assignments
        ],
    }


def lookup_client_by_tin(tin: str | None) -> Client | None:
    if not tin:
        return None
    return Client.objects.filter(TIN=tin).first()


def resolve_product_for_enrollment(
    *,
    client: Client,
    tax_year_value: int,
    product_id: int,
) -> tuple[TaxYear, Product]:
    tax_year, _ = TaxYear.objects.get_or_create(client=client, year=tax_year_value)
    seed_products_for_tax_year(tax_year)
    selected = Product.objects.get(pk=product_id)
    product = Product.objects.get(
        tax_year=tax_year,
        product_type=selected.product_type,
    )
    return tax_year, product


def create_enrollment_pa(
    *,
    client: Client,
    intake: Intake,
    tax_year_value: int,
    filing_type_id: int,
    product_id: int,
    actor=None,
    force_new: bool = False,
) -> ProductAssignment:
    tax_year, product = resolve_product_for_enrollment(
        client=client,
        tax_year_value=tax_year_value,
        product_id=product_id,
    )
    filing_type = FilingType.objects.get(pk=filing_type_id)

    if active_product_assignment_conflict(
        client=client,
        intake=intake,
        tax_year=tax_year,
        product=product,
    ):
        raise GlobalParseError(DUPLICATE_ACTIVE_PA_MESSAGE)

    if force_new:
        from decimal import Decimal

        pa = ProductAssignment.objects.create(
            client=client,
            intake=intake,
            tax_year=tax_year,
            product=product,
            filing_type=filing_type,
            is_active=True,
            fee=Decimal(str(product.default_price or 0)),
        )
    else:
        pa, _ = ProductAssignment.objects.create_product_assignment(
            client=client,
            intake=intake,
            tax_year=tax_year,
            product=product,
            filing_type=filing_type,
            is_active=True,
        )
    if DailyClearing.objects.filter(
        client=client,
        tax_season=intake.tax_season,
        is_active=True,
    ).exists():
        cmd_enter_clearing(pa_id=pa.id, actor=actor)
    get_or_create_appointment(pa)
    return pa


def preview_global_upload(
    uploaded_file,
    *,
    client: PDFManagerClient | None = None,
) -> dict[str, Any]:
    filename = getattr(uploaded_file, "name", "") or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise GlobalParseError("Only PDF files are supported.")

    pdf_client = client or PDFManagerClient()
    try:
        uploaded_file.seek(0)
        detail = pdf_client.upload_and_fetch_detail(
            file_obj=uploaded_file,
            filename=filename,
        )
    except PDFManagerError as exc:
        raise GlobalParseError(str(exc)) from exc

    job_id = detail.get("job_id")
    if not job_id:
        raise GlobalParseError("Parser did not return a job id.")

    extracted = build_extracted_preview(detail)
    matched_client = lookup_client_by_tin(extracted.get("taxpayer_tin"))

    return {
        "status": "success",
        "parse_job_uuid": str(job_id),
        "extracted": extracted,
        "match": build_match_payload(matched_client),
        "suggested_enrollment": build_suggested_enrollment(
            detail,
            client=matched_client,
        ),
    }


def _fetch_job_detail(parse_job_uuid: str, pdf_client: PDFManagerClient) -> dict[str, Any]:
    try:
        job_uuid = UUID(str(parse_job_uuid))
    except (TypeError, ValueError) as exc:
        raise GlobalParseError("Invalid parse job id.") from exc

    try:
        detail = pdf_client.get_job(job_uuid, detail=True)
    except PDFManagerError as exc:
        raise GlobalParseError(str(exc)) from exc

    status = (detail.get("status") or "").lower()
    if status in {"error", "failed"}:
        raise GlobalParseError("Parser job failed.")
    if status in {"cancelled", "applied"}:
        raise GlobalParseError("This upload session is no longer available.")
    if status not in {"done", "success"}:
        raise GlobalParseError("Parser job is not ready.")

    detail.setdefault("job_id", str(job_uuid))
    return detail


def _validated_tax_year(detail: dict[str, Any], override: int | None = None) -> int:
    fields = detail.get("fields") or {}
    tax_year_value = override if override is not None else _parse_tax_year(fields)
    if tax_year_value is None:
        raise GlobalParseError("Tax year could not be determined from the PDF.")
    if tax_year_value not in get_valid_tax_years():
        raise GlobalParseError("Tax year from PDF is not valid for enrollment.")
    return tax_year_value


def _require_enrollment_fields(
    *,
    filing_type_id: int | None,
    product_id: int | None,
) -> tuple[int, int]:
    if not filing_type_id or not product_id:
        raise GlobalParseError("Filing type and product are required.")
    return int(filing_type_id), int(product_id)


def _mark_job_cancelled(parse_job_uuid: str, pdf_client: PDFManagerClient) -> None:
    try:
        pdf_client.set_job_disposition(parse_job_uuid, status="CANCELLED")
    except PDFManagerError as exc:
        raise GlobalParseError(str(exc)) from exc


def _mark_job_applied(parse_job_uuid: str, pdf_client: PDFManagerClient) -> None:
    try:
        pdf_client.set_job_disposition(parse_job_uuid, status="APPLIED")
    except PDFManagerError as exc:
        raise GlobalParseError(str(exc)) from exc


def commit_global_upload(
    *,
    parse_job_uuid: str,
    action: str,
    actor=None,
    client_id: int | None = None,
    pa_id: int | None = None,
    filing_type_id: int | None = None,
    product_id: int | None = None,
    tax_year: int | None = None,
    pdf_client: PDFManagerClient | None = None,
) -> dict[str, Any]:
    pdf_client = pdf_client or PDFManagerClient()
    detail = _fetch_job_detail(parse_job_uuid, pdf_client)
    extracted = build_extracted_preview(detail)
    tin = extracted.get("taxpayer_tin")

    if action == "cancel":
        _mark_job_cancelled(parse_job_uuid, pdf_client)
        return {
            "status": "success",
            "action": "cancel",
            "parse_job_uuid": str(parse_job_uuid),
            "message": "Upload cancelled.",
        }

    voided_pa_id: int | None = None
    target_client: Client | None = None
    target_pa: ProductAssignment | None = None

    with transaction.atomic():
        if action == "new_client":
            if not tin:
                raise GlobalParseError("Taxpayer TIN is required to create a client.")
            if lookup_client_by_tin(tin):
                raise GlobalParseError("A client with this TIN already exists.")

            ft_id, prod_id = _require_enrollment_fields(
                filing_type_id=filing_type_id,
                product_id=product_id,
            )
            tax_year_value = _validated_tax_year(detail, tax_year)
            name = extracted.get("taxpayer_full_name") or f"Unknown ({tin[-4:]})"

            target_client = Client.objects.create(TIN=tin, name=name)
            try:
                get_or_create_intake(target_client)
                activate_client_in_clearing(target_client, actor=actor)
            except NoActiveTaxSeasonError as exc:
                raise GlobalParseError(str(exc)) from exc

            intake = get_or_create_intake(target_client)
            target_pa = create_enrollment_pa(
                client=target_client,
                intake=intake,
                tax_year_value=tax_year_value,
                filing_type_id=ft_id,
                product_id=prod_id,
                actor=actor,
            )

        elif action == "enroll":
            if not client_id:
                raise GlobalParseError("Client id is required.")
            target_client = Client.objects.filter(pk=client_id).first()
            if not target_client:
                raise GlobalParseError("Client not found.")
            _validate_pdf_tin_matches_client(tin, target_client)

            ft_id, prod_id = _require_enrollment_fields(
                filing_type_id=filing_type_id,
                product_id=product_id,
            )
            tax_year_value = _validated_tax_year(detail, tax_year)

            try:
                get_or_create_intake(target_client)
                activate_client_in_clearing(target_client, actor=actor)
            except NoActiveTaxSeasonError as exc:
                raise GlobalParseError(str(exc)) from exc

            intake = get_or_create_intake(target_client)
            target_pa = create_enrollment_pa(
                client=target_client,
                intake=intake,
                tax_year_value=tax_year_value,
                filing_type_id=ft_id,
                product_id=prod_id,
                actor=actor,
            )

        elif action == "new_entry":
            if not client_id:
                raise GlobalParseError("Client id is required.")
            target_client = Client.objects.filter(pk=client_id).first()
            if not target_client:
                raise GlobalParseError("Client not found.")
            _validate_pdf_tin_matches_client(tin, target_client)

            tax_season = get_active_tax_season()
            if not tax_season or not DailyClearing.objects.filter(
                client=target_client,
                tax_season=tax_season,
                is_active=True,
            ).exists():
                raise GlobalParseError("Client is not on active clearing.")

            ft_id, prod_id = _require_enrollment_fields(
                filing_type_id=filing_type_id,
                product_id=product_id,
            )
            tax_year_value = _validated_tax_year(detail, tax_year)
            intake = Intake.objects.filter(
                client=target_client,
                tax_season=tax_season,
                is_active=True,
            ).first()
            if not intake:
                raise GlobalParseError("Active intake not found.")

            target_pa = create_enrollment_pa(
                client=target_client,
                intake=intake,
                tax_year_value=tax_year_value,
                filing_type_id=ft_id,
                product_id=prod_id,
                actor=actor,
            )

        elif action == "apply":
            if not client_id or not pa_id:
                raise GlobalParseError("Client and product assignment are required.")
            target_client = Client.objects.filter(pk=client_id).first()
            if not target_client:
                raise GlobalParseError("Client not found.")
            _validate_pdf_tin_matches_client(tin, target_client)

            target_pa = ProductAssignment.objects.select_related(
                "tax_year", "filing_type", "product", "intake"
            ).filter(pk=pa_id, client=target_client, is_active=True).first()
            if not target_pa:
                raise GlobalParseError("Product assignment not found.")
            if not _is_empty_manual_placeholder(target_pa):
                raise GlobalParseError(
                    "This entry already has parser data or is locked. "
                    "Use Replace Entry or New Entry instead."
                )

        elif action == "replace":
            if not client_id or not pa_id:
                raise GlobalParseError("Client and product assignment are required.")
            target_client = Client.objects.filter(pk=client_id).first()
            if not target_client:
                raise GlobalParseError("Client not found.")
            _validate_pdf_tin_matches_client(tin, target_client)

            old_pa = ProductAssignment.objects.select_related(
                "tax_year", "filing_type", "product", "intake"
            ).filter(pk=pa_id, client=target_client).first()
            if not old_pa or not old_pa.is_active:
                raise GlobalParseError("Product assignment not found.")

            if is_pa_locked_for_editing(old_pa):
                raise GlobalParseError(
                    "This entry has already completed clearing. "
                    "Create a new entry with the appropriate fee instead."
                )

            ft_id = filing_type_id or (old_pa.filing_type_id if old_pa.filing_type_id else None)
            prod_id = product_id or (old_pa.product_id if old_pa.product_id else None)
            ft_id, prod_id = _require_enrollment_fields(
                filing_type_id=ft_id,
                product_id=prod_id,
            )
            tax_year_value = _validated_tax_year(
                detail,
                tax_year or (old_pa.tax_year.year if old_pa.tax_year_id else None),
            )

            voided_pa_id = old_pa.id
            cmd_void_pa_for_parse_replace(pa_id=old_pa.id, actor=actor)
            target_pa = create_enrollment_pa(
                client=target_client,
                intake=old_pa.intake,
                tax_year_value=tax_year_value,
                filing_type_id=ft_id,
                product_id=prod_id,
                actor=actor,
                force_new=True,
            )
            old_pa.superseded_by_id = target_pa.id
            old_pa.save(update_fields=["superseded_by"])

        else:
            raise GlobalParseError(f"Unknown action: {action}")

        if target_pa is None or target_client is None:
            raise GlobalParseError("Enrollment did not produce a product assignment.")

        try:
            apply_parser_from_job(target_pa, parse_job_uuid, client=pdf_client, detail=detail)
        except ParseUploadError as exc:
            raise GlobalParseError(str(exc)) from exc

        _mark_job_applied(parse_job_uuid, pdf_client)
        target_pa.refresh_from_db()

    return {
        "status": "success",
        "action": action,
        "client_id": target_client.id,
        "product_assignment_id": target_pa.id,
        "voided_product_assignment_id": voided_pa_id,
        "parse_job_uuid": str(parse_job_uuid),
        "lifecycle_state": target_pa.lifecycle_state or LifecycleState.IN_CLEARING,
        "message": "PDF applied to clearing entry.",
        "downloads": parser_downloads_payload(target_pa),
    }
