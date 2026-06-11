"""
Parser ack hints — expected e-file transmissions for Review Complete (schema v1).

Priority: Client Letter e-file list → Diagnostic Summary state list → BILL_01 index.
"""
from __future__ import annotations

import re
from typing import Any

# Drake MEF form tokens commonly seen on Client Letter / BILL index rows.
_FORM_TOKEN_RE = re.compile(
    r"\b("
    r"1040(?:SR|NR|X)?|"
    r"1120(?:S|X|SX)?|"
    r"1065(?:X)?|"
    r"1041(?:X)?|"
    r"990(?:EZ|PF|T|X)?|"
    r"4868|7004|8868|"
    r"CA540(?:2EZ|NR|X)?|"
    r"[A-Z]{2}\d{3,4}[A-Z0-9]*|"
    r"HIN15|N15"
    r")\b",
    re.IGNORECASE,
)

_FEDERAL_FORMS = frozenset({
    "1040", "1040SR", "1040NR", "1040X",
    "1120", "1120S", "1120X", "1120SX",
    "1065", "1065X",
    "1041", "1041X",
    "990", "990EZ", "990PF", "990T", "990X",
    "4868", "7004", "8868",
})

# Not separate e-file transmissions (signatures, vouchers, worksheets).
_BILL_EXCLUDE_TOKENS = frozenset({
    "8879", "8879O", "1040V", "1040ES", "W2", "W2G", "1099",
    "TPG", "DDP", "DDPMT",
})

_STATE_NAME_TO_CODE = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}


def _normalize_form_token(raw: str, *, line: str = "") -> str | None:
    token = (raw or "").strip().upper().replace(" ", "")
    if not token:
        return None
    if token in {"540", "540NR", "5402EZ"} and "california" in line.lower():
        return f"CA{token}"
    if token in {"N15", "HIN15"} or token == "HI-N15":
        return "HIN15"
    if token.isdigit() and len(token) == 4 and token.startswith("104"):
        return token
    return token


def _jurisdiction_for_form(form_type: str) -> str:
    ft = form_type.upper()
    if ft in _FEDERAL_FORMS:
        return "federal"
    return "state"


def _transmission(form_type: str, *, source: str) -> dict[str, str]:
    ft = form_type.upper()
    return {
        "jurisdiction": _jurisdiction_for_form(ft),
        "form_type": ft,
        "source": source,
    }


_STATE_FORM_NUMBER_RE = re.compile(r"\b(\d{3,4}(?:2EZ|NR|X)?)\b", re.IGNORECASE)


def _state_form_from_line(line: str) -> str | None:
    line_lower = line.lower()
    for state_name, code in _STATE_NAME_TO_CODE.items():
        if state_name not in line_lower:
            continue
        for match in _STATE_FORM_NUMBER_RE.finditer(line):
            token = _normalize_form_token(match.group(1), line=line)
            if token:
                if token.isdigit() or (len(token) <= 4 and token[0].isdigit()):
                    return f"{code}{token.upper()}"
                if token.startswith(code):
                    return token.upper()
        return None
    return None


def _forms_on_line(line: str) -> list[str]:
    found: list[str] = []
    for match in _FORM_TOKEN_RE.finditer(line):
        normalized = _normalize_form_token(match.group(1), line=line)
        if normalized and normalized not in found:
            found.append(normalized)
    return found


def _extract_block(source: str, start_markers: tuple[str, ...], end_markers: tuple[str, ...]) -> str:
    lower = source.lower()
    start_idx = -1
    for marker in start_markers:
        idx = lower.find(marker)
        if idx != -1:
            start_idx = idx + len(marker)
            break
    if start_idx == -1:
        return ""

    end_idx = len(source)
    for marker in end_markers:
        idx = lower.find(marker, start_idx)
        if idx != -1:
            end_idx = min(end_idx, idx)
    return source[start_idx:end_idx]


