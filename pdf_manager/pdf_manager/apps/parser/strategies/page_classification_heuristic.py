from __future__ import annotations

from pdf_manager.apps.parser.strategies.page_classification_base import PageClassificationStrategy
from pdf_manager.apps.parser.types import PageTag, PdfPage


# -----------------------------
# ------- HELP FUNCTION -------
# -----------------------------
def _get_outline_titles_from_page(page: PdfPage) -> list[str]:
    """
    Adapter between the old `page.outlines: list[str]` world and the new
    `page.outline: OutlineInfo | None`.

    Returns a list of outline titles for this page (currently at most 1),
    or an empty list if not outline info is present.
    """
    outline = getattr(page, "outline", None)
    if outline and outline.title:
        return [str(outline.title)]
    return []


class HeuristicClassifier(PageClassificationStrategy):
    """
    Rules-based classifier using PDF outline titles first, then text heuristics.

    Categories:
    - COVER: front-matter (folder page, client letter, privacy policy, bill, etc.)
    - SIGNATURE: any page that requires signatures/authorizations (8879, 8453C, TPG_*, etc.)
    - REMOVAL: filing instrucitons, EF status/messages, notes about the return (federal or state)
    - PAYMENT_VOUCHER: federal or state payment vouchers
    - UNKNOWN: everything else
    """

    name = "heuristic"

    # --------------
    # OUTLINE-BASED PATTERNS (case-insensitive substrings)
    # Derived from Sample A + Sample B outlines
    # --------------

    # These patterns should be tuned from Sample A and B outlines via introspect_pdf
    OUTLINE_REMOVE_KEYS = (
        "ETD_MSG",
        "EF Messages",
        "Notes",
        "EF Status",
    )

    OUTLINE_SIGNATURE_KEYS = (
        "ACH Payment",
        "8879",
        "TPG",
        "Engagement Letter",
        "Account Transaction Summary",
        "DD_PMT",
        "TR579",
        "8453C",
    )

    OUTLINE_COVER_KEYS = (
        "Folder Page",
        "FILEINST",
        "Client Letter",
        "Privacy Policy Letter",
        "Bill_01",
    )

    def tag_pages(self, pages: list[PdfPage]) -> list[list[PageTag]]:
        """
        Rules-based classifier:
        - First uses PDF outline titles (structural metadata) to assign categories
            for removal, signatures, cover pages.
        - Then uses text-based heuristics as a fallback
        - Falls back to UNKNOWN if no rule matches.
        """
        tagged: list[list[PageTag]] = []

        for page in pages:
            tags: list[PageTag] = []

            # --------------
            # 1) Outline-driven heuristics
            # --------------
            outlines = _get_outline_titles_from_page(page)

            def any_outline_contains(outlines_local: list[str], keys: tuple[str, ...]) -> bool:
                outlines_lower = [t.lower() for t in outlines_local]
                keys_lower = [k.lower() for k in keys]
                return any(key in title for title in outlines_lower for key in keys_lower)

            def is_payment_voucher_title(title: str) -> bool:
                """
                Detect Drake payment vouchers, which typically have state form codes ending in V
                1040V - Payment Voucher is the federal page title
                Heuristic: Strip spaces/hyphens, endswith 'V', and contains at least one digit.
                """
                norm = title.strip().lower()
                if "payment voucher" in norm:
                    return True

                # State payment vouchers (ends with "v")
                compact = title.replace(" ", "").replace("-", "").replace("_", "").lower()
                return compact.endswith("v") and any(ch.isdigit() for ch in compact)

            # --- Payment Voucher Pages
            if any(is_payment_voucher_title(t) for t in outlines):
                tags.append(PageTag(label="PAYMENT_VOUCHER", score=0.99))

            # Remove-like pages: EF status, notes, messages
            if any_outline_contains(outlines, self.OUTLINE_REMOVE_KEYS):
                # You may choose finer-grained labels here based on the specific key;
                # for now, classify them as NOTES for removal purposes.
                tags.append(PageTag(label="NOTES", score=0.99))

            # Signature-related pages
            if any_outline_contains(outlines, self.OUTLINE_SIGNATURE_KEYS):
                tags.append(PageTag(label="SIGNATURE", score=0.99))

            # Cover / summary pages
            if any_outline_contains(outlines, self.OUTLINE_COVER_KEYS):
                tags.append(PageTag(label="COVER", score=0.95))

            # --------------
            # 2) Text-based heuristics (your existing rules) as fallback/additional signal
            # --------------
            text = ""
            raw = page.raw
            try:
                if hasattr(raw, "extract_text"):
                    text = raw.extract_text() or ""
                elif hasattr(raw, "get_text"):
                    text = raw.get_text() or ""
            except Exception:
                text = ""
            lower = text.lower()

            # --- COVER pages (text-based; still restricted to early pages) ---
            if page.index <= 3 and any(
                kw in lower for kw in ("client copy", "filing copy", "preparer copy")
            ):
                tags.append(PageTag(label="COVER", score=0.95))

            # --- SIGNATURE pages ---
            if any(
                kw in lower
                for kw in (
                    "sign here",
                    "taxpayer signature",
                    "spouse signature",
                    "signature of taxpayer",
                    "signature of preparer",
                    "sign and date",
                )
            ):
                tags.append(PageTag(label="SIGNATURE", score=0.99))

            # --- EF / e-file status pages (text-based) ---
            if any(
                kw in lower
                for kw in (
                    "electronic filing status",
                    "e-file status",
                    "efile status",
                    "ef status",
                )
            ):
                tags.append(PageTag(label="EF_STATUS", score=0.9))

            # --- Filing instructions / messages ---
            if "filing instructions" in lower or "filing message" in lower:
                tags.append(PageTag(label="FILING_MESSAGE", score=0.9))

            # --- State-specific filing messages ---
            if "state filing instructions" in lower or "state filing message" in lower:
                tags.append(PageTag(label="STATE_FILING_MESSAGE", score=0.9))

            # --- Internal notes / admin pages ---
            if any(
                kw in lower
                for kw in ("preparer notes", "internal use only", "do not send to client")
            ):
                tags.append(PageTag(label="NOTES", score=0.8))

            """
            # Future: additional tags for financial documents (Drake outline classifier preferred).
            This could be used to pull essential data for analytics and future AI features.
            """

            # --- Fallback ---
            if not tags:
                tags.append(PageTag(label="UNKNOWN", score=0.1))

            tagged.append(tags)

        return tagged
