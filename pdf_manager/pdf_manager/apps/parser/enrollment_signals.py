"""
Enrollment inference signals from Drake PDF outline + Comparison/Diagnostic text.

Track 1 only — signals needed for Path A enrollment, not full RETURN_ANALYTICS KPIs.
"""
from __future__ import annotations

import re
from typing import Any

from pdf_manager.apps.parser.types import TaggedPage

_TIN_SSN_RE = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")

_CORP_OUTLINE_RE = re.compile(r"1120s|1120sef|1120sk|\b1120\b", re.IGNORECASE)
_CORP_NAME_RE = re.compile(r"\bcorp\b", re.IGNORECASE)
_AMENDMENT_RE = re.compile(r"(?:\b\d{3,4}X\b|\b\d+X\b)", re.IGNORECASE)
_EXTENSION_MARKERS = ("4868", "7004", "extension")
_SOLE_PROP_SCHEDULE_MARKERS = ("schedule c", "schedule e", "schedule se")


def _is_numeric_line(value: str) -> bool:
    try:
        float(str(value).replace(",", ""))
        return True
    except (TypeError, ValueError):
        return False


def _parse_amount(value: str) -> float:
    return float(str(value).replace(",", ""))


def _looks_like_preparer_name(line: str) -> bool:
    if len(line) < 4 or line.endswith(":"):
        return False
    lower = line.lower()
    if lower.startswith(
        ("preparer", "invoice", "date", "return information", "form type", "dependent")
    ):
        return False
    if line.startswith("$") or re.match(r"^\$?\s*[\d,]+\.\d{2}\s*$", line):
        return False
    if re.search(r"\d{1,2}-\d{1,2}-\d{4}", line):
        return False
    if re.fullmatch(r"[\d\s\-]+", line):
        return False
    return bool(re.search(r"[A-Za-z]", line))


def _extract_preparer_name_from_diagnostic(text: str) -> str | None:
    if not text or "Preparer" not in text:
        return None

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    for idx, line in enumerate(lines):
        if not re.match(r"^\$?\s*[\d,]+\.\d{2}\s*$", line):
            continue
        for candidate in reversed(lines[max(0, idx - 12) : idx]):
            if _looks_like_preparer_name(candidate):
                return candidate.strip()

    preparer_idx = next((i for i, line in enumerate(lines) if line.lower().startswith("preparer")), None)
    if preparer_idx is None:
        return None

    for candidate in lines[preparer_idx + 1 : preparer_idx + 20]:
        if _looks_like_preparer_name(candidate):
            return candidate.strip()
    return None


def _extract_dependents_from_comparison_footer(footer_lines: list[str]) -> int | None:
    val_idx = 0
    while val_idx < len(footer_lines) and not _is_numeric_line(footer_lines[val_idx]):
        val_idx += 1
    vals: list[float] = []
    while val_idx < len(footer_lines) and len(vals) < 3 and _is_numeric_line(footer_lines[val_idx]):
        vals.append(_parse_amount(footer_lines[val_idx]))
        val_idx += 1
    if not vals:
        return None
    return int(vals[-1])


def _extract_itemized_and_standard(footer_lines: list[str]) -> tuple[float | None, float | None]:
    amounts = [
        (idx, _parse_amount(line))
        for idx, line in enumerate(footer_lines)
        if _is_numeric_line(line)
    ]
    candidates: list[tuple[float, float]] = []
    for i in range(len(amounts) - 1):
        if amounts[i][1] != amounts[i + 1][1]:
            continue
        itemized = amounts[i][1]
        if not (20_000 <= itemized <= 100_000):
            continue
        for j in range(i + 2, min(i + 10, len(amounts) - 1)):
            if amounts[j][1] != amounts[j + 1][1]:
                continue
            standard = amounts[j][1]
            if 12_000 <= standard <= 35_000 and standard < itemized:
                candidates.append((itemized, standard))
                break
    if not candidates:
        return None, None
    return max(candidates, key=lambda pair: pair[0])


def _extract_credits_from_comparison_footer(
    footer_lines: list[str],
    *,
    standard_value: float | None,
) -> float | None:
    amounts = [
        (idx, _parse_amount(line))
        for idx, line in enumerate(footer_lines)
        if _is_numeric_line(line)
    ]
    passed_standard = standard_value is None
    for i in range(len(amounts) - 1):
        value = amounts[i][1]
        if (
            not passed_standard
            and standard_value is not None
            and value == standard_value
            and amounts[i + 1][1] == standard_value
        ):
            passed_standard = True
            continue
        if not passed_standard:
            continue
        if 0 < value <= 25_000 and value == amounts[i + 1][1]:
            return value
    return None


def _comparison_footer_lines(text: str) -> list[str]:
    if not text or "TAX RETURN COMPARISON" not in text.upper():
        return []

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    tin_idx = next(
        (i for i, line in enumerate(lines) if _TIN_SSN_RE.fullmatch(line)),
        None,
    )
    if tin_idx is None:
        return []
    return lines[tin_idx + 1 :]


def extract_comparison_enrollment_signals(text: str) -> dict[str, Any]:
    footer = _comparison_footer_lines(text)
    if not footer:
        return {}

    dependents = _extract_dependents_from_comparison_footer(footer)
    itemized, standard = _extract_itemized_and_standard(footer)
    credits = _extract_credits_from_comparison_footer(footer, standard_value=standard)

    signals: dict[str, Any] = {}
    if dependents is not None:
        signals["comparison_num_dependents"] = dependents
    if itemized is not None:
        signals["comparison_itemized_deductions"] = itemized
    if standard is not None:
        signals["comparison_standard_deduction"] = standard
    if credits is not None:
        signals["comparison_credits"] = credits
    return signals


def _outline_title(tp: TaggedPage) -> str:
    return (getattr(tp.outline, "title", "") or "").strip()


def scan_outline_enrollment_signals(pages: list[TaggedPage]) -> dict[str, Any]:
    titles = [_outline_title(tp) for tp in pages if _outline_title(tp)]
    lowered = [title.lower() for title in titles]

    is_corporation = any(
        _CORP_OUTLINE_RE.search(title) or _CORP_NAME_RE.search(title)
        for title in titles
    )
    has_sole_prop_schedule = any(
        any(marker in title for marker in _SOLE_PROP_SCHEDULE_MARKERS)
        for title in lowered
    )
    has_extension = any(
        any(marker in title for marker in _EXTENSION_MARKERS)
        for title in lowered
    )
    amendment_count = sum(1 for title in titles if _AMENDMENT_RE.search(title))

    signals: dict[str, Any] = {
        "is_corporation": is_corporation,
        "has_sole_prop_schedule": has_sole_prop_schedule,
        "has_extension": has_extension,
        "amendment_count": amendment_count,
    }
    if titles:
        signals["outline_titles_sample"] = titles[:12]
    return signals


def build_enrollment_signals(
    *,
    pages: list[TaggedPage],
    comparison_text: str,
    diagnostic_text: str,
    has_tpg_pages: bool,
) -> dict[str, Any]:
    signals = scan_outline_enrollment_signals(pages)
    signals.update(extract_comparison_enrollment_signals(comparison_text))

    preparer_name = _extract_preparer_name_from_diagnostic(diagnostic_text)
    if preparer_name:
        signals["preparer_name"] = preparer_name

    signals["has_tpg_pages"] = bool(has_tpg_pages)
    return signals
