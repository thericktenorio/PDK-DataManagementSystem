"""Clearing enrollment: DailyClearing + lifecycle after intake enrollment."""
from __future__ import annotations

from core.models import Client, DailyClearing
from core.utils import get_active_tax_season, get_or_create_intake
from core.workflows.lifecycle import enter_clearing_for_client_assignments

from intake.services.enrollment import NoActiveTaxSeasonError


def activate_client_in_clearing(client: Client, *, actor=None) -> None:
    """
    Add client to daily clearing for the active tax season and transition
    active product assignments to IN_CLEARING. Requires intake to exist.
    """
    current_tax_season = get_active_tax_season()
    if current_tax_season is None:
        raise NoActiveTaxSeasonError("No active tax season found.")

    intake = get_or_create_intake(client)

    clearing, _ = DailyClearing.objects.get_or_create(
        client=client,
        tax_season=current_tax_season,
        defaults={"is_active": True},
    )
    if not clearing.is_active:
        clearing.is_active = True
        clearing.save(update_fields=["is_active"])

    enter_clearing_for_client_assignments(
        client_id=client.id,
        intake_id=intake.id,
        actor=actor,
    )
