# Parser extraction spec (Drake schema v1)

Phase 5 source of truth for what the pdf_manager parser extracts, which pages supply it, and how CRM clearing consumes it.

See also: `docs/PARSER_ROADMAP.md` (status, backlog, resume checklist), `ROADMAP.md` (Phase 5), `pdk_crm/clearing/services/parser_schema.py`, `pdf_manager/fixtures/drake_samples/outline_registry.yaml`.

**Return-level / executive extraction (schema v2, async Track 2):** `docs/RETURN_ANALYTICS.md` and `docs/ANALYTICS_ROADMAP.md` (phase A1). Not part of clearing schema v1.

---

## Role in the ecosystem

```text
Drake PDF → pdf_manager (extract + packets) → CRM snapshot on PA → (Phase 9) analytics facts
```

- **Parser DB** (`parser`): job rows, `Template` field catalog, `ExtractedField` facts with lineage.
- **CRM** (`tax_operations`): `parse_result_json` snapshot only; staff edits PA columns in clearing.
- **Analytics** (later): ETL from parser facts, not heavy JSON mining on CRM.

Field extraction runs **before** packet sorting (main / signature / payment voucher). Fee data is read from `TPG_INFO` during extraction even though that page is routed to the signature packet.

---

## Extracted fields catalog

All keys below are persisted to `ExtractedField` rows and included in the CRM snapshot (`parse_result_json.fields`) when present. Lineage (`page_index`, `method`, `role`) is stored in parser DB only via `_field_sources`.

| Field | Tier | Drake outline / location | Registry role | Text method | Extraction rule (summary) |
|-------|------|--------------------------|---------------|-------------|---------------------------|
| `taxpayer_first_name` | A | **Client Letter** (first page) | `extract_client_letter` | OCR | First token of primary taxpayer on first post-date address block; skips firm header and IRS/FTB remittance addresses |
| `taxpayer_first_name` | A | **Notes** or **FILEINST** (fallback) | `remove` / `cover` | PyMuPDF | Used only if Client Letter did not yield a first name |
| `taxpayer_full_name` | C | **Client Letter** (first page) | `extract_client_letter` | OCR | Name line two lines above taxpayer CITY/ST/ZIP; joint names kept (e.g. `John & Jane Doe`) |
| `taxpayer_full_name` | C | **Notes** or **FILEINST** (fallback) | `remove` / `cover` | PyMuPDF | `Name(s) as shown on return` line or `Filing Instructions` line |
| `taxpayer_tin` | A | **Diagnostic Summary** | `extract_diagnostic_invoice` | PyMuPDF | **Priority 1:** primary SSN or entity EIN (9 digits, dashes stripped) |
| `taxpayer_tin` | A | **Comparison** | `extract_tin_comparison` | PyMuPDF | **Priority 2:** identifying number footer; joint returns use first SSN |
| `taxpayer_tin` | A | **1040** page 1 | `form_federal` | PyMuPDF | **Priority 3:** first SSN on outline title exactly `1040` |
| `tax_year` | A | **Client Letter** (first page) | `extract_client_letter` | OCR | Regex: `tax year 20xx`, `20xx tax return`, etc. |
| `federal_amount` | B | **Client Letter** (first page) | `extract_client_letter` | OCR | Summary table row containing `Federal` + `income tax`; negative = balance due |
| `states` | B | **Client Letter** (first page) | `extract_client_letter` | OCR | Summary table state rows → `[{state: "CA", amount: float}, …]` |
| `last_4_of_account` | B | **Client Letter** (first page) | `extract_client_letter` | OCR | `account ending in XXXX` / `ending in XXXX` |
| `mailing_address` | B | **Client Letter** (first page) | `extract_client_letter` | OCR | Combined street + city/state/zip for taxpayer block |
| `mailing_address_line1` | C | **Client Letter** (first page) | `extract_client_letter` | OCR | Street line above taxpayer CITY/ST/ZIP |
| `mailing_city` | C | **Client Letter** (first page) | `extract_client_letter` | OCR | From taxpayer CITY/ST/ZIP match |
| `mailing_state` | C | **Client Letter** (first page) | `extract_client_letter` | OCR | From taxpayer CITY/ST/ZIP match |
| `mailing_zip` | C | **Client Letter** (first page) | `extract_client_letter` | OCR | From taxpayer CITY/ST/ZIP match |
| `tax_prep_fee` | B | **TPG_INFO** (Bank Product Information) | `extract_tpg_fee` | PyMuPDF | **Priority 1 (TPG returns):** amount on line after `PDK ENTRUST` in Fees section |
| `tax_prep_fee` | B | **Diagnostic Summary** | `extract_diagnostic_invoice` | PyMuPDF | **Priority 2 (invoice / QBO):** `$amount` in preparer / `Invoice # and Amount:` block |
| `tax_prep_fee` | B | **BILL_01 page 2** | `extract_bill_fee` | OCR | **Priority 3 (S-corp / entity bill):** `Forms Subtotal` or `Total Balance Due` row |
| `has_tpg_pages` | B | Any outline title containing `TPG` | `outline` | n/a | Boolean; CRM may set `payment_method` = TPG |