def extract_efiled_transmissions_from_client_letter(text: str) -> list[dict[str, str]]:
    """Parse Client Letter 'following returns will be e-filed' section."""
    if not text:
        return []

    block = _extract_block(
        text,
        start_markers=(
            "the following returns will be e-filed",
            "following returns will be e-filed",
            "returns to be e-filed",
            "return type",
        ),
        end_markers=(
            "sign and date",
            "the following returns will be printed",
            "following returns will be printed",
            "please sign",
        ),
    )
    if not block.strip():
        return []

    transmissions: list[dict[str, str]] = []
    seen: set[str] = set()

    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) < 3:
            continue
        line_lower = stripped.lower()
        if any(
            skip in line_lower
            for skip in ("return type", "form type", "form name", "transaction method")
        ):
            continue

        forms = _forms_on_line(stripped)
        if not forms and "federal" in line_lower:
            forms = ["1040"]
        if not forms:
            state_form = _state_form_from_line(stripped)
            if state_form:
                forms = [state_form]

        for form_type in forms:
            key = form_type.upper()
            if key in seen:
                continue
            seen.add(key)
            transmissions.append(_transmission(form_type, source="client_letter"))

    return transmissions


def extract_state_filings_from_diagnostic(text: str) -> list[dict[str, str]]:
    """Supplement transmissions from Diagnostic Summary state return list."""
    if not text:
        return []

    block = _extract_block(
        text,
        start_markers=(
            "state return",
            "state returns",
            "state filing",
            "state filings",
        ),
        end_markers=(
            "federal return",
            "return information",
            "comparison",
            "invoice",
        ),
    )
    if not block.strip():
        block = text

    transmissions: list[dict[str, str]] = []
    seen: set[str] = set()

    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        forms = _forms_on_line(stripped)
        for form_type in forms:
            if _jurisdiction_for_form(form_type) != "state":
                continue
            key = form_type.upper()
            if key in seen:
                continue
            seen.add(key)
            transmissions.append(_transmission(form_type, source="diagnostic"))

    return transmissions


def extract_transmissions_from_bill(text: str) -> list[dict[str, str]]:
    """Fallback count from BILL_01 form index (pages 1–2)."""
    if not text:
        return []

    transmissions: list[dict[str, str]] = []
    seen: set[str] = set()

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        forms = _forms_on_line(stripped)
        for form_type in forms:
            key = form_type.upper()
            if key in _BILL_EXCLUDE_TOKENS:
                continue
            if key in _FEDERAL_FORMS or _jurisdiction_for_form(key) == "state":
                if key in seen:
                    continue
                seen.add(key)
                transmissions.append(_transmission(form_type, source="bill"))

    return transmissions


def merge_expected_transmissions(
    *sources: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Merge by form_type; earlier sources win on jurisdiction metadata."""
    merged: dict[str, dict[str, str]] = {}
    for source_list in sources:
        for item in source_list:
            form_type = (item.get("form_type") or "").upper()
            if not form_type:
                continue
            if form_type not in merged:
                merged[form_type] = {
                    "jurisdiction": item.get("jurisdiction") or _jurisdiction_for_form(form_type),
                    "form_type": form_type,
                    "source": item.get("source") or "unknown",
                }
    return sorted(merged.values(), key=lambda x: (x["jurisdiction"], x["form_type"]))


def apply_ack_hints(
    out: dict[str, Any],
    *,
    client_letter_text: str = "",
    diagnostic_text: str = "",
    bill_text: str = "",
) -> dict[str, Any]:
    """Compute expected_transmissions + expected_ack_count into *out*."""
    letter_tx = extract_efiled_transmissions_from_client_letter(client_letter_text)
    diagnostic_tx = extract_state_filings_from_diagnostic(diagnostic_text)
    bill_tx = extract_transmissions_from_bill(bill_text)

    if letter_tx:
        merged = merge_expected_transmissions(letter_tx, diagnostic_tx)
        primary_source = "client_letter"
    elif diagnostic_tx:
        merged = merge_expected_transmissions(diagnostic_tx, bill_tx)
        primary_source = "diagnostic"
    elif bill_tx:
        merged = bill_tx
        primary_source = "bill"
    else:
        merged = []
        primary_source = ""

    if merged:
        out["expected_transmissions"] = merged
        out["expected_ack_count"] = len(merged)
        out["expected_ack_source"] = primary_source
    return out
