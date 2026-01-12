# Choose PyPDF2 as Initial PdfReader Adapter

Date: 2025-10-29

## Status

Accepted

## Decision

Use `PyPDF2` for Phase 2/3 with a `PdfReaderAdapter` abstraction. Keep `pdfminer.six`/`pdfplumber` as future alternatives via `PdfReaderAdapter`.

## Consequences

- (+) Rapid progress; stable API.
- (+) Easy subset write.
- (-) Text extraction quality limited on some PDFs; can swap later without touching facade due to Adapter pattern.
