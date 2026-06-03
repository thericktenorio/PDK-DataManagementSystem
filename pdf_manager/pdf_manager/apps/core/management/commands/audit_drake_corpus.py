"""
Batch audit of Drake sample PDFs for parser rebuild planning.

Reports per file:
  - page count, outline titles, classifier tag distribution
  - PyMuPDF text length + image count on key pages (client letter, bill, etc.)
  - full parse timing + extracted field keys (optional)

Usage:
  python manage.py audit_drake_corpus
  python manage.py audit_drake_corpus --dir fixtures/drake_samples
  python manage.py audit_drake_corpus --output /home/app/data/reports/corpus_audit.json
  python manage.py audit_drake_corpus --no-parse
"""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from uuid import uuid4

import fitz
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from pdf_manager.apps.parser.facade import PDFParserFacade
from pdf_manager.apps.parser.introspection import introspect_local_file


def _default_report_path() -> Path:
    data_root = Path(getattr(settings, "DATA_ROOT", "/home/app/data"))
    return data_root / "reports" / "corpus_audit.json"

KEY_OUTLINE_SUBSTRINGS = (
    "client letter",
    "bill_01",
    "bill 01",
    "payment voucher",
    "8879",
    "8453",
    "tpg",
    "ach payment",
    "engagement letter",
    "folder page",
    "fileinst",
)

TEXT_WEAK_THRESHOLD = int(getattr(settings, "OCR_PYMUPDF_MIN_LENGTH", 30))


def _normalize_title(title: str) -> str:
    return " ".join((title or "").lower().split())


def _is_key_page(title: str) -> bool:
    norm = _normalize_title(title)
    return any(key in norm for key in KEY_OUTLINE_SUBSTRINGS)


def _page_key_role(title: str) -> str:
    norm = _normalize_title(title)
    if "client letter" in norm:
        return "client_letter"
    if "bill_01" in norm or "bill 01" in norm:
        return "bill"
    if "payment voucher" in norm or (norm.replace("-", "").replace(" ", "").endswith("v") and any(c.isdigit() for c in norm)):
        return "payment_voucher"
    if any(k in norm for k in ("8879", "8453", "tpg", "ach payment", "engagement letter")):
        return "signature"
    if any(k in norm for k in ("folder page", "fileinst")):
        return "cover"
    return "other_key"


def _build_outline_map(doc: fitz.Document) -> dict[int, list[str]]:
    """Map page index -> list of outline titles (PyMuPDF TOC)."""
    outlines: dict[int, list[str]] = {}
    try:
        toc = doc.get_toc(simple=True) or []
    except Exception:
        return outlines
    for _level, title, page_num in toc:
        # PyMuPDF TOC page numbers are 1-based
        idx = max(page_num - 1, 0)
        outlines.setdefault(idx, []).append(str(title))
    return outlines


def _inspect_page_text(doc: fitz.Document, page_index: int) -> dict:
    page = doc[page_index]
    try:
        text = page.get_text("text") or ""
    except Exception:
        text = ""
    try:
        images = page.get_images(full=True) or []
        image_count = len(images)
    except Exception:
        image_count = 0
    text_len = len(text.strip())
    return {
        "text_len": text_len,
        "image_count": image_count,
        "text_usable": text_len >= TEXT_WEAK_THRESHOLD,
        "likely_needs_ocr": text_len < TEXT_WEAK_THRESHOLD and image_count > 0,
    }


