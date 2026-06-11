# Parser development roadmap

Handoff doc for **resuming parser work** after a pause. Covers clearing Path A (schema v1) and points to analytics Track 2 (schema v2).

**Not a replacement for `ROADMAP.md`.** Monolith-wide phases stay in the main roadmap.

| Doc | Role |
|-----|------|
| **`docs/PARSER_EXTRACTION.md`** | Schema v1 spec — fields, pages, fee rules, `message_ready` |
| **`docs/PARSER_ROADMAP.md`** (this file) | Status, backlog, tests, resume checklist |
| **`docs/PATH_A_TESTING.md`** | Path A sign-off checklist (gate before analytics A1) |
| **`docs/PATH_A_PDF_UPLOAD.md`** | Global upload, TIN match, auto-enrollment spec |
| **`docs/ACKNOWLEDGMENTS.md`** | Drake ack ingest + PA matching |
| **`docs/PRODUCT_ASSIGNMENT_WORKFLOW.md`** | Full PA workflow after clearing (review, acks, TP Comp Dt) |
| **`docs/RETURN_ANALYTICS.md`** | Schema v2 / async Track 2 technical spec |
| **`docs/ANALYTICS_ROADMAP.md`** | Analytics phases A1–A5 (Track 2 sequencing) |
| **`ROADMAP.md`** | Phase 4 (Path A), Phase 5 (quality & speed) |

---

## Status snapshot (pause point)

| Area | Status |
|------|--------|
| **Path B clearing** | ✅ Production default — no parser required |
| **Path A integration** | Built (upload, snapshot, message, output PDFs) — **beta smoke test deferred** |
| **Schema v1 extraction** | ✅ Client Letter, fee tiers, packets, `message_ready` |
| **Phase 5 polish** | In progress — see backlog below |
| **Schema v2 / Track 2** | Not started — see `ANALYTICS_ROADMAP.md` A1 |
| **Ack hints from PDF** | ✅ | Feeds `expected_ack_count` at Review Complete — see `ack_hints.py`, `docs/REVIEW.md` |

**Practical stance:** Parser is **usable for clearing MVP**; treat as **paused** until smoke tests pass or Phase 5 backlog is cleared. Path B remains the safe operational fallback.

---

## Two parser tracks

```text
PDF upload (Path A)
        │
        ▼
┌───────────────────────────────────────────┐
│  Track 1 — sync (CLEARING, schema v1)      │
│  message, fee, packets → CRM snapshot      │  ◀── this doc + PARSER_EXTRACTION.md
└───────────────────────────────────────────┘
        │
        ▼ (when analytics work resumes)
┌───────────────────────────────────────────┐
│  Track 2 — async (EXECUTIVE, schema v2)    │
│  Comparison, return profile → parser DB    │  ◀── RETURN_ANALYTICS.md, A1
└───────────────────────────────────────────┘
```

Do **not** mix Track 2 into clearing `parse_result_json`. CRM keeps schema v1 keys only.

---

## Phase 4 — Path A integration

**Goal:** Upload PDF in clearing → auto message, fee hint, output docs.

| Step | Status | Notes |
|------|--------|-------|
| 4.1 Schema v1 | ✅ | `parser_schema.py`, `extraction_schema.py` |
| 4.2 CRM client | ✅ | `clearing/services/pdf_manager_client.py` |
| 4.3 Upload UI | ✅ | `clearing.html` parse button |
| 4.4 PA snapshot | ✅ | `parse_upload.py` |
| 4.5 Client message | ✅ | Gated on `message_ready` |
| 4.6 Output PDFs | ✅ | Proxy download via clearing views |
| 4.7 Failure → Path B | ✅ | `ParseUploadError`; manual clearing unchanged |
| 4.8 Parser DB boundary | ✅ | CRM stores refs + snapshot only |

**Exit criteria (from `ROADMAP.md`):** Path A works for at least one Drake template; Path B still available.