### Fee source priority

Only one `tax_prep_fee` is stored per parse job:

```text
TPG_INFO (extract_tpg_fee)  →  Diagnostic Summary (extract_diagnostic_invoice)  →  BILL_01 page 2 (extract_bill_fee)
```

**Not used for fee:** `BILL_01` page 1 (form index only). The legacy `OCR_EXTRACT_BILL` setting is superseded by the roles above.

**Fee policy:** PDF fee is a hint. Product `default_price` and manual fee edits remain valid (Path B).

### Tier A — message-ready

`message_ready` is true only when both `taxpayer_first_name` and `tax_year` are present after `finalize_extracted_fields()` (including first-name fallback from `taxpayer_full_name`).

### Not extracted in MVP (staff / intake)

`filing_type`, `product`, `preparer` from PDF (staff selects in enrollment modal for global upload). Client grid TIN / name still from CRM unless created from parse.

---

## Page roles and text strategy

| Registry role | Drake outline title(s) | OCR when image-only? | Used for |
|---------------|------------------------|----------------------|----------|
| `extract_client_letter` | `Client Letter`, `Client Letter page 2` | Yes (required on corpus) | Tier A/B name, tax year, amounts, address |
| `extract_tpg_fee` | `TPG_INFO` | No (embedded text) | TPG tax prep fee; page also in **signature packet** |
| `extract_diagnostic_invoice` | `Diagnostic Summary` | No (embedded text) | Invoice fee + taxpayer TIN; page **excluded** from client packet |
| `extract_tin_comparison` | `Comparison` | No (embedded text) | TIN fallback; page **excluded** from client packet |
| `extract_bill_fee` | `BILL_01 page 2` | Yes | S-corp / entity billing total |
| `extract_bill` | `BILL_01` (page 1 only) | Yes if read | Form index — **not** used for fee |
| `outline` / signature / voucher roles | TPG forms, 8879, vouchers, etc. | Usually no | Packet routing + `has_tpg_pages` |

**Name fallbacks (embedded text, no OCR):**

| Outline title | Role | When used |
|---------------|------|-----------|
| `Notes` | `remove` | Client Letter missing first name |
| `FILEINST` | `cover` | Client Letter missing first name |

Alternative pages (Comparison, state COMP, raw 1040 form) have embedded text but **different layout** — not drop-in replacements for Client Letter regex (v2).

---

## CRM behavior (Path A)

1. Parse succeeds → store snapshot, output refs, `parser_status=DONE`.
2. Set `closing_message_text` only when `message_ready` is true.
3. Set `pa.fee` only when `tax_prep_fee` is present in extracted fields.
4. Set `payment_method` to TPG when `has_tpg_pages` is true.
5. UI shows a warning when PDFs/fields exist but message was not auto-filled.

---

## Performance target

- Corpus benchmark: sync parse p95 &lt; 5s on Drake samples (see `test_parser_benchmark.py`).
- Typical corpus timings (local): personal ~2.0–2.4s (Client Letter OCR + embedded fee pages); S-corp ~1.0–1.1s (Client Letter + BILL page 2 OCR).
- Async queue: deferred to ROADMAP 5.5 when concurrency or p95 exceeds budget.

---

## Schema version

Bump `SCHEMA_VERSION` in CRM and parser catalog only when extracted keys or semantics change.
