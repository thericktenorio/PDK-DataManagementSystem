from __future__ import annotations

import io
from dataclasses import dataclass

import fitz  # PyMuPDF
import pytesseract
from django.conf import settings
from PIL import Image  # PIL = Pillow; IMPORTANT: use Pillow for pip install and requirement.txt


@dataclass
class OCREngineConfig:
    """
    Configuration options for the OCR engine

    For OCR-0, OCR-1, keep this intentionally small and simple
    """

    lang: str = "eng"
    dpi: int = 150
    min_text_length: int = 10
    tesseract_cmd: str | None = None


def build_ocr_config_from_settings() -> OCREngineConfig:
    """
    Construct an OCREngineConfig from Django settings w/ safe defaults
    """
    if not hasattr(settings, "OCR_ENABLED"):
        # non-django or very early import: fall back to hard-coded defaults
        return OCREngineConfig()

    return OCREngineConfig(
        lang=getattr(settings, "OCR_LANG", "eng"),
        dpi=int(getattr(settings, "OCR_DPI", 150)),
        min_text_length=int(getattr(settings, "OCR_MIN_TEXT_LENGTH", 10)),
        tesseract_cmd=getattr(settings, "OCR_TESSERACT_CMD", None),
    )


class OCREngine:
    """
    Minimal OCR engine used as a fallback when PyMuPDF text extraction is empty

    Usage (conceptually):
        engine = OCREngine()
        ocr_text = engine.ocr_page(doc, page_index)
    """

    def __init__(self, config: OCREngineConfig | None = None) -> None:
        self.config = config or OCREngineConfig()

        # allow overriding tesseract binary path (useful in Docker)
        if self.config.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self.config.tesseract_cmd

    def ocr_page(self, doc: fitz.Document, page_index: int) -> str:
        """
        Render the given page as an image and run OCR on it

        Returns a stripped string; may be empty if OCR produced no meaningful text
        """
        page = doc.load_page(page_index)

        # render page as an image; scale based on desired DPI
        # 72 dpi is the default; scale factor = target_dpi / 72
        scale = self.config.dpi / 72.0
        matrix = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        # convert PyMuPDF pixmap to a PIL image
        img_bytes = pix.tobytes("png")
        image = Image.open(io.BytesIO(img_bytes))

        # run OCR
        raw_text = pytesseract.image_to_string(image, lang=self.config.lang, config="--psm 6")

        text = self._normalize_text(raw_text)
        if len(text) < self.config.min_text_length:
            # treat tiny outputs as noise and return empty string for OCR-0
            return ""

        return text

    @staticmethod
    def _normalize_text(text: str) -> str:
        """
        basic cleanup: strip, collapse repeated whitespace, normalize newlines
        """
        if not text:
            return ""

        # strip leading /trailing whitespace
        text = text.strip()

        # normalize newlines (optional light cleanup)
        # you can add more sophisticated normalization later
        lines = [line.rstrip() for line in text.splitlines()]
        cleaned = "\n".join(line for line in lines if line)  # drop pure blank lines

        return cleaned