**Remaining:** Formal beta validation (checklist below). Optionally mark Phase 4 complete in `ROADMAP.md` after smoke tests.

---

## Phase 5 — Quality & speed (backlog)

**Goal:** p95 sync parse &lt;5s; schema v1 stable; no CRM contract churn.

| Step | Status | Action when resuming |
|------|--------|----------------------|
| 5.1 Text-first extraction | ✅ | PyMuPDF before OCR on extract roles |
| 5.2 OCR fallback | ✅ | Client Letter, BILL when no text layer |
| 5.3 Field registry in parser DB | ✅ | DRAKE template seed, `ExtractedField` lineage |
| 5.4 Debug / TODO cleanup | ☐ | Remove or gate `__debug_*` in `field_extraction_regex.py`; review `ui/api.py` TODOs |
| 5.5 Benchmark + queue | Partial | S-corp benchmark test only; add personal sample; queue if p95 &gt;5s on droplet |
| 5.6 Worker replicas | ☐ | Optional Compose scaling for peak season |

**Exit criteria:** Majority of text-native PDFs &lt;5s; schema v1 stable.

### Known non-goals (v1)

Documented in `PARSER_EXTRACTION.md`:

- `filing_type`, `product`, `preparer` from PDF
- Comparison / Diagnostic KPIs (Track 2)

### Ack hints backlog (workflow W2)

Feeds `ProductAssignment.expected_ack_count` at **Review Complete** (`docs/PRODUCT_ASSIGNMENT_WORKFLOW.md`).

| Priority | PDF source | Registry role | Proposed fields |
|----------|------------|---------------|-----------------|
| 1 | Client Letter — return type / filed docs table | `extract_client_letter` | `expected_transmissions[]`, `expected_ack_count` | ✅ |
| 2 | Diagnostic Summary — state filing list | `extract_diagnostic_invoice` | `state_filings[]` (merge into transmissions) | ✅ |
| 3 | BILL_01 pages 1–2 — form index | `extract_bill`, `extract_bill_fee` | Supplement count when letter incomplete | ✅ |

Text-first on Client Letter; OCR only if no text layer. CRM stores snapshot on `parse_result_json`; staff can override in Review Complete modal.

### Open code TODOs

| Location | Item |
|----------|------|
| `field_extraction_regex.py` | `__debug_*` fields when debug enabled |
| `pdf_manager/apps/ui/api.py` | Auto-download three packets; refactor `job_output_api()` |
| `tests/test_ingestion.py` | Dev-only parse patch comment |

---

## Resume checklist — Path A beta smoke test

**Full checklist:** `docs/PATH_A_TESTING.md` (includes global upload). Quick list:

Run on **beta droplet** or local Compose when resuming. Skip during pause is OK if Path B is the operational default.

- [ ] **Personal + TPG** — message auto-fills, `has_tpg_pages` → payment method TPG, fee from `TPG_INFO`
- [ ] **Personal + non-TPG** — fee from Diagnostic Summary invoice block
- [ ] **S-corp** — fee from `BILL_01 page 2`; message ready
- [ ] **Output PDFs** — main packet, signature, payment voucher (when applicable) download from clearing row
- [ ] **Parse failure** — bad PDF → error message; staff can complete via Path B
- [ ] **Timing** — upload feels &lt;5s p95 on target hardware (Track 1 only)
- [ ] **Watermarked PDF** — spot-check one watermarked sample if used in prod

---

## Test commands

From repo root (Compose running) or `pdf_manager` with Django env:

```bash
# Unit tests (no sample PDFs required)
docker compose exec pdf_web pytest pdf_manager/tests/test_tin_extraction.py pdf_manager/tests/test_extraction_schema.py pdf_manager/tests/test_ack_hints.py pdf_manager/tests/test_drake_registry.py pdf_manager/tests/test_fee_extraction.py pdf_manager/tests/test_parsejob_status.py -q

# CRM Path A integration (mocked parser)
docker compose exec crm_web python manage.py test clearing.tests.test_clearing_phase4 -v 2

# Corpus tests (require fixtures/drake_samples/*.pdf on disk)
docker compose exec pdf_web pytest pdf_manager/tests/test_parser_corpus.py pdf_manager/tests/test_parser_benchmark.py -q
```

