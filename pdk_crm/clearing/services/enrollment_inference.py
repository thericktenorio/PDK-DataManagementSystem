"""
Map parser enrollment_signals to CRM FilingType + Product catalog IDs for Path A preview.
"""
from __future__ import annotations

from typing import Any

from accounts.models import InternalUser

from core.models import Client, FilingType, Product, ProductAssignment, TaxYear
from core.utils import seed_products_for_tax_year

MANUAL_ONLY_PRODUCT_TYPES = frozenset({
    Product.PRODUCT_TYPE_WITHHOLDINGS_ADJUSTMENT,
    Product.PRODUCT_TYPE_ADVISORY,
    Product.PRODUCT_TYPE_REJECT_CORRECTION,
    Product.PRODUCT_TYPE_PAPER_FILING,
})


def _signals_from_fields(fields: dict[str, Any]) -> dict[str, Any]:
    raw = fields.get("enrollment_signals")
    return raw if isinstance(raw, dict) else {}


def infer_filing_type_string(signals: dict[str, Any]) -> str:
    """First-match filing type per Path A business rules."""
    if signals.get("is_corporation"):
        return FilingType.FILING_TYPE_CORPORATION

    business_income = signals.get("comparison_business_income")
    rental_income = signals.get("comparison_rental_income")
    if signals.get("has_sole_prop_schedule") or business_income or rental_income:
        return FilingType.FILING_TYPE_SOLE_PROP

    itemized = signals.get("comparison_itemized_deductions")
    standard = signals.get("comparison_standard_deduction")
    if itemized is not None and standard is not None and itemized > standard:
        return FilingType.FILING_TYPE_ITEMIZING

    dependents = signals.get("comparison_num_dependents")
    credits = signals.get("comparison_credits")
    if (dependents is not None and dependents >= 1) or (credits is not None and credits > 0):
        return FilingType.FILING_TYPE_CREDITS

    if signals:
        return FilingType.FILING_TYPE_SIMPLE
    return FilingType.FILING_TYPE_DEFAULT


def infer_product_type_string(signals: dict[str, Any], *, filing_type: str) -> str:
    """First-match product per Path A business rules."""
    if signals.get("has_extension"):
        return Product.PRODUCT_TYPE_FREE_EXTENSION

    amendment_count = int(signals.get("amendment_count") or 0)
    if amendment_count >= 3:
        return Product.PRODUCT_TYPE_AMENDMENT_THREE
    if amendment_count == 2:
        return Product.PRODUCT_TYPE_AMENDMENT_TWO
    if amendment_count >= 1:
        return Product.PRODUCT_TYPE_AMENDMENT_ONE

    if filing_type == FilingType.FILING_TYPE_CORPORATION:
        return Product.PRODUCT_TYPE_CORPORATE_TAXES

    return Product.PRODUCT_TYPE_PERSONAL_TAXES


def infer_payment_method(fields: dict[str, Any]) -> str:
    if fields.get("has_tpg_pages"):
        return ProductAssignment.PAYMENT_METHOD_TPG
    return ProductAssignment.PAYMENT_METHOD_QBO


def match_preparer_id(signals: dict[str, Any]) -> int | None:
    name = (signals.get("preparer_name") or "").strip()
    if not name:
        return None

    normalized = " ".join(name.upper().split())
    for user in InternalUser.objects.filter(role="tax_preparer", is_active=True):
        full = f"{user.first_name} {user.last_name}".strip().upper()
        if full and full == normalized:
            return user.id
    return None


