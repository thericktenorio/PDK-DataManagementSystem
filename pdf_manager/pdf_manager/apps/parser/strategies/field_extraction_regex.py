"""
NOTE : FIELD EXTRACTOR
Purpose :
 - Extract targeted fields from pdf
Techniques :
 - System uses PyMuPDF or tesseract OCR
Requirements :
 - PyMuPDF default field extractor
    - non empty
    - 30 or more characters
    - alphanumeric content
 - OCR secondary field extractor
    - must return a minimum string length ('min_text_length')
 - Returns empty string if requirements not met
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from django.conf import settings

from pdf_manager.apps.parser.ack_hints import apply_ack_hints
from pdf_manager.apps.parser.drake_registry import load_drake_registry
from pdf_manager.apps.parser.enrollment_signals import build_enrollment_signals
from pdf_manager.apps.parser.extraction_schema import finalize_extracted_fields
from pdf_manager.apps.parser.ocr.ocr_engine import OCREngine, build_ocr_config_from_settings
from pdf_manager.apps.parser.strategies.field_extraction_base import FieldExtractionStrategy
from pdf_manager.apps.parser.types import TaggedPage, Template

# Try to import PyMuPDF (fitz). If unavailable, fail fast for this strategy
try:
    import fitz  # PyMuPDF
except Exception as exc:
    fitz = None
    _IMPORT_ERROR: Exception | None = exc
else:
    _IMPORT_ERROR = None


# -----------------------------
# ------- REGEX HELPERS -------
# -----------------------------
_CURRENCY_RE = re.compile(r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})|[0-9]+(?:\.[0-9]{2}))")
_DATE_RE = re.compile(r"\b([0-1]?\d)/([0-3]?\d)/((?:20)?\d{2})\b")
# Heuristics for tax-specific data on Client Letter / Bill pages
TAX_YEAR_RE = re.compile(r"\b(20\d{2})\b", re.IGNORECASE)
ACCOUNT_LAST4_RE = re.compile(
    r"(?:account\s+ending\s+in|ending\s+in)\s*([0-9]{4})",
    re.IGNORECASE,
)
TPG_RE = re.compile(r"\bTPG\b|\bTax Products Group\b", re.IGNORECASE)
CITY_STATE_ZIP_RE = re.compile(
    r"^(?P<city>.+?),?\s+(?P<state>[A-Z]{2})\s+(?P<zip>\d{5}(?:-\d{4})?)$"
)

STATE_NAME_TO_CODE = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "Florida": "FL",
    "Georgia": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
    "District of Columbia": "DC",
}

_AGENCY_REMITTANCE_MARKERS = (
    "internal revenue service",
    "franchise tax board",
    "department of the treasury",
    "department of revenue",
)

_MONTH_NAME_PATTERN = re.compile(
    r"\b("
    r"January|February|March|April|May|June|July|August|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
    r")\b",
    re.IGNORECASE,
)

_FIRM_HEADER_MARKERS = (
    "pdk entrust",
    "info@",
    "phone:",
    "fax:",
)


# --------------------------------
# ----- OUTLINE BASE HELPERS -----
# --------------------------------
CLIENT_LETTER_SECTION_KEYS: tuple[str, ...] = ("CLIENT_LETTER",)
CLIENT_LETTER_TITLE_KEYWORDS: tuple[str, ...] = ("client letter",)

BILL_SECTION_KEYS: tuple[str, ...] = ("BILL_01",)
BILL_TITLE_KEYWORDS: tuple[str, ...] = ("bill 01", "bill_01")


def _normalize_amount(raw: str) -> str:
    v = raw.replace("$", "").replace(",", "").strip()
    return f"{float(v)}"


def _normalize_date(m: re.Match[str]) -> str:
    mm, dd, yy = m.group(1), m.group(2), m.group(3)
    if len(yy) == 2:
        yy = "20" + yy  # naive pivot for MVP
    dt = datetime(int(yy), int(mm), int(dd))
    return dt.strftime("%Y-%m-%d")


def _page_role(tp: TaggedPage) -> str:
    if not tp.tags:
        return ""
    return str(tp.tags[0].label)


def _is_client_letter_page(tp: TaggedPage) -> bool:
    return _page_role(tp) == "extract_client_letter"


def _is_bill_page(tp: TaggedPage) -> bool:
    return _page_role(tp) == "extract_bill"


def _is_tpg_fee_page(tp: TaggedPage) -> bool:
    return _page_role(tp) == "extract_tpg_fee"


def _is_diagnostic_invoice_page(tp: TaggedPage) -> bool:
    return _page_role(tp) == "extract_diagnostic_invoice"


def _is_bill_fee_page(tp: TaggedPage) -> bool:
    return _page_role(tp) == "extract_bill_fee"


def _is_tin_comparison_page(tp: TaggedPage) -> bool:
    return _page_role(tp) == "extract_tin_comparison"


def _is_bank_deposit_page(tp: TaggedPage) -> bool:
    """DD_PMT / Account Transaction Summary — customer refund deposit details."""
    title = (getattr(tp.outline, "title", "") or "")
    upper = title.upper()
    if "DD_PMT" in upper:
        return True
    return title.strip().lower() == "account transaction summary"


def _extract_customer_bank_from_dd_pmt(text: str) -> dict[str, Any]:
    """
    Parse taxpayer bank name and account last-4 from Drake DD_PMT / bank product pages.
    Prefers the block after 'customer's chosen bank account' (not the TPG routing account).
    """
    out: dict[str, Any] = {}
    if not text or not text.strip():
        return out

    section = text
    lower = text.lower()
    marker = "customer's chosen bank account"
    idx = lower.find(marker)
    if idx != -1:
        section = text[idx:]
    else:
        acct2 = lower.find("account #2")
        if acct2 != -1:
            section = text[acct2:]

    inst_match = re.search(
        r"Financial\s+Institution\s*\n\s*([^\n]+?)\s*\n\s*Routing\s+Transit\s+Number",
        section,
        re.IGNORECASE,
    )
    acct_match = re.search(
        r"Account\s+Number\s*\n\s*([0-9X*]+)",
        section,
        re.IGNORECASE,
    )

    if inst_match:
        bank = inst_match.group(1).strip()
        if bank and "green dot" not in bank.lower():
            out["bank_name"] = bank

    if acct_match:
        digits = re.sub(r"\D", "", acct_match.group(1))
        if len(digits) >= 4:
            out["last_4_of_account"] = digits[-4:]

    return out


def _is_tin_1040_page(tp: TaggedPage) -> bool:
    """First Form 1040 page (outline title exactly ``1040``) — packet stays form_federal."""
    if _page_role(tp) != "form_federal":
        return False
    title = (tp.outline.title or "") if tp.outline else ""
    return title.strip() == "1040"


def _parser_debug_enabled() -> bool:
    return bool(getattr(settings, "PARSER_DEBUG", False))


def _extract_tax_year(source: str) -> str | None:
    """
    Extract the filing tax year from the client letter text.

    Priority:
      1. 'tax year 20xx'
      2. '20xx tax year'
      3. 'tax return 20xx'
      4. '20xx tax return'
      5. First standalone 20xx that is NOT part of an mm/dd/yyyy date.
    """
    text = source

    # 1) 'tax year 20xx'
    m = re.search(r"tax\s+year[^\d]*(20\d{2})", text, re.IGNORECASE)
    if m:
        return m.group(1)

    # 2) '20xx tax year'
    m = re.search(r"(20\d{2})[^\n]*tax\s+year", text, re.IGNORECASE)
    if m:
        return m.group(1)

    # 3) 'tax return 20xx'
    m = re.search(r"tax\s+return[^\d]*(20\d{2})", text, re.IGNORECASE)
    if m:
        return m.group(1)

    # 4) '20xx tax return'
    m = re.search(r"(20\d{2})[^\n]*tax\s+return", text, re.IGNORECASE)
    if m:
        return m.group(1)

    # 5) Standalone years not part of mm/dd/yyyy dates
    years_in_dates = {match.group(3) for match in _DATE_RE.finditer(text)}

    for m in TAX_YEAR_RE.finditer(text):
        year = m.group(1)
        if year not in years_in_dates:
            return year

    return None


def _parse_table_amount(line: str) -> int | None:
    """
    Parse a monetary amount from a summary-table line, returning an *integer dollar* value.

    Strategy:
      - Strip everything but digits.
      - Interpret the remaining digits as a whole-dollar amount.
        Example OCRs:
          "3,792.00" -> "379200" or "3792"  -> 379200 or 3792 -> treat as 3792 dollars
          "2,417"    -> "2417"              -> 2417 dollars

    Assumptions:
      - Drake's summary letter prints whole dollars (cents are always .00 or absent).
      - If OCR collapses "3,792.00" to "3792", we still want 3792 (not 37.92).
    """
    digits = re.sub(r"\D", "", line)
    if not digits:
        return None

    try:
        return int(digits)
    except ValueError:
        return None


def _extract_summary_table(source: str) -> tuple[float | None, list[dict[str, Any]]]:
    """
    Extract federal and state amounts from the client letter summary table.

    OCR-tolerant, line-based heuristic:

      1) Find the block of text starting at the summary header:
           "Refund/Balance Due Transaction Method"
         and ending before the next narrative section
           ("The following returns", "Sign and date", etc.), or EOF.

      2) Within that block, scan lines that look like tax rows:
           - contain "income tax"
           - and contain "refund" or "balance due" or "amount you owe"

         For each such line:
           - determine the jurisdiction: "Federal" or a state name
           - parse a robust amount using _parse_table_amount()
           - sign convention:
               * Refund        -> +amount
               * Balance Due /
                 Amount You Owe -> -amount

      3) Aggregate into:
           - federal_amount_val (float | None)
           - states: list[{"state": "CA", "amount": float}]
    """
    text_lower = source.lower()

    # 1) Locate the start of the summary table block
    header_variants = [
        "refund/balance due transaction method",
        "refund / balance due transaction method",
        "refund/ balance due transaction method",
        "refund /balance due transaction method",
    ]
    start_idx = -1
    for hv in header_variants:
        start_idx = text_lower.find(hv)
        if start_idx != -1:
            break

    if start_idx == -1:
        # No summary table header found
        return None, []

    # 2) Determine the end of the table block
    end_markers = [
        "the following returns will be e-filed",
        "the following returns will be printed",
        "sign and date",
    ]
    end_idx_candidates = [
        idx for marker in end_markers if (idx := text_lower.find(marker, start_idx)) != -1
    ]
    end_idx = min(end_idx_candidates) if end_idx_candidates else len(source)

    table_block = source[start_idx:end_idx]

    lines = [ln.strip() for ln in table_block.splitlines() if ln.strip()]

    federal_amount_val: float | None = None
    state_totals: defaultdict[str, int] = defaultdict(int)

    for line in lines:
        line_lower = line.lower()

        # Must look like a summary row
        if "income tax" not in line_lower:
            continue

        is_refund = "refund" in line_lower
        is_balance = "balance due" in line_lower or "amount you owe" in line_lower

        if not (is_refund or is_balance):
            continue

        # Parse the amount with OCR-robust helper
        amt_val = _parse_table_amount(line)
        if amt_val is None:
            continue

        if is_balance:
            amt_val = -amt_val

        # Determine jurisdiction: Federal vs state
        if "federal" in line_lower:
            federal_amount_val = amt_val
            continue

        # Try to match a state name in the line
        for state_name, code in STATE_NAME_TO_CODE.items():
            if state_name.lower() in line_lower:
                if code:
                    state_totals[code] += amt_val
                break

    # Build states list
    states: list[dict[str, Any]] = []
    for code, total in state_totals.items():
        if total == 0:
            continue
        states.append({"state": code, "amount": total})

    states.sort(key=lambda s: s["state"])
    return federal_amount_val, states


def _client_letter_date_line_index(lines: list[str]) -> int:
    for idx, line in enumerate(lines):
        if _MONTH_NAME_PATTERN.search(line):
            return idx
        if re.search(r"\bBelow is a summary\b", line, re.IGNORECASE):
            return idx
    return 0


def _is_agency_remittance_block(lines: list[str], city_line_idx: int) -> bool:
    start = max(city_line_idx - 3, 0)
    block = "\n".join(lines[start : city_line_idx + 1]).lower()
    return any(marker in block for marker in _AGENCY_REMITTANCE_MARKERS)


def _name_line_for_address(lines: list[str], city_line_idx: int) -> str | None:
    if city_line_idx < 2:
        return None
    name_line = lines[city_line_idx - 2].strip()
    if name_line.endswith(":"):
        if city_line_idx >= 3:
            name_line = lines[city_line_idx - 3].strip()
        else:
            return None
    if not name_line or any(marker in name_line.lower() for marker in _FIRM_HEADER_MARKERS):
        return None
    return name_line


def _looks_like_entity_name(name_line: str) -> bool:
    from pdf_manager.apps.parser.extraction_schema import looks_like_entity_name

    return looks_like_entity_name(name_line)


def _populate_name_fields(result: dict[str, Any], name_line: str, *, street: str | None, city: str, state: str, zip_code: str) -> None:
    full_name = name_line.title()
    result["taxpayer_full_name"] = full_name

    if _looks_like_entity_name(name_line):
        result["taxpayer_first_name"] = full_name
        result["taxpayer_is_entity"] = True
    else:
        primary_segment = name_line
        if "&" in name_line:
            primary_segment = name_line.split("&", 1)[0].strip()
        elif " and " in name_line.lower():
            primary_segment = re.split(r"\band\b", name_line, flags=re.IGNORECASE)[0].strip()

        tokens = primary_segment.split()
        if tokens:
            result["taxpayer_first_name"] = tokens[0].title()

    if street:
        result["mailing_address_line1"] = street

    result["mailing_city"] = city
    result["mailing_state"] = state
    result["mailing_zip"] = zip_code

    address_parts = []
    if street:
        address_parts.append(street)
    city_state_zip = " ".join(part for part in [city, state, zip_code] if part)
    if city_state_zip:
        address_parts.append(city_state_zip)
    if address_parts:
        result["mailing_address"] = ", ".join(address_parts)


def _extract_name_and_address_from_client_letter(source: str) -> dict[str, Any]:
    """
    Extract taxpayer name/address from Client Letter OCR text.

    Uses the first post-date CITY/ST/ZIP block, skipping firm header and
    tax-agency remittance addresses (IRS / FTB PO boxes).
    """
    result: dict[str, Any] = {}
    lines = [ln.strip() for ln in source.splitlines() if ln.strip()]

    if not lines:
        return result

    candidates: list[tuple[int, re.Match[str]]] = []
    for idx, line in enumerate(lines):
        m = CITY_STATE_ZIP_RE.match(line)
        if m:
            candidates.append((idx, m))

    if not candidates:
        return result

    date_line_idx = _client_letter_date_line_index(lines)

    for chosen_idx, chosen_match in candidates:
        if chosen_idx < date_line_idx:
            continue
        if _is_agency_remittance_block(lines, chosen_idx):
            continue

        name_line = _name_line_for_address(lines, chosen_idx)
        if not name_line:
            continue

        street = lines[chosen_idx - 1].strip() if chosen_idx >= 1 else None
        _populate_name_fields(
            result,
            name_line,
            street=street,
            city=chosen_match.group("city").strip(),
            state=chosen_match.group("state").strip(),
            zip_code=chosen_match.group("zip").strip(),
        )
        break

    return result


def _extract_name_from_embedded_fallback(text: str, *, source: str) -> dict[str, Any]:
    """Fast fallback from Drake Notes or FILEINST embedded text."""
    result: dict[str, Any] = {}
    name_line: str | None = None
    if source == "fileinst":
        match = re.search(
            r"Filing Instructions\s+(.+?)(?:\n|Form filed:)",
            text,
            re.IGNORECASE,
        )
        if match:
            name_line = match.group(1).strip()
    elif source == "notes":
        match = re.search(
            r"Name\(s\)\s+as\s+shown\s+on\s+return[^\n]*\n(?:[^\n]*\n){0,3}([A-Z][A-Z0-9 &'\-]+)",
            text,
            re.IGNORECASE,
        )
        if match:
            name_line = match.group(1).strip()

    if not name_line or any(m in name_line.lower() for m in _AGENCY_REMITTANCE_MARKERS):
        return result

    full_name = name_line.title()
    result["taxpayer_full_name"] = full_name
    if _looks_like_entity_name(name_line):
        result["taxpayer_first_name"] = full_name
        result["taxpayer_is_entity"] = True
    else:
        primary_segment = name_line.split("&", 1)[0].strip() if "&" in name_line else name_line
        tokens = primary_segment.split()
        if tokens:
            result["taxpayer_first_name"] = tokens[0].title()
    return result


def _parse_currency_amount(raw: str) -> float | None:
    cleaned = raw.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_tpg_info_fee(text: str) -> float | None:
    match = re.search(r"PDK\s+ENTRUST\s*\n\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
    if match:
        return _parse_currency_amount(match.group(1))
    return None


def _extract_diagnostic_invoice_fee(text: str) -> float | None:
    if "Invoice" not in text:
        return None

    lines = [ln.strip() for ln in text.splitlines()]
    preparer_idx = next((i for i, line in enumerate(lines) if line.startswith("Preparer")), None)
    if preparer_idx is not None:
        for line in lines[preparer_idx + 1 : preparer_idx + 15]:
            amount_match = re.match(r"^\$?\s*([\d,]+\.\d{2})\s*$", line)
            if amount_match:
                return _parse_currency_amount(amount_match.group(1))

    dollar_matches = re.findall(r"^\s*\$([\d,]+\.\d{2})\s*$", text, re.MULTILINE)
    if len(dollar_matches) == 1:
        return _parse_currency_amount(dollar_matches[0])
    return None


def _extract_bill_page2_fee(text: str) -> float | None:
    for pattern in (
        r"(?:Total\s+Balance\s+Due|(?:Lo\s+)?Fotal\s+Balance\s+Due|Forms\s+Subtotal)"
        r"[^\d\n]*([\d,]+\.\d{2})",
        r"Payment due upon receipt[^\d]*([\d,]+\.\d{2})",
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount = _parse_currency_amount(match.group(1))
            if amount is not None:
                return amount
    return None


_TIN_SSN_RE = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")
_TIN_EIN_RE = re.compile(r"\b(\d{2})-(\d{7})\b")


def _normalize_tin_value(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 9 and digits.isdigit():
        return digits
    return None


def _first_tin_in_text(text: str, *, start: int = 0) -> str | None:
    for pattern in (_TIN_SSN_RE, _TIN_EIN_RE):
        match = pattern.search(text, start)
        if match:
            normalized = _normalize_tin_value(match.group(0))
            if normalized:
                return normalized
    return None


def _extract_tin_from_diagnostic(text: str) -> str | None:
    """Primary taxpayer TIN from Diagnostic Summary (SSN or entity EIN)."""
    ein_match = re.search(
        r"Employer\s+Identification\s*#?\s*(?:\n[^\n]*){0,2}\n\s*(\d{2}-\d{7})\b",
        text,
        re.IGNORECASE,
    )
    if ein_match:
        return _normalize_tin_value(ein_match.group(1))

    marker = re.search(r"Taxpayer\s+Tax\s+ID\s+Number", text, re.IGNORECASE)
    if marker:
        return _first_tin_in_text(text, start=marker.end())
    return None


def _extract_tin_from_comparison(text: str) -> str | None:
    """Primary taxpayer TIN from Comparison footer (joint returns: first SSN)."""
    if "TAX RETURN COMPARISON" not in text.upper() and "Identifying number" not in text:
        return None

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for idx, line in enumerate(lines):
        if not (_TIN_SSN_RE.fullmatch(line) or _TIN_EIN_RE.fullmatch(line)):
            continue
        if idx == 0:
            continue
        prev = lines[idx - 1]
        if re.search(r"[A-Za-z]", prev) and not prev.startswith("."):
            return _normalize_tin_value(line)

    marker = re.search(r"Identifying\s+number", text, re.IGNORECASE)
    if marker:
        return _first_tin_in_text(text, start=marker.end())
    return None


def _extract_tin_from_1040(text: str) -> str | None:
    """Fallback: first taxpayer SSN on Form 1040 page 1."""
    if "1040" not in text and "Individual Income Tax Return" not in text:
        return None
    return _first_tin_in_text(text)


def _extract_taxpayer_tin(
    *,
    diagnostic_text: str,
    comparison_text: str,
    form_1040_text: str,
) -> tuple[str | None, str | None]:
    """Priority: Diagnostic Summary → Comparison → 1040 page 1."""
    if diagnostic_text:
        tin = _extract_tin_from_diagnostic(diagnostic_text)
        if tin:
            return tin, "extract_diagnostic_invoice"

    if comparison_text:
        tin = _extract_tin_from_comparison(comparison_text)
        if tin:
            return tin, "extract_tin_comparison"

    if form_1040_text:
        tin = _extract_tin_from_1040(form_1040_text)
        if tin:
            return tin, "form_federal"

    return None, None


def _extract_tax_prep_fee(
    *,
    tpg_text: str,
    diagnostic_text: str,
    bill_fee_text: str,
) -> tuple[float | None, str | None]:
    """Priority: TPG_INFO → Diagnostic Summary → BILL_01 page 2."""
    if tpg_text:
        fee = _extract_tpg_info_fee(tpg_text)
        if fee is not None:
            return fee, "extract_tpg_fee"

    if diagnostic_text:
        fee = _extract_diagnostic_invoice_fee(diagnostic_text)
        if fee is not None:
            return fee, "extract_diagnostic_invoice"

    if bill_fee_text:
        fee = _extract_bill_page2_fee(bill_fee_text)
        if fee is not None:
            return fee, "extract_bill_fee"

    return None, None


def _get_pdf_source_path(pages: list[TaggedPage]) -> Path:
    """
    Determine the underlying PDF file path for this parse job

    Assume all TaggedPage objects refer to the same original PDF
    look for either:
    - tp.source_path
    - tp.page.source_path
    """
    for tp in pages:
        page = tp.page
        path = getattr(page, "source_path", None)
        if path:
            return path

    raise RuntimeError(
        "Unable to determine PDF source path for PyMuPDF extraction. "
        "Ensure TaggedPage or its `page` object exposes a `source_path` attribute."
    )


# -------------------------------
# Determine to use PyMuPDF or OCR
# -------------------------------
def _has_meaningful_text(text: str, min_length: int = 30) -> bool:
    """
    Heuristic to decide to use PyMuPDF or OCR

    For OCR-0 keep this simple:
    - non-empty
    - above a small length threshold
    - contains at least one alphabetic character
    """
    if not text:
        return False
    stripped = text.strip()
    if len(stripped) < min_length:
        return False

    return any(ch.isalpha() for ch in stripped)


def _run_extraction(
    pages: list[TaggedPage],
    template: Template,
    text_getter: Callable[[TaggedPage], str],
) -> dict[str, Any]:
    """Extract clearing fields from classified source pages."""
    client_letter_pages = [tp for tp in pages if _is_client_letter_page(tp)]
    tpg_fee_pages = [tp for tp in pages if _is_tpg_fee_page(tp)]
    diagnostic_pages = [tp for tp in pages if _is_diagnostic_invoice_page(tp)]
    bill_pages = [tp for tp in pages if _is_bill_page(tp)]
    bill_fee_pages = [tp for tp in pages if _is_bill_fee_page(tp)]
    comparison_pages = [tp for tp in pages if _is_tin_comparison_page(tp)]
    tin_1040_pages = [tp for tp in pages if _is_tin_1040_page(tp)]
    bank_deposit_pages = [tp for tp in pages if _is_bank_deposit_page(tp)]

    client_letter_text = text_getter(client_letter_pages[0]) if client_letter_pages else ""
    tpg_fee_text = text_getter(tpg_fee_pages[0]) if tpg_fee_pages else ""
    diagnostic_text = text_getter(diagnostic_pages[0]) if diagnostic_pages else ""
    bill_fee_text = text_getter(bill_fee_pages[0]) if bill_fee_pages else ""
    bill_text_parts = [text_getter(tp) for tp in bill_pages]
    if bill_fee_pages and (not bill_pages or bill_fee_pages[0].index != bill_pages[0].index):
        bill_text_parts.append(bill_fee_text)
    bill_text = "\n".join(part for part in bill_text_parts if part)
    comparison_text = text_getter(comparison_pages[0]) if comparison_pages else ""
    form_1040_text = text_getter(tin_1040_pages[0]) if tin_1040_pages else ""
    bank_deposit_text = text_getter(bank_deposit_pages[0]) if bank_deposit_pages else ""

    out: dict[str, Any] = {}
    if _parser_debug_enabled():
        out.update(
            {
                "__debug_page_count": len(pages),
                "__debug_client_letter_indices": [tp.index for tp in client_letter_pages],
                "__debug_tpg_fee_indices": [tp.index for tp in tpg_fee_pages],
                "__debug_diagnostic_indices": [tp.index for tp in diagnostic_pages],
                "__debug_bill_fee_indices": [tp.index for tp in bill_fee_pages],
            }
        )
        if client_letter_text:
            out["__debug_client_letter_snippet"] = client_letter_text[:300]
            out["__debug_client_letter_full"] = client_letter_text[:4000]

    source_for_letter = client_letter_text

    tax_year = _extract_tax_year(source_for_letter)
    if tax_year:
        out["tax_year"] = tax_year

    if client_letter_text:
        out.update(_extract_name_and_address_from_client_letter(client_letter_text))

    m_last4 = ACCOUNT_LAST4_RE.search(source_for_letter)
    if m_last4:
        out["last_4_of_account"] = m_last4.group(1)

    if bank_deposit_text:
        bank_fields = _extract_customer_bank_from_dd_pmt(bank_deposit_text)
        if bank_fields.get("bank_name"):
            out["bank_name"] = bank_fields["bank_name"]
        if bank_fields.get("last_4_of_account") and "last_4_of_account" not in out:
            out["last_4_of_account"] = bank_fields["last_4_of_account"]
            out["_last_4_role"] = "extract_dd_pmt"

    federal_amount_val, states = _extract_summary_table(source_for_letter)
    if federal_amount_val is not None:
        out["federal_amount"] = federal_amount_val
    if states:
        out["states"] = states

    fee, fee_role = _extract_tax_prep_fee(
        tpg_text=tpg_fee_text,
        diagnostic_text=diagnostic_text,
        bill_fee_text=bill_fee_text,
    )
    if fee is not None and fee_role:
        out["tax_prep_fee"] = fee
        out["_tax_prep_fee_role"] = fee_role

    tin, tin_role = _extract_taxpayer_tin(
        diagnostic_text=diagnostic_text,
        comparison_text=comparison_text,
        form_1040_text=form_1040_text,
    )
    if tin and tin_role:
        out["taxpayer_tin"] = tin
        out["_taxpayer_tin_role"] = tin_role

    if diagnostic_text and re.search(r"Employer\s+Identification", diagnostic_text, re.IGNORECASE):
        out["taxpayer_is_entity"] = True
        full = (out.get("taxpayer_full_name") or "").strip()
        if full:
            out["taxpayer_first_name"] = full

    has_tpg = bool(tpg_fee_pages) or any(
        "tpg" in (getattr(tp.outline, "title", "") or "").lower()
        for tp in pages
        if tp.outline
    )
    out["has_tpg_pages"] = has_tpg

    out["enrollment_signals"] = build_enrollment_signals(
        pages=pages,
        comparison_text=comparison_text,
        diagnostic_text=diagnostic_text,
        has_tpg_pages=has_tpg,
    )

    apply_ack_hints(
        out,
        client_letter_text=client_letter_text,
        diagnostic_text=diagnostic_text,
        bill_text=bill_text,
    )

    return out


class RegexFieldExtraction(FieldExtractionStrategy):
    name = "regex"

    def extract(self, pages: list[TaggedPage], template: Template) -> dict[str, Any]:
        """
        Use PyMuPDF for all text extraction within this strategy

        Requirements:
        - PyMuPDF (pymupdf) must be installed
        - Each TaggedPage (or its underlying .page) must expose:
            * .index -> 0-based index in the original PDF
            * .source_path OR .page.source_path -> path to the PDF file
        """
        if fitz is None or _IMPORT_ERROR is not None:
            raise RuntimeError(
                "PyMuPDF (pymupdf) is not available but is required for RegexFieldExtraction. "
                "Install it via requirements.txt / constraints.txt and rebuild your environment."
            ) from _IMPORT_ERROR

        if not pages:
            return {}

        registry = load_drake_registry()
        pdf_path = _get_pdf_source_path(pages)
        doc = fitz.open(str(pdf_path))

        ocr_config = build_ocr_config_from_settings()
        ocr_engine = OCREngine(ocr_config)
        ocr_enabled = bool(getattr(settings, "OCR_ENABLED", True))
        pymupdf_min_length = int(getattr(settings, "OCR_PYMUPDF_MIN_LENGTH", 30))

        extract_targets: list[TaggedPage] = []
        client_letters = [tp for tp in pages if _is_client_letter_page(tp)]
        tpg_fee_pages = [tp for tp in pages if _is_tpg_fee_page(tp)]
        diagnostic_pages = [tp for tp in pages if _is_diagnostic_invoice_page(tp)]
        bill_fee_pages = [tp for tp in pages if _is_bill_fee_page(tp)]
        bill_pages = [tp for tp in pages if _is_bill_page(tp)]
        comparison_pages = [tp for tp in pages if _is_tin_comparison_page(tp)]
        tin_1040_pages = [tp for tp in pages if _is_tin_1040_page(tp)]
        bank_deposit_pages = [tp for tp in pages if _is_bank_deposit_page(tp)]

        if client_letters:
            extract_targets.append(client_letters[0])
        if tpg_fee_pages:
            extract_targets.append(tpg_fee_pages[0])
        if diagnostic_pages:
            extract_targets.append(diagnostic_pages[0])
        if bill_fee_pages:
            extract_targets.append(bill_fee_pages[0])
        if bill_pages and (not bill_fee_pages or bill_pages[0].index != bill_fee_pages[0].index):
            extract_targets.append(bill_pages[0])
        if comparison_pages:
            extract_targets.append(comparison_pages[0])
        if tin_1040_pages:
            extract_targets.append(tin_1040_pages[0])
        if bank_deposit_pages:
            extract_targets.append(bank_deposit_pages[0])

        target_indices = {tp.index for tp in extract_targets}

        ocr_attempted_indices: set[int] = set()
        ocr_success_indices: set[int] = set()
        ocr_total_seconds = 0.0
        text_cache: dict[int, str] = {}
        page_methods: dict[int, str] = {}

        try:
            for tp in extract_targets:
                page_index = tp.index
                role = _page_role(tp)
                try:
                    pymupdf_text = doc[page_index].get_text("text") or ""
                except Exception:
                    pymupdf_text = ""

                text = pymupdf_text
                method = "pymupdf"
                has_good_text = _has_meaningful_text(pymupdf_text, min_length=pymupdf_min_length)
                needs_ocr = (
                    ocr_enabled
                    and registry.ocr_required_if_no_text(role)
                    and not has_good_text
                )

                if needs_ocr:
                    ocr_attempted_indices.add(page_index)
                    start = time.perf_counter()
                    ocr_text = ocr_engine.ocr_page(doc, page_index)
                    ocr_total_seconds += time.perf_counter() - start
                    if ocr_text:
                        ocr_success_indices.add(page_index)
                        text = ocr_text
                        method = "ocr"

                text_cache[page_index] = text
                page_methods[page_index] = method

            def text_getter(tp: TaggedPage) -> str:
                if tp.index not in target_indices:
                    return ""
                return text_cache.get(tp.index, "")

            result = _run_extraction(pages, template, text_getter)

            if not result.get("taxpayer_first_name"):
                for tp in pages:
                    title = (tp.outline.title or "") if tp.outline else ""
                    if title == "FILEINST":
                        fallback = _extract_name_from_embedded_fallback(
                            doc[tp.index].get_text("text") or "",
                            source="fileinst",
                        )
                    elif title == "Notes":
                        fallback = _extract_name_from_embedded_fallback(
                            doc[tp.index].get_text("text") or "",
                            source="notes",
                        )
                    else:
                        continue
                    if fallback.get("taxpayer_first_name"):
                        for key, value in fallback.items():
                            if key not in result or not result.get(key):
                                result[key] = value
                        break

            field_sources: dict[str, dict[str, Any]] = {}
            last4_role = result.pop("_last_4_role", None)

            if client_letters:
                cl_idx = client_letters[0].index
                cl_method = page_methods.get(cl_idx, "pymupdf")
                for key in (
                    "taxpayer_first_name",
                    "taxpayer_full_name",
                    "tax_year",
                    "federal_amount",
                    "states",
                    "mailing_address",
                    "mailing_address_line1",
                    "mailing_city",
                    "mailing_state",
                    "mailing_zip",
                    "expected_transmissions",
                    "expected_ack_count",
                    "expected_ack_source",
                ):
                    if key in result:
                        field_sources[key] = {
                            "page_index": cl_idx,
                            "method": cl_method,
                            "role": "extract_client_letter",
                        }
                if "last_4_of_account" in result and last4_role != "extract_dd_pmt":
                    field_sources["last_4_of_account"] = {
                        "page_index": cl_idx,
                        "method": cl_method,
                        "role": "extract_client_letter",
                    }

            if bank_deposit_pages:
                bd_idx = bank_deposit_pages[0].index
                bd_method = page_methods.get(bd_idx, "pymupdf")
                if "bank_name" in result:
                    field_sources["bank_name"] = {
                        "page_index": bd_idx,
                        "method": bd_method,
                        "role": "extract_dd_pmt",
                    }
                if "last_4_of_account" in result and last4_role == "extract_dd_pmt":
                    field_sources["last_4_of_account"] = {
                        "page_index": bd_idx,
                        "method": bd_method,
                        "role": "extract_dd_pmt",
                    }

            fee_role = result.pop("_tax_prep_fee_role", None)
            if fee_role and "tax_prep_fee" in result:
                fee_pages = {
                    "extract_tpg_fee": tpg_fee_pages,
                    "extract_diagnostic_invoice": diagnostic_pages,
                    "extract_bill_fee": bill_fee_pages,
                }.get(fee_role, [])
                if fee_pages:
                    fee_idx = fee_pages[0].index
                    field_sources["tax_prep_fee"] = {
                        "page_index": fee_idx,
                        "method": page_methods.get(fee_idx, "pymupdf"),
                        "role": fee_role,
                    }

            if result.get("has_tpg_pages") is not None:
                field_sources["has_tpg_pages"] = {
                    "page_index": None,
                    "method": "outline",
                    "role": "outline",
                }

            tin_role = result.pop("_taxpayer_tin_role", None)
            if tin_role and "taxpayer_tin" in result:
                tin_pages = {
                    "extract_diagnostic_invoice": diagnostic_pages,
                    "extract_tin_comparison": comparison_pages,
                    "form_federal": tin_1040_pages,
                }.get(tin_role, [])
                if tin_pages:
                    tin_idx = tin_pages[0].index
                    field_sources["taxpayer_tin"] = {
                        "page_index": tin_idx,
                        "method": page_methods.get(tin_idx, "pymupdf"),
                        "role": tin_role,
                    }

            result["_field_sources"] = field_sources
            result["ocr_enabled"] = ocr_enabled
            result["ocr_attempted_count"] = len(ocr_attempted_indices)
            result["ocr_success_count"] = len(ocr_success_indices)
            result["ocr_total_ms"] = int(ocr_total_seconds * 1000)

            if _parser_debug_enabled():
                result["__debug_text_engine"] = (
                    "pymupdf+ocr" if ocr_attempted_indices else "pymupdf"
                )

            return finalize_extracted_fields(result)

        finally:
            doc.close()
