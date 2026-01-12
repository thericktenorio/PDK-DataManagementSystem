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


def _is_client_letter_page(tp: TaggedPage) -> bool:
    """
    A page is a client letter if its structural metadata indicates 'CLIENT_LETTER'.

    Treat any section_key containing 'CLIENT_LETTER' as a client letter page, e.g.:
      - CLIENT_LETTER
      - CLIENT_LETTER_PAGE_2
    """
    sk = (tp.section_key or "").upper()
    if "CLIENT_LETTER" in sk:
        return True

    outline = tp.outline
    title = (outline.title or "").lower() if outline and outline.title else ""
    return "client letter" in title


def _is_bill_page(tp: TaggedPage) -> bool:
    """
    A page is a bill page if its structural metadata indicates 'BILL_01'.

    Treat any section_key starting with 'BILL_01' as a bill page:
      - BILL_01
      - BILL_01_PAGE_2
    """
    sk = (tp.section_key or "").upper()
    if sk.startswith("BILL_01"):
        return True

    outline = tp.outline
    title = (outline.title or "").lower() if outline and outline.title else ""
    return "bill_01" in title or "bill 01" in title


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


def _extract_name_and_address_from_client_letter(source: str) -> dict[str, Any]:
    """
    Given the text of the client letter (or equivalent summary page),
    attempt to extract:
      - taxpayer_full_name
      - taxpayer_first_name
      - mailing_address_line1
      - mailing_city
      - mailing_state
      - mailing_zip
      - mailing_address (full address)

    Drake-style heuristic:
      - Firm header address is usually at the very top.
      - Taxpayer name/address block appears later on the same page.
      - On the FIRST client-letter page, if there are multiple CITY/ST/ZIP
        lines, the LAST one is typically the taxpayer address.
    """
    result: dict[str, Any] = {}
    lines = [ln.strip() for ln in source.splitlines() if ln.strip()]

    if not lines:
        return result

    # Collect all CITY/ST/ZIP candidates on this page
    candidates: list[tuple[int, re.Match[str]]] = []
    for idx, line in enumerate(lines):
        m = CITY_STATE_ZIP_RE.match(line)
        if m:
            candidates.append((idx, m))

    if not candidates:
        return result

    # Prefer the LAST candidate on the page (taxpayer block),
    # so we skip the firm header address when present.
    chosen_idx, chosen_match = candidates[1]

    # City, state, zip
    city = chosen_match.group("city").strip()
    state = chosen_match.group("state").strip()
    zip_code = chosen_match.group("zip").strip()

    result["mailing_city"] = city
    result["mailing_state"] = state
    result["mailing_zip"] = zip_code

    # Street line (just above city, state, zip)
    street: str | None = None
    if chosen_idx >= 1:
        street = lines[chosen_idx - 1].strip()
        if street:
            result["mailing_address_line1"] = street

    # Name line (two lines above city, state, zip)
    if chosen_idx >= 2:
        name_line = lines[chosen_idx - 2].strip()
        # full name: preserve casing / normalize to title for display
        full_name = name_line.title()
        result["taxpayer_full_name"] = full_name

        # primary taxpayer first name heuristic
        primary_segment = name_line
        if "&" in name_line:
            primary_segment = name_line.split("&", 1)[0].strip()
        elif " and " in name_line.lower():
            primary_segment = re.split(
                r"\band\b",
                name_line,
                flags=re.IGNORECASE,
            )[0].strip()

        tokens = primary_segment.split()
        if tokens:
            result["taxpayer_first_name"] = tokens[0].title()

    # combined / full mailing address (on 1 line)
    address_parts = []
    if street:
        address_parts.append(street)
    city_state_zip = " ".join(part for part in [city, state, zip_code] if part)
    if city_state_zip:
        address_parts.append(city_state_zip)
    if address_parts:
        result["mailing_address"] = ", ".join(address_parts)

    return result


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
    """
    Core extraction logic, parameterized by how we obtain text for a TaggedPage.
    `text_getter` is backed by PyMuPDF in this module.
    """
    # -----------------------------------------------
    # 1 ) Gather text and locate client letter page(s)
    # -----------------------------------------------
    all_texts: list[str] = []
    texts_by_label: defaultdict[str, list[str]] = defaultdict(list)
    cover_pages: list[TaggedPage] = []
    cover_texts: list[str] = []
    client_letter_pages: list[TaggedPage] = []
    bill_pages: list[TaggedPage] = []

    for tp in pages:
        text = text_getter(tp)
        all_texts.append(text)

        # group by tag label (backwards compatibility)
        for tag in tp.tags:
            texts_by_label[tag.label].append(text)

        # ID pages tagged as COVER by page_classification_heuristic.py
        is_cover = any(tag.label == "COVER" for tag in tp.tags)
        if is_cover:
            cover_pages.append(tp)
            cover_texts.append(text)

            # use structural metadata from original PDF to locate page
            if _is_client_letter_page(tp):
                client_letter_pages.append(tp)

            if _is_bill_page(tp):
                bill_pages.append(tp)

    # primary text for extraction : COVER pages
    cover_blob = "\n".join(cover_texts)
    # fallback to all pages in case COVER tagging is missing
    all_blob = "\n".join(all_texts)
    blob = cover_blob or all_blob

    # --------------------------------------------------------------------
    # DEBUG: expose what is actually being seen TODO: remove in production
    # --------------------------------------------------------------------
    debug: dict[str, Any] = {
        "__debug_page_count": len(pages),
        "__debug_cover_indices": [tp.index for tp in cover_pages],
        "__debug_client_letter_indices": [tp.index for tp in client_letter_pages],
        "__debug_bill_indices": [tp.index for tp in bill_pages],
    }

    if pages:
        debug["__debug_first_page_snippet"] = (text_getter(pages[0]) or "")[:300]
    if client_letter_pages:
        debug["__debug_client_letter_snippet"] = (text_getter(client_letter_pages[0]) or "")[:300]
    if bill_pages:
        debug["__debug_bill_snippet"] = (text_getter(bill_pages[0]) or "")[:300]

    # prioritize pages tagged / identified as client letter
    if client_letter_pages:
        # OCR-2: use ONLY first client letter page for name/address extraction
        # page 2 often has extra payment addresses (state, vouchers, etc)
        primary_letter_page = client_letter_pages[0]
        client_letter_text = text_getter(primary_letter_page)
    else:
        client_letter_text = cover_blob

    # prioritize pages within COVER for bill
    bill_text = "\n".join(text_getter(tp) for tp in bill_pages) if bill_pages else ""

    out: dict[str, Any] = {}
    out.update(debug)

    # --------------------------------------------------------
    # 2 ) Backwards compatible generic extraction (COVER-wide)
    # --------------------------------------------------------
    # total_amount
    m_amt = _CURRENCY_RE.search(blob)
    if m_amt:
        out["total_amount"] = _normalize_amount(m_amt.group(1))

    # report_date
    m_date = _DATE_RE.search(blob)
    if m_date:
        out["report_date"] = _normalize_date(m_date)

    # ----------------------------------------------------------------------
    # 3 ) Tax year, Name, Address, Last 4 of Bank Account from Client Letter
    # ----------------------------------------------------------------------
    source_for_letter = client_letter_text or blob or all_blob

    # DEBUG: dump full client letter text (capped) so we can see the table
    if source_for_letter:
        debug["__debug_client_letter_full"] = source_for_letter[:4000]

    # tax_year
    tax_year = _extract_tax_year(source_for_letter)
    if tax_year:
        out["tax_year"] = tax_year

    # name + mailing address (from client letter)
    if client_letter_text:
        name_addr_fields = _extract_name_and_address_from_client_letter(client_letter_text)
        out.update(name_addr_fields)

    # last_4_of_account - from direct deposit / account lines
    m_last4 = ACCOUNT_LAST4_RE.search(source_for_letter)
    if m_last4:
        out["last_4_of_account"] = m_last4.group(1)

    # ---------------------------------------------------
    # 3b ) Federal + state amounts from the summary table
    # ---------------------------------------------------
    federal_amount_val, states = _extract_summary_table(source_for_letter)

    if federal_amount_val is not None:
        out["federal_amount"] = federal_amount_val

    if states:
        out["states"] = states

    # -----------------------------
    # 4 ) Tax prep fee from BILL_01
    # -----------------------------
    if bill_text:
        m_bill_amt = _CURRENCY_RE.search(bill_text)
        if m_bill_amt:
            bill_amount = _normalize_amount(m_bill_amt.group(1))
            out["tax_prep_fee"] = float(bill_amount)

    # ----------------------
    # 5 ) has_tpg_pages flag
    # ----------------------
    # scan entire document text for TPG pages
    has_tpg = bool(TPG_RE.search(all_blob))
    out["has_tpg_pages"] = has_tpg

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
            return {"__debug_page_count": 0, "__debug_text_engine": "pymupdf"}

        pdf_path = _get_pdf_source_path(pages)
        doc = fitz.open(str(pdf_path))

        # ----------------------------------------------
        # OCR-1: instantiate ocr engine and read settings
        # ----------------------------------------------
        ocr_config = build_ocr_config_from_settings()
        ocr_engine = OCREngine(ocr_config)
        ocr_enabled: bool = bool(getattr(settings, "OCR_ENABLED", True))
        ocr_candidate_labels: list[str] = list(
            getattr(
                settings,
                "OCR_CANDIDATE_TAG_LABELS",
                [
                    # "COVER",
                ],
            )
        )
        pymupdf_min_length: int = int(getattr(settings, "OCR_PYMUPDF_MIN_LENGTH", 30))
        force_client_letter_flag: bool = bool(getattr(settings, "OCR_FORCE_CLIENT_LETTER", True))
        force_bill_flag: bool = bool(getattr(settings, "OCR_FORCE_BILL", True))

        # debug metrics
        ocr_attempted_indices: set[int] = set()
        ocr_success_indices: set[int] = set()
        ocr_debug: dict[int, dict[str, Any]] = {}  # more indepth debug
        ocr_total_seconds: float = 0.0

        try:

            def text_getter(tp: TaggedPage) -> str:
                nonlocal ocr_total_seconds
                """
                Obtain text for a page:
                1) use PyMuPDF get-text("text")
                2) if OCR enabled
                    - use OCR on high value pages when configured ... or else do...
                    - OCR pages with weak text & tagged w/ candidate labels
                """
                page_index = getattr(tp, "index", None)
                if page_index is None:
                    return ""

                # -----------------------------
                # STEP 1 : ATTEMPT PYMUPDF TEXT
                # -----------------------------
                try:
                    page = doc[page_index]  # 0-based index
                    pymupdf_text = page.get_text("text") or ""
                except Exception:
                    pymupdf_text = ""

                # if OCR engine disabled globally, then return pymupdf text
                if not ocr_enabled:
                    return pymupdf_text

                # ID page types and candidate status
                is_client_letter = _is_client_letter_page(tp)
                is_bill = _is_bill_page(tp)
                labels = [tag.label for tag in tp.tags]
                is_candidate_label = any(label in ocr_candidate_labels for label in labels)

                # determine if force OCR needed
                force_client_letter = force_client_letter_flag and is_client_letter
                force_bill = force_bill_flag and is_bill
                force_ocr = force_client_letter or force_bill

                # decide if pymupdf text is usable
                has_good_text = _has_meaningful_text(
                    pymupdf_text,
                    min_length=pymupdf_min_length,
                )

                # OCR triggers
                # - forced for configured high value pages or
                # - fall back for weak pymupdf text
                needs_ocr = force_ocr or (not has_good_text and is_candidate_label)

                if not needs_ocr:
                    # good pymupf text and not forced OCR
                    return pymupdf_text

                # --------------------------------
                # STEP 2 : USE OCR (IF APPLICABLE)
                # --------------------------------
                ocr_attempted_indices.add(page_index)

                start = time.perf_counter()
                ocr_text = ocr_engine.ocr_page(doc, page_index)
                ocr_total_seconds += time.perf_counter() - start

                # record debug for any OCR parsed pages
                ocr_debug[page_index] = {
                    "pymupdf_len": len(pymupdf_text.strip()),
                    "ocr_len": len((ocr_text or "").strip()),
                    "pymupdf_snippet": (pymupdf_text or "")[:200],
                    "ocr_snippet": (ocr_text or "")[:200],
                    "force_ocr": force_ocr,
                    "labels": labels,
                    "section_key": tp.section_key,
                }

                if ocr_text:
                    ocr_success_indices.add(page_index)
                    return ocr_text

                # still nothing meaningful; fall back to pymupdf or return empty
                return pymupdf_text.strip()

            result = _run_extraction(pages, template, text_getter)

            # OCR debug fields
            result["__debug_text_engine"] = "pymupdf+ocr1" if ocr_attempted_indices else "pymupdf"
            result["__debug_ocr_attempted-indices"] = sorted(ocr_attempted_indices)
            result["__debug_ocr_fallback_indices"] = sorted(ocr_success_indices)
            if ocr_debug:
                result["__debug_ocr_pages"] = ocr_debug

            # high level OCR stats for audit / metrics
            result["ocr_enabled"] = ocr_enabled
            result["ocr_attempted_count"] = len(ocr_attempted_indices)
            result["ocr_success_count"] = len(ocr_success_indices)
            result["ocr_total_ms"] = int(ocr_total_seconds * 1000)

            return result

        finally:
            doc.close()
