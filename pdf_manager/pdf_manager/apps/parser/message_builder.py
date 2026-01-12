from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape


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
def build_tax_prep_fee_statement(has_tpg_pages: bool, tax_prep_fee) -> str:
    # Option 1 : No tax prep fee
    if tax_prep_fee is None:
        return ""

    amount_str = f"${tax_prep_fee:,.2f}"

    # Option 2 : TPG
    if has_tpg_pages:
        return (
            f" Tax prep fees ({amount_str}) will be deducted from your return "
            "when issued (third party banking fees apply)."
        )
    # Option 3 : Invoice
    else:
        return (
            f" An invoice for tax prep fees ({amount_str}) will be sent to you via email. "
            "Tax returns will be submitted once the invoice has been paid."
        )


def build_refund_statement(
    federal_amount,
    states: list[dict],
    last4: str | None,
    mailing_address: str | None,
) -> str:
    amounts = [federal_amount] + [s["amount"] for s in states]
    has_refund = any(a is not None and a > 0 for a in amounts)
    all_negative_or_zero = all(a is None or a <= 0 for a in amounts)

    # Option 1 : No refund
    if all_negative_or_zero:
        return ""

    # Option 2 : No refund ($0 balance and -$ balance)
    if not has_refund:
        return ""

    # Option 3 : At least one refund
    if last4:
        return (
            f" Applicable refunds will be direct deposited into the account ending in " f" {last4}."
        )

    # Option 4 : Refund is mailed to tax payer
    return " Applicable refunds will be mailed to the following address " f"{mailing_address}."

    # Option 5 Placeholder for printed refund in office
    # return ""


def build_due_tax_statement(has_payment_voucher: bool) -> str:
    if not has_payment_voucher:
        return ""

    return " Instructions to pay owed taxes may be found with your approval documents."


def build_message_context(parse_result) -> dict[str, Any]:
    # map from ParseResult / extracted fields to the context keys above

    extracted = parse_result.extracted_fields  # or similar

    federal_amount = extracted.get("federal_amount")
    states = extracted.get("states") or []
    last4 = extracted.get("last_4_of_account")

    mailing_address = extracted.get("mailing_address")
    if not mailing_address:
        line1 = extracted.get("Mailing_address_line1")
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

    tax_prep_fee_statement = build_tax_prep_fee_statement(has_tpg_pages, tax_prep_fee)
    refund_statement = build_refund_statement(federal_amount, states, last4, mailing_address)
    due_tax_statement = build_due_tax_statement(has_payment_voucher)

    return {
        "taxpayer_first_name": extracted.get("taxpayer_first_name", ""),
        "tax_year": extracted.get("tax_year", ""),
        "federal_amount": federal_amount or 0,
        "states": states,
        "tax_prep_fee": tax_prep_fee,
        "has_tpg_pages": has_tpg_pages,
        "has_payment_voucher": has_payment_voucher,
        "last_4_of_account": last4,
        "mailing_address": mailing_address,
        "tax_prep_fee_statement": tax_prep_fee_statement,
        "refund_statement": refund_statement,
        "due_tax_statement": due_tax_statement,
    }


def build_message(parse_result: Any, templates_dir: Path, template_key: str | None = None) -> str:
    context = build_message_context(parse_result)
    return render_message(templates_dir, template_key, context)