def _build_reasons(
    signals: dict[str, Any],
    *,
    filing_type: str,
    product_type: str,
    payment_method: str,
    preparer_id: int | None,
) -> list[str]:
    reasons: list[str] = []
    if signals.get("is_corporation"):
        reasons.append("Corporation outline (1120/1120S)")
    if signals.get("has_sole_prop_schedule"):
        reasons.append("Schedule C/E/SE in outline")
    if signals.get("comparison_itemized_deductions") and signals.get("comparison_standard_deduction"):
        reasons.append("Comparison itemized > standard deduction")
    if signals.get("comparison_num_dependents"):
        reasons.append(f"Comparison dependents={signals['comparison_num_dependents']}")
    if signals.get("comparison_credits"):
        reasons.append(f"Comparison credits={signals['comparison_credits']}")
    if signals.get("has_extension"):
        reasons.append("Extension form in outline")
    if int(signals.get("amendment_count") or 0) > 0:
        reasons.append(f"Amendment outlines={signals['amendment_count']}")
    if filing_type == FilingType.FILING_TYPE_SIMPLE and not reasons:
        reasons.append("Default simple filing type")
    if product_type == Product.PRODUCT_TYPE_PERSONAL_TAXES:
        reasons.append("Default personal taxes product")
    if product_type == Product.PRODUCT_TYPE_CORPORATE_TAXES:
        reasons.append("Corporate taxes for corporation filing type")
    if payment_method == ProductAssignment.PAYMENT_METHOD_TPG:
        reasons.append("TPG pages detected")
    elif payment_method == ProductAssignment.PAYMENT_METHOD_QBO:
        reasons.append("QBO default (no TPG pages)")
    if preparer_id:
        reasons.append(f"Preparer matched: {signals.get('preparer_name')}")
    return reasons


def resolve_catalog_ids(
    *,
    client: Client | None,
    tax_year_value: int,
    filing_type_str: str,
    product_type_str: str,
) -> tuple[int | None, int | None]:
    filing_type = (
        FilingType.objects.filter(filing_type=filing_type_str).order_by("id").first()
    )
    filing_type_id = filing_type.id if filing_type else None

    tax_year: TaxYear | None = None
    if client is not None:
        tax_year, _ = TaxYear.objects.get_or_create(client=client, year=tax_year_value)
    else:
        tax_year = TaxYear.objects.filter(year=tax_year_value).order_by("id").first()

    product_id = None
    if tax_year is not None:
        seed_products_for_tax_year(tax_year)
        product = Product.objects.filter(
            tax_year=tax_year,
            product_type=product_type_str,
        ).first()
        if product is not None:
            product_id = product.id

    return filing_type_id, product_id


def build_suggested_enrollment(
    detail: dict[str, Any],
    *,
    client: Client | None = None,
) -> dict[str, Any]:
    fields = detail.get("fields") or {}
    if not isinstance(fields, dict):
        fields = {}

    signals = _signals_from_fields(fields)
    tax_year_raw = fields.get("tax_year")
    tax_year_value: int | None = None
    if tax_year_raw is not None and str(tax_year_raw).strip():
        try:
            tax_year_value = int(str(tax_year_raw).strip())
        except (TypeError, ValueError):
            tax_year_value = None

    filing_type = infer_filing_type_string(signals)
    product_type = infer_product_type_string(signals, filing_type=filing_type)
    payment_method = infer_payment_method(fields)
    preparer_id = match_preparer_id(signals)

    filing_type_id, product_id = (None, None)
    if tax_year_value is not None:
        filing_type_id, product_id = resolve_catalog_ids(
            client=client,
            tax_year_value=tax_year_value,
            filing_type_str=filing_type,
            product_type_str=product_type,
        )

    reasons = _build_reasons(
        signals,
        filing_type=filing_type,
        product_type=product_type,
        payment_method=payment_method,
        preparer_id=preparer_id,
    )

    return {
        "filing_type_id": filing_type_id,
        "product_id": product_id,
        "filing_type": filing_type,
        "product_type": product_type,
        "preparer_id": preparer_id,
        "payment_method": payment_method,
        "reasons": reasons,
        "auto_commit_eligible": product_type not in MANUAL_ONLY_PRODUCT_TYPES,
    }


def is_auto_commit_eligible(suggested: dict[str, Any] | None) -> bool:
    if not suggested:
        return False
    if not suggested.get("filing_type_id") or not suggested.get("product_id"):
        return False
    if suggested.get("product_type") in MANUAL_ONLY_PRODUCT_TYPES:
        return False
    return bool(suggested.get("auto_commit_eligible", True))
