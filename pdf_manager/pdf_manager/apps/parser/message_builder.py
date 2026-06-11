from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from pdf_manager.apps.parser.extraction_schema import taxpayer_display_name


def render_message(templates_dir: Path, template_key: str | None, context: dict[str, Any]) -> str:
    """Render a message using Jinja2 from templates/messages."""
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(disabled_extensions=("txt",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    name = f"{(template_key or 'generic').lower()}.txt.j2"
    tpl = env.get_template(name)

    return tpl.render(**context)


# ------------------------------
# ------- HELPER METHODS -------
# ------------------------------
def _has_refund_amount(federal_amount, states: list[dict]) -> bool:
    amounts = [federal_amount] + [s.get("amount") for s in states]
    return any(a is not None and a > 0 for a in amounts)


def _has_balance_due(federal_amount, states: list[dict]) -> bool:
    amounts = [federal_amount] + [s.get("amount") for s in states]
    return any(a is not None and a < 0 for a in amounts)


def _has_banking_info(last4: str | None, bank_name: str | None) -> bool:
    """Direct-deposit copy requires both institution name and account last-4."""
    return bool(str(last4 or "").strip() and str(bank_name or "").strip())


def build_tax_prep_fee_statement(
    has_tpg_pages: bool,
    tax_prep_fee,
    *,
    federal_amount=None,
    states: list[dict] | None = None,
) -> str:
    """
    Fee copy rules:
    - No extracted fee → omit.
    - TPG return with an expected refund → fees withheld from refund.
    - Otherwise (invoice / QBO / entity bill, or TPG with balance due) → email invoice.
    """
    if tax_prep_fee is None:
        return ""

    amount_str = f"${tax_prep_fee:,.2f}"
    states = states or []

    if has_tpg_pages and _has_refund_amount(federal_amount, states):
        return (
            f" Tax prep fees ({amount_str}) will be deducted from your return "
            "when issued (third party banking fees apply)."
        )

    return (
        f" An invoice for tax prep fees ({amount_str}) will be sent to you via email. "
        "Tax returns will be submitted once the invoice has been paid."
    )


def build_refund_statement(
    federal_amount,
    states: list[dict],
    last4: str | None,
    mailing_address: str | None,
    bank_name: str | None = None,
) -> str:
    """
    Refund copy rules (only when a refund amount exists):
    - bank_name + last_4 → direct deposit.
    - else mailing_address → mail.
    - else omit.
    """
    if not _has_refund_amount(federal_amount, states):
        return ""

    if _has_banking_info(last4, bank_name):
        return (
            f" Applicable refunds will be direct deposited into your {bank_name.strip()} "
            f"account ending in {str(last4).strip()}."
        )

    if mailing_address:
        return (
            " Applicable refunds will be mailed to the following address "
            f"{mailing_address}."
        )

    return ""


def build_due_tax_statement(
    has_payment_voucher: bool,
    *,
    federal_amount=None,
    states: list[dict] | None = None,
) -> str:
    """
    Balance-due copy rules:
    - Payment-voucher packet present, or summary shows balance due → include pay instructions.
    - Otherwise omit.
    """
    states = states or []
    if not has_payment_voucher and not _has_balance_due(federal_amount, states):
        return ""

    return " Instructions to pay owed taxes may be found with your approval documents."


def build_message_context(parse_result) -> dict[str, Any]:
    # map from ParseResult / extracted fields to the context keys above

    extracted = parse_result.extracted_fields  # or similar

    federal_amount = extracted.get("federal_amount")
    states = extracted.get("states") or []
    last4 = extracted.get("last_4_of_account")
    bank_name = (extracted.get("bank_name") or "").strip() or None

    mailing_address = extracted.get("mailing_address")
    if not mailing_address:
        line1 = extracted.get("mailing_address_line1")
        city = extracted.get("mailing_city")
        state = extracted.get("mailing_state")
        zip_code = extracted.get("mailing_zip")
        parts = []
        if line1:
            parts.append(line1)
        city_state_zip = " ".join(p for p in [city, state, zip_code] if p)
        if city_state_zip:
            parts.append(city_state_zip)
        mailing_address = ", ".join(parts) if parts else None

    tax_prep_fee = extracted.get("tax_prep_fee")
    has_tpg_pages = bool(extracted.get("has_tpg_pages", False))
    has_payment_voucher = getattr(parse_result, "payment_voucher_packet_path", None) is not None

    tax_prep_fee_statement = build_tax_prep_fee_statement(
        has_tpg_pages,
        tax_prep_fee,
        federal_amount=federal_amount,
        states=states,
    )
    refund_statement = build_refund_statement(
        federal_amount, states, last4, mailing_address, bank_name=bank_name
    )
    due_tax_statement = build_due_tax_statement(
        has_payment_voucher,
        federal_amount=federal_amount,
        states=states,
    )

    return {
        "taxpayer_first_name": taxpayer_display_name(extracted),
        "tax_year": extracted.get("tax_year", ""),
        "federal_amount": federal_amount or 0,
        "states": states,
        "tax_prep_fee": tax_prep_fee,
        "has_tpg_pages": has_tpg_pages,
        "has_payment_voucher": has_payment_voucher,
        "last_4_of_account": last4,
        "bank_name": bank_name,
        "mailing_address": mailing_address,
        "tax_prep_fee_statement": tax_prep_fee_statement,
        "refund_statement": refund_statement,
        "due_tax_statement": due_tax_statement,
    }


def build_message(parse_result: Any, templates_dir: Path, template_key: str | None = None) -> str:
    context = build_message_context(parse_result)
    return render_message(templates_dir, template_key, context)
