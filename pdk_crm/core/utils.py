from .models import TaxSeason, Intake, DailyClearing, TaxYear, ProductAssignment, Product, FilingType, Appointment

from django.utils import timezone
from django.core.exceptions import ValidationError

import datetime


INTAKE_PRODUCT_ASSIGNMENT_ORDERING = (
    "-tax_year__year",
    "filing_type__filing_type",
    "product__product_type",
)

DUPLICATE_ACTIVE_PA_MESSAGE = (
    "An active entry with this tax year and product already exists for this client."
)


def get_default_filing_type() -> FilingType:
    """Return the default FilingType row; tolerate duplicate seed rows."""
    filing_type = (
        FilingType.objects.filter(filing_type=FilingType.FILING_TYPE_DEFAULT)
        .order_by("id")
        .first()
    )
    if filing_type is None:
        filing_type = FilingType.objects.create(
            filing_type=FilingType.FILING_TYPE_DEFAULT
        )
    return filing_type


def active_product_assignment_conflict(
    *,
    client,
    intake,
    tax_year,
    product,
    exclude_pa_id=None,
) -> bool:
    """True if another active PA shares the same client, intake, tax year, and product."""
    qs = ProductAssignment.objects.filter(
        client=client,
        intake=intake,
        tax_year=tax_year,
        product=product,
        is_active=True,
    )
    if exclude_pa_id is not None:
        qs = qs.exclude(pk=exclude_pa_id)
    return qs.exists()


def seed_products_for_tax_year(tax_year) -> None:
    """Ensure every product type exists for a client's tax year."""
    for product_type, _ in Product.PRODUCT_TYPE_CHOICES:
        Product.objects.get_or_create(
            tax_year=tax_year,
            product_type=product_type,
            defaults={"is_product_active": False},
        )


def pick_product_for_new_active_assignment(*, client, intake, tax_year):
    """
    Return the first product on tax_year that has no active PA for this client/intake,
    or None when every product type is already in use.
    """
    seed_products_for_tax_year(tax_year)
    for product_type, _ in Product.PRODUCT_TYPE_CHOICES:
        product = Product.objects.get(tax_year=tax_year, product_type=product_type)
        if not active_product_assignment_conflict(
            client=client,
            intake=intake,
            tax_year=tax_year,
            product=product,
        ):
            return product
    return None


# Get valid tax years
def get_valid_tax_years():
    current_calendar_year = datetime.datetime.now().year
    current_tax_year = current_calendar_year -1
    seven_years_before_current_tax_year = current_tax_year - 7

    return list(range(current_tax_year, seven_years_before_current_tax_year -1, -1))


def get_active_tax_season():
    """Return the active tax season (highest year when multiple are active)."""
    return TaxSeason.objects.filter(is_active=True).order_by("-year").first()


# utility to return a newly created or activated intake NOTE: may be accessed by any module
def get_or_create_intake(client):
    current_tax_season = get_active_tax_season()
    if not current_tax_season:
        raise ValueError("No active tax season.")
    
    intake, _ = Intake.objects.get_or_create(
        client = client,
        tax_season = current_tax_season,
        defaults = {'is_active': True}
    )

    if not intake.is_active:
        intake.is_active = True
        intake.save()

    return intake


# utility to return a newly created or activated product_assignment NOTE: may be accessed by any module
def get_or_create_product_assignment(client, intake):
    # check for existing active ProductAssignment instances for the intake
    existing_assignments = ProductAssignment.objects.filter(
        client = client,
        intake = intake,
        is_active = True,
    ).order_by('tax_year__year')

    if existing_assignments.exists():
        return existing_assignments.first()
    
    # if product assignment doesn't exist then create one
    current_tax_year_value = timezone.now().year - 1

    tax_year, _ = TaxYear.objects.get_or_create(
        client = client,
        year = current_tax_year_value
    )

    filing_type = get_default_filing_type()

    # seeds all default products for the tax year (if not already present) NOTE: essential to the creation of product ->> product_assignment
    for pt, _ in Product.PRODUCT_TYPE_CHOICES:
        Product.objects.get_or_create(tax_year = tax_year, product_type = pt)

    product = Product.objects.get(
        tax_year = tax_year,
        product_type = Product.PRODUCT_TYPE_DEFAULT
    )

    # get or create product assignment via product assignment factory manager
    product_assignment, _ = ProductAssignment.objects.create_product_assignment(
        client = client,
        intake = intake,
        tax_year = tax_year,
        product = product,
        filing_type = filing_type,
        is_active = True
    )

    return product_assignment


# allows user to create new PA if an unmatched acknowledgment is found
def get_or_create_product_assignment_for_tax_year(client, intake, tax_year_value):
    tax_year, _ = TaxYear.objects.get_or_create(client = client, year = tax_year_value)

    filing_type = get_default_filing_type()

    for pt, _ in Product.PRODUCT_TYPE_CHOICES:
        Product.objects.get_or_create(tax_year = tax_year, product_type = pt)
    
    product = Product.objects.get(tax_year = tax_year, product_type = Product.PRODUCT_TYPE_DEFAULT)

    product_assignment, _ = ProductAssignment.objects.create_product_assignment(client = client, intake = intake, tax_year = tax_year, product = product, filing_type = filing_type, is_active = True)

    return product_assignment


# create an appointment that can be associated with a single product assignment
def get_or_create_appointment(product_assignment):
    if not hasattr(product_assignment, 'appointment'):
        appointment = Appointment.objects.create(product_assignment = product_assignment)
    else:
        appointment = product_assignment.appointment
    return appointment


def enforce_pa_not_frozen_for_action(pa, *, action: str):
    """
    Block structural changes (deactivate/remove) once lifecycle has left IN_CLEARING
    or legacy completion has started.
    """
    from core.models import CompletionState, LifecycleState

    state = (pa.lifecycle_state or "").strip()
    removable_states = {LifecycleState.IN_CLEARING, LifecycleState.CANCELLED}
    if state and state not in removable_states:
        raise ValidationError({"__all__": f"PA is frozen (lifecycle={state}). Action '{action}' not allowed."})

    if pa.completion_state and pa.completion_state != CompletionState.OPEN:
        raise ValidationError(
            {"__all__": f"PA is frozen (legacy completion={pa.completion_state}). Action '{action}' not allowed."}
        )
    
