"""Intake enrollment: Intake + ProductAssignment for the active tax season."""
from __future__ import annotations

from core.models import Client, FilingType, Product, ProductAssignment
from core.utils import (
    get_active_tax_season,
    get_or_create_intake,
    get_or_create_product_assignment,
    get_valid_tax_years,
)


class NoActiveTaxSeasonError(Exception):
    """Raised when intake enrollment requires an active tax season."""


def _product_options_for_tax_year(tax_year) -> list[dict]:
    seen_types: set[str] = set()
    options: list[dict] = []
    for product in Product.objects.filter(tax_year=tax_year).order_by("product_type", "id"):
        if product.product_type in seen_types:
            continue
        options.append({"id": product.id, "product_type": product.product_type})
        seen_types.add(product.product_type)
    return options


def enrollment_payload(client: Client, product_assignment: ProductAssignment) -> dict:
    tax_year = product_assignment.tax_year
    product = product_assignment.product
    filing_type = product_assignment.filing_type

    return {
        "client": {
            "id": client.id,
            "TIN": client.TIN,
            "name": client.name,
        },
        "product_assignment": {
            "id": product_assignment.id,
            "tax_year": tax_year.year,
            "product_id": product.id,
            "product_type": product.product_type,
            "filing_type": {
                "id": filing_type.id,
                "label": filing_type.filing_type,
            },
        },
        "filing_type_options": list(FilingType.objects.values("id", "filing_type")),
        "product_options": _product_options_for_tax_year(tax_year),
        "valid_tax_years": get_valid_tax_years(),
    }


def enroll_client_in_intake(client: Client) -> dict:
    """
    Create or reactivate Intake + default ProductAssignment for the active tax season.

    Does not create DailyClearing or transition lifecycle (that happens in clearing).
    """
    if get_active_tax_season() is None:
        raise NoActiveTaxSeasonError("No active tax season found.")

    intake = get_or_create_intake(client)
    product_assignment = get_or_create_product_assignment(client, intake)
    return enrollment_payload(client, product_assignment)
