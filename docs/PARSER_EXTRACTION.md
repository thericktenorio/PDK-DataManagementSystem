# Parser extraction spec (Drake schema v1)

Phase 5 source of truth for what the pdf_manager parser extracts, which pages supply it, and how CRM clearing consumes it.

See also: `ROADMAP.md` (Phase 5), `pdk_crm/clearing/services/parser_schema.py`, `pdf_manager/fixtures/drake_samples/outline_registry.yaml`.

---

## Role in the ecosystem

```text
Drake PDF → pdf_manager (extract + packets) → CRM snapshot on PA → (Phase 9) analytics facts
```

- **Parser DB** (`parser`): job rows, `Template` field catalog, `ExtractedField` facts with lineage.
- **CRM** (`tax_operations`): `parse_result_json` snapshot only; staff edits PA columns in clearing.
- **Analytics** (later): ETL from parser facts, not heavy JSON mining on CRM.

---

## Field tiers (MVP)

### Tier A — message-ready (Path A must have these for auto message)

| Key | Source role | Notes |
|-----|-------------|--------|
| `taxpayer_first_name` | `extract_client_letter` | Fallback: first token of `taxpayer_full_name` |
| `tax_year` | `extract_client_letter` | Regex on letter text |

`message_ready` is true only when both Tier A fields are present after `finalize_extracted_fields()`.

### Tier B — clearing hints (optional; staff can override in Path B)

| Key | Maps to clearing | Source |
|-----|------------------|--------|
| `federal_amount`, `states` | Client message body | Client Letter |
| `last_4_of_account`, `mailing_address*` | Refund paragraph | Client Letter |
| `tax_prep_fee` | `pa.fee` only if extracted | BILL (`OCR_EXTRACT_BILL`, default off) |
| `has_tpg_pages` | `payment_method` = TPG if true | Outline titles (no OCR) |

**Fee policy:** PDF fee is a hint. Product `default_price` and manual fee edits remain valid (Path B).

### Tier C — snapshot / analytics (not blocking clearing)

`taxpayer_full_name`, mailing parts, `ocr_*` metrics, output PDF paths.

### Not extracted in MVP (staff / intake)

`filing_type`, `product`, `preparer`, client grid `TIN` / `name`.

---

## Page strategy

| Role | OCR when image-only | MVP |
|------|---------------------|-----|
| `extract_client_letter` | Yes (corpus: 0 embedded text on all 8 samples) | **Required** for Tier A |
| `extract_bill` | Only if `OCR_EXTRACT_BILL=true` | **Optional** (fee hint) |
| TPG / signature / vouchers | Classification only | Packets + `has_tpg_pages` |

Alternative pages (Comparison, state COMP) have embedded text but **different layout** — not drop-in replacements for Client Letter regex (v2).

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
- Async queue: deferred to ROADMAP 5.5 when concurrency or p95 exceeds budget.

---

## Schema version

Bump `SCHEMA_VERSION` in CRM and parser catalog only when extracted keys or semantics change.
