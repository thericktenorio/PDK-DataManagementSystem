"""Drake MEF form-type → product-family mapping for ack matching."""

from core.models import FilingType, Product, ProductAssignment


# Federal and common state personal income forms
PERSONAL_FORM_TYPES = frozenset({
    "1040", "1040SR", "1040NR", "1040X",
    "CA540", "CA5402EZ", "CA540NR", "CA540X", "CA",
    "AZ140", "AZ140NR", "AZ140X",
    "AR1000F", "AR1000NR",
    "CO104", "CO104PN", "CO104NR",
    "CT1040", "CT1040NR",
    "GA500", "GA500X",
    "IL1040", "IL1040X",
    "IN40", "IN40PNR",
    "IA1040",
    "KS40", "KS40X",
    "KY740", "KY740X",
    "LA540", "LA540B", "LA540X",
    "ME1040", "ME1040NR",
    "MD502", "MD505", "MD505X",
    "MA1", "MA1NR",
    "MI1040", "MI1040CR",
    "MN1040", "M1",
    "MS80", "MS80X",
    "MO1040", "MO1040NR",
    "MT2", "MT2X",
    "NE1040N", "NE1040XN",
    "NJ1040", "NJ1040NR",
    "NM1040", "NM1040X",
    "NY203", "NY203X", "IT201", "IT203",
    "NC400", "D400",
    "ND1", "ND1X",
    "OH1040", "OH1040X", "OHIT1040",
    "OK511", "OK511NR", "OK511X",
    "OR40", "OR40P", "OR40N", "OR40X",
    "PA40", "PA40X", "PA41",
    "RI1040", "RI1040NR",
    "SC1040", "SC1040X",
    "UT40", "UT40X",
    "VTIN111", "VTIN112",
    "VA760", "VA763", "VA763X",
    "WVIT140", "WVIT140X",
    "WI1", "WI1X",
    "WAWFTC",
})

# Corporate, partnership, fiduciary, nonprofit, LLC
CORPORATE_FORM_TYPES = frozenset({
    "1120", "1120S", "1120X", "1120SX",
    "1065", "1065X",
    "1041", "1041X",
    "990", "990EZ", "990PF", "990T", "990X",
    "CA100", "CA100S", "CA565", "CA568", "CA199", "CA541", "CA541X",
    "CALLC01", "CALLC02", "CALLC03",
    "AZ120", "AZ120S", "AZ120X",
    "NCD400", "CD405",
    "OHIT1041", "OHSD100",
    "TN173", "TN173C",
    "TX05163", "TX05164",
    "FL1120", "F1120",
})

EXTENSION_FORM_TYPES = frozenset({
    "4868", "7004", "7004-09", "8868", "8868-01",
})

# Federal e-file forms (state forms live in PERSONAL/CORPORATE sets minus this bucket).
FEDERAL_FORM_TYPES = frozenset({
    "1040", "1040SR", "1040NR", "1040X",
    "1120", "1120S", "1120X", "1120SX",
    "1065", "1065X",
    "1041", "1041X",
    "990", "990EZ", "990PF", "990T", "990X",
    *EXTENSION_FORM_TYPES,
})


def ack_jurisdiction_bucket(form_type: str) -> str | None:
    """Return ``federal``, ``state``, or None for clearing status columns."""
    if not form_type:
        return None
    ft = form_type.strip().upper()
    if ft in FEDERAL_FORM_TYPES:
        return "federal"
    if ft in PERSONAL_FORM_TYPES or ft in CORPORATE_FORM_TYPES:
        return "state"
    return None


def map_form_to_family(form_type: str) -> str | None:
    if not form_type:
        return None
    ft = form_type.strip().upper()

    if ft.endswith("X") and ft not in PERSONAL_FORM_TYPES and ft not in CORPORATE_FORM_TYPES:
        return "AMENDMENT"

    if ft in EXTENSION_FORM_TYPES:
        return "EXTENSION"

    if ft in PERSONAL_FORM_TYPES:
        return "PERSONAL"

    if ft in CORPORATE_FORM_TYPES:
        return "CORPORATE"

    return None


def bucket_from_filing_type(client, tax_year_value: int) -> str | None:
    pa = (
        ProductAssignment.objects.filter(
            client=client, tax_year__year=tax_year_value, is_active=True
        )
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
        return None

    if filing_type_value == FilingType.FILING_TYPE_CORPORATION:
        return Product.PRODUCT_TYPE_CORPORATE_TAXES

    return Product.PRODUCT_TYPE_PERSONAL_TAXES


def resolve_product_type(*, form_type: str, client, tax_year_value: int) -> tuple[str | None, str | None]:
    """
    Returns (product_type, error_reason).
    error_reason is set when staging is required instead of matching.
    """
    family = map_form_to_family(form_type)
    if family in ("EXTENSION", "AMENDMENT"):
        product_type = bucket_from_filing_type(client, tax_year_value)
        if not product_type:
            return None, "Can't map extension / amendment without a non-TBD filing type."
        return product_type, None
    if family == "CORPORATE":
        return Product.PRODUCT_TYPE_CORPORATE_TAXES, None
    if family == "PERSONAL":
        return Product.PRODUCT_TYPE_PERSONAL_TAXES, None
    return None, "Unknown or unsupported form type; cannot map to a product type."