def _audit_file(pdf_path: Path, *, run_parse: bool) -> dict:
    doc = fitz.open(str(pdf_path))
    outline_map = _build_outline_map(doc)
    page_count = doc.page_count

    key_pages: list[dict] = []
    for idx in range(page_count):
        titles = outline_map.get(idx, [])
        if not titles:
            continue
        for title in titles:
            if _is_key_page(title):
                info = _inspect_page_text(doc, idx)
                key_pages.append(
                    {
                        "page_index": idx,
                        "outline_title": title,
                        "role": _page_key_role(title),
                        **info,
                    }
                )
    doc.close()

    _, _, introspection = introspect_local_file(pdf_path)
    tag_counter: Counter[str] = Counter()
    outline_titles: set[str] = set()
    unknown_count = 0
    for page in introspection:
        if not page.tags or (len(page.tags) == 1 and page.tags[0].label == "UNKNOWN"):
            unknown_count += 1
        for tag in page.tags:
            tag_counter[tag.label] += 1
        for title in page.outline_titles:
            outline_titles.add(title)

    result: dict = {
        "filename": pdf_path.name,
        "page_count": page_count,
        "outline_title_count": len(outline_titles),
        "outline_titles": sorted(outline_titles),
        "unknown_page_count": unknown_count,
        "unknown_page_pct": round(100 * unknown_count / page_count, 1) if page_count else 0,
        "tag_counts": dict(sorted(tag_counter.items())),
        "key_pages": key_pages,
        "key_pages_needing_ocr": [p for p in key_pages if p["likely_needs_ocr"]],
        "key_pages_text_usable": [p for p in key_pages if p["text_usable"]],
    }

    if run_parse:
        facade = PDFParserFacade()
        start = time.perf_counter()
        try:
            if hasattr(facade, "run"):
                parse_result = facade.run(input_path=str(pdf_path))
            else:
                parse_result = facade.parse(job_id=uuid4(), file_path=str(pdf_path))
            elapsed = time.perf_counter() - start
            fields = parse_result.extracted_fields or {}
            result["parse"] = {
                "ok": True,
                "seconds": round(elapsed, 3),
                "field_keys": sorted(k for k in fields if not str(k).startswith("__")),
                "ocr_attempted_count": fields.get("ocr_attempted_count"),
                "ocr_total_seconds": fields.get("ocr_total_seconds"),
                "has_message": bool(parse_result.message),
                "message_len": len(parse_result.message or ""),
            }
        except Exception as exc:
            elapsed = time.perf_counter() - start
            result["parse"] = {
                "ok": False,
                "seconds": round(elapsed, 3),
                "error": str(exc),
            }

    return result


class Command(BaseCommand):
    help = "Audit all Drake sample PDFs in a directory (outline, text layer, parse timing)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir",
            dest="samples_dir",
            default="fixtures/drake_samples",
            help="Directory containing sample PDF files (default: fixtures/drake_samples).",
        )
        parser.add_argument(
            "--output",
            dest="output",
            default="",
            help="Write JSON report to this path (default: DATA_ROOT/reports/corpus_audit.json).",
        )
        parser.add_argument(
            "--no-parse",
            dest="no_parse",
            action="store_true",
            help="Skip full parse pipeline (faster; structure/text only).",
        )

    def handle(self, *args, **options):
        samples_dir = Path(options["samples_dir"]).expanduser().resolve()
        if not samples_dir.is_dir():
            raise CommandError(f"Directory not found: {samples_dir}")

        pdfs = sorted(samples_dir.glob("*.pdf"))
        if not pdfs:
            raise CommandError(f"No PDF files found in {samples_dir}")

        self.stdout.write(f"Auditing {len(pdfs)} PDF(s) in {samples_dir} …")

        files: list[dict] = []
        all_outlines: Counter[str] = Counter()
        corpus_key_pages: list[dict] = []

        for pdf_path in pdfs:
            self.stdout.write(f"  • {pdf_path.name}")
            audit = _audit_file(pdf_path, run_parse=not options["no_parse"])
            files.append(audit)
            for title in audit["outline_titles"]:
                all_outlines[title] += 1
            for kp in audit["key_pages"]:
                corpus_key_pages.append({"filename": pdf_path.name, **kp})

        # Cross-corpus summary
        ocr_needed = [p for p in corpus_key_pages if p.get("likely_needs_ocr")]
        text_ok = [p for p in corpus_key_pages if p.get("text_usable")]

        parse_times = [f["parse"]["seconds"] for f in files if f.get("parse", {}).get("ok")]
        summary = {
            "sample_count": len(pdfs),
            "unique_outline_titles": len(all_outlines),
            "outline_titles_seen_in_2plus_files": sorted(
                t for t, c in all_outlines.items() if c >= 2
            ),
            "key_page_observations": len(corpus_key_pages),
            "key_pages_text_usable": len(text_ok),
            "key_pages_likely_needing_ocr": len(ocr_needed),
            "parse_seconds_min": round(min(parse_times), 3) if parse_times else None,
            "parse_seconds_max": round(max(parse_times), 3) if parse_times else None,
            "parse_seconds_avg": round(sum(parse_times) / len(parse_times), 3) if parse_times else None,
        }

        report = {"summary": summary, "outline_frequency": dict(all_outlines.most_common()), "files": files}

        output_raw = (options.get("output") or "").strip()
        output_path = Path(output_raw).expanduser().resolve() if output_raw else _default_report_path()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        self.stdout.write(self.style.SUCCESS(f"\nReport written to {output_path}"))
        self.stdout.write(
            f"  Pages/key-role: {summary['key_page_observations']} observed, "
            f"{summary['key_pages_text_usable']} with usable PyMuPDF text, "
            f"{summary['key_pages_likely_needing_ocr']} likely needing OCR"
        )
        if parse_times:
            self.stdout.write(
                f"  Parse timing: min={summary['parse_seconds_min']}s "
                f"max={summary['parse_seconds_max']}s avg={summary['parse_seconds_avg']}s"
            )