**Sample PDFs:** `pdf_manager/fixtures/drake_samples/` (8 Drake samples; may be gitignored in some clones).

**Corpus audit report:** `pdf_manager/fixtures/drake_samples_reports/corpus_audit.json` (text-layer findings).

**Benchmark budget:** `PARSER_BENCHMARK_MAX_SECONDS` (default `5.0`).

---

## Key files

### pdf_manager (parser service)

| Path | Purpose |
|------|---------|
| `apps/parser/facade.py` | Parse orchestration |
| `apps/parser/strategies/field_extraction_regex.py` | Schema v1 extraction |
| `apps/parser/extraction_schema.py` | Field catalog, `finalize_extracted_fields` |
| `apps/parser/message_builder.py` | Client message template |
| `apps/parser/packet_builder.py` | Main / signature / voucher packets |
| `apps/parser/drake_registry.py` | Outline registry loader |
| `fixtures/drake_samples/outline_registry.yaml` | Page roles + OCR policy |
| `apps/core/field_persistence.py` | `ExtractedField` rows per job |

### pdk_crm (clearing integration)

| Path | Purpose |
|------|---------|
| `clearing/services/parse_upload.py` | Apply parse result to PA |
| `clearing/services/parser_schema.py` | CRM snapshot contract |
| `clearing/services/pdf_manager_client.py` | HTTP client to parser |
| `clearing/views.py` | Upload + download endpoints |
| `clearing/templates/clearing/clearing.html` | Path A UI |

---

## Environment (Compose defaults)

| Variable | Service | Purpose |
|----------|---------|---------|
| `PDF_MANAGER_BASE_URL` | `crm_web` | Parser API base (e.g. `http://pdf_web:8000`) |
| `OCR_ENABLED` | `pdf_web` | Client Letter OCR |
| `PARSER_BENCHMARK_MAX_SECONDS` | `pdf_web` | Corpus timing budget |

See `compose.yaml`, `docs/LOCAL_DEV.md`, `docs/CLOUD_BETA.md`.

---

## Thread prompts (copy-paste)

**Resume clearing parser / Phase 5 only:**

> Continue parser Phase 4–5 per `docs/PARSER_ROADMAP.md`, `docs/PATH_A_TESTING.md`, and `docs/PATH_A_PDF_UPLOAD.md`. Do not implement analytics Track 2.

**Implement global upload + Path A testing:**

> Implement `docs/PATH_A_PDF_UPLOAD.md` and validate with `docs/PATH_A_TESTING.md`. Add `taxpayer_tin` to schema v1. KPI/Track 2 out of scope.

**Start analytics parser (Track 2):**

> Implement `docs/ANALYTICS_ROADMAP.md` phase A1 per `docs/RETURN_ANALYTICS.md`. Track 1 clearing contract unchanged.

**Fix a specific extraction miss:**

> Debug parser extraction for [field] per `docs/PARSER_EXTRACTION.md`. Corpus sample: [filename]. Keep schema v1 CRM contract stable.

---

## When to resume which track

| Trigger | Resume |
|---------|--------|
| Beta/demo needs PDF upload clearing | Track 1 + smoke checklist |
| Slow parses on droplet | Phase 5.5–5.6 |
| Extraction misses on real returns | Field rules in `field_extraction_regex.py` + corpus tests |
| Shareholder / executive analytics | Track 2 — `ANALYTICS_ROADMAP.md` A1 (after Track 1 stable) |

---

## Revision history

| Version | Date | Notes |
|---------|------|-------|
| 1.0 | 2025-06-06 | Initial pause/resume handoff doc |
