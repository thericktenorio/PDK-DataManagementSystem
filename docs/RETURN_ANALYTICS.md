# Return-level analytics spec

Technical source of truth for **parser Track 2 (async)** extraction and **analytics warehouse** tables for Comparison, return profile, and executive KPIs.

**Roadmap / sequencing:** `docs/ANALYTICS_ROADMAP.md` (phases A1–A5).

**Clearing extraction (unchanged):** `docs/PARSER_EXTRACTION.md` schema v1. **Track 1 backlog:** `docs/PARSER_ROADMAP.md`.

---

## Scope

### In scope

- Full **Comparison** page metrics (YoY table).
- **Return profile** from Diagnostic Summary + targeted form pages (1040 context, Sch C, Sch E).
- Parser persistence, ETL into `analytics`, `bi_*` views for Track B/C.
- PII handling rules for warehouse and agent.

### Out of scope (v1)

- Every worksheet cell in the PDF.
- Real-time analytics (batch ETL only).
- Querying `tax_operations` or `parser` at report/agent runtime.
- Storing full return profile on `ProductAssignment.parse_result_json`.
- Path B manual clearing without PDF.

---

## End-to-end data flow

```text
Staff uploads PDF (Path A, clearing)
        │
        ▼
┌───────────────────────────────────────────────────┐
│  pdf_manager parse job                             │
│  Track 1 (sync):  v1 fields, packets, message      │──▶ CRM parse_result_json (slim)
│  Track 2 (async): return facts                     │──▶ parser DB only
└───────────────────────────────────────────────────┘
        │
        │  batch ETL (analytics_etl worker)
        ▼
┌───────────────────────────────────────────────────┐
│  analytics warehouse                               │
│  fact_return_comparison, fact_return_profile, …    │
│  bi_return_* views                                 │
└───────────────────────────────────────────────────┘
        │
        ├─▶ Track A: optional headline KPIs (/analytics/)
        ├─▶ Track B: Power BI / executive reports
        └─▶ Track C: shareholder AI agent (SQL on bi_* only)
```

**Linkage:** `ProductAssignment.parse_job_uuid` → parser job → return facts in ETL.

---

## Parser: Track 1 vs Track 2

| | Track 1 (sync) | Track 2 (async) |
|--|----------------|-----------------|
| **Purpose** | Clearing: message, fee, packets | Executive / return analytics |
| **Schema** | v1 (`PARSER_EXTRACTION.md`) | v2 (this doc) |
| **CRM snapshot** | Yes (`parse_result_json.fields`) | **No** |
| **Parser DB** | Yes | Yes |
| **Blocks preparer** | Yes (must finish for upload UX) | **No** |
| **OCR** | Client Letter, BILL (as today) | **Avoid** — embedded text pages only |
| **Failure** | Upload error / Path B fallback | Log + `track2_status=FAILED`; clearing stands |

### Track 2 job states

```text
PENDING → RUNNING → DONE
                 └→ FAILED
```

Expose on parser `ParseJob` and mirror summary flags on `fact_assignment` after ETL.

---

## Drake page sources

Corpus audit (8 samples): form and summary pages have **embedded PyMuPDF text**; OCR is not required for Track 2.

| Page (outline title) | Role (proposed) | Text | Primary use |
|----------------------|-----------------|------|-------------|
| `Comparison`, `Comparison page 2` | `extract_comparison` | Embedded | Full YoY KPI table |
| `Diagnostic Summary` | `extract_return_profile` | Embedded | DOB, address, dependents, federal/state summary |
| `1040`, `1040 Page 2` | `extract_form_1040` | Embedded | Filing status, line-level fallback |
| `Schedule C (...)` | `extract_schedule_c` | Embedded | Business type, gross/net |
| `Schedule E (...)` | `extract_schedule_e` | Embedded | Property count, gross/net rental |
| `TAX_COMP` | `extract_tax_comp` | Embedded | Line 16 tax validation (optional) |
| `1120S`, … | `extract_form_1120s` | Embedded | Entity returns (S-corp variant) |

**S-corp note:** Comparison layout differs (extra page 2). Parser selects variant by outline titles / return type detected on Diagnostic.

---

## Schema v2 — field catalog

Bump parser `SCHEMA_VERSION` to **2** for Track 2 catalog. CRM clearing stays at **v1**.

### Comparison (`comparison_json` + normalized fields)

Store full table as JSON; also map headline metrics to typed `ExtractedField` keys for ETL.

**Metadata**

| Key | Type | Source |
|-----|------|--------|
| `comparison.tax_year` | int | Page header |
| `comparison.taxpayer_name` | string | Page footer |
| `comparison.taxpayer_tin` | string | Identifying number (PII) |
| `comparison.filing_status` | string | Labeled row |
| `comparison.num_dependents` | int | Labeled row |

**Per-metric YoY structure**

Each metric row from Comparison (labels vary slightly by return type):

| Metric key (examples) | Labels on page | Years |
|-----------------------|----------------|-------|
| `total_income` | Total Income | 2022, 2023, 2024 |
| `agi` | Adjusted Gross Income | … |
| `taxable_income` | Taxable Income | … |
| `total_tax` | Total Tax | … |
| `refund` | Refund | … |
| `balance_due` | Balance Due | … |
| `effective_tax_rate` | Effective tax rate | … |
| `marginal_tax_rate` | Marginal tax rate | … |
| `wages` | Wages, salaries, tips | … |
| `business_income` | Business income (loss) | … |
| `rental_income` | Rent and royalty income (loss) | … |
| `standard_deduction` | Standard deduction | … |
| `itemized_deductions` | Total itemized deductions | … |

**JSON shape (parser DB)**

```json
{
  "tax_year": 2024,
  "taxpayer_name": "JOHN & JANE DOE",
  "taxpayer_tin": "123-45-6789",
  "filing_status": "Married Joint",
  "num_dependents": 1,
  "rows": [
    {
      "key": "agi",
      "label": "Adjusted Gross Income",
      "y2022": 139600,
      "y2023": 154869,
      "y2024": 154869,
      "delta_2023_2024": 0
    }
  ]
}
```

Persist as:

- `ExtractedField` key `comparison_json` (JSON text), or dedicated JSON column on `ParseJob`.
- Optional typed keys: `comparison.agi_2024`, `comparison.refund_2024`, etc.

### Return profile (`return_profile_json` + normalized fields)

**Taxpayer / spouse (Diagnostic Summary)**

| Key | Type | PII |
|-----|------|-----|
| `profile.tax_year` | int | |
| `profile.form_type` | string | e.g. `1040`, `1120S` |
| `profile.filing_status` | string | |
| `profile.taxpayer_dob` | date | Yes |
| `profile.spouse_dob` | date | Yes |
| `profile.mailing_address_line1` | string | Yes |
| `profile.mailing_city` | string | |
| `profile.mailing_state` | string | |
| `profile.mailing_zip` | string | |
| `profile.resident_state` | string | |

**Federal summary (Diagnostic — current year column)**

| Key | Type |
|-----|------|
| `profile.total_income` | decimal |
| `profile.agi` | decimal |
| `profile.deductions` | decimal |
| `profile.taxable_income` | decimal |
| `profile.tax_before_credits` | decimal |
| `profile.tax_after_credits` | decimal |
| `profile.refund` | decimal |
| `profile.balance_due` | decimal |
| `profile.deduction_type` | enum | `standard` / `itemized` / `unknown` |
| `profile.standard_deduction_amount` | decimal |
| `profile.itemized_deduction_amount` | decimal |

**Dependents (array)**

| Key | Type | PII |
|-----|------|-----|
| `profile.dependents[]` | array | |
| `profile.dependents[].name` | string | |
| `profile.dependents[].tin` | string | Yes |
| `profile.dependents[].relationship` | string | |
| `profile.dependents[].dob` | date | Yes |
| `profile.dependents[].qualifying_child_credit` | bool | |

**Schedule C (when outline present)**

| Key | Type |
|-----|------|
| `profile.has_schedule_c` | bool |
| `profile.sch_c_business_name` | string |
| `profile.sch_c_business_code` | string | NAICS / principal code if present |
| `profile.sch_c_gross_income` | decimal |
| `profile.sch_c_net_profit` | decimal |

**Schedule E (when outline present)**

| Key | Type |
|-----|------|
| `profile.has_schedule_e` | bool |
| `profile.sch_e_property_count` | int | Count Part I property rows |
| `profile.sch_e_gross_rents` | decimal |
| `profile.sch_e_net_income` | decimal |

**State summary (Diagnostic grid — repeatable)**

| Key | Type |
|-----|------|
| `profile.states[]` | array |
| `profile.states[].code` | string | e.g. `CA`, `NY` |
| `profile.states[].agi` | decimal |
| `profile.states[].taxable_income` | decimal |
| `profile.states[].tax` | decimal |
| `profile.states[].refund_or_balance` | decimal | negative = refund |

---

## Analytics warehouse schema (proposed)

Grain: **one row per ProductAssignment** where Track 2 succeeded (nullable for unparsed).

### `fact_return_comparison`

| Column | Type | Notes |
|--------|------|-------|
| `source_pa_id` | PK/FK | Unique |
| `source_client_id` | int | |
| `tax_season_year` | int | |
| `parse_job_id` | uuid | |
| `return_type` | varchar | `1040`, `1120S`, … |
| `filing_status` | varchar | |
| `num_dependents` | smallint | |
| `agi_2022` … `agi_2024` | decimal | Headline columns for SQL |
| `taxable_income_2024` | decimal | |
| `total_tax_2024` | decimal | |
| `refund_2024` | decimal | |
| `balance_due_2024` | decimal | |
| `effective_rate_2024` | decimal | |
| `marginal_rate_2024` | decimal | |
| `agi_delta_2023_2024` | decimal | |
| `comparison_full_json` | jsonb | Full Comparison table |
| `extracted_at` | timestamptz | From parser |
| `etl_synced_at` | timestamptz | |

### `fact_return_profile`

| Column | Type | Notes |
|--------|------|-------|
| `source_pa_id` | PK | Unique |
| `source_client_id` | int | |
| `tax_season_year` | int | |
| `parse_job_id` | uuid | |
| `taxpayer_dob` | date | PII |
| `spouse_dob` | date | PII |
| `mailing_zip` | varchar | |
| `mailing_state` | varchar | |
| `resident_state` | varchar | |
| `deduction_type` | varchar | |
| `standard_deduction_amount` | decimal | |
| `itemized_deduction_amount` | decimal | |
| `has_schedule_c` | bool | |
| `sch_c_gross_income` | decimal | |
| `sch_c_net_profit` | decimal | |
| `sch_c_business_name` | varchar | |
| `has_schedule_e` | bool | |
| `sch_e_property_count` | smallint | |
| `sch_e_net_income` | decimal | |
| `dependents_json` | jsonb | Array; PII |
| `states_json` | jsonb | State grid |
| `profile_full_json` | jsonb | Complete parser payload |
| `extracted_at` | timestamptz | |
| `etl_synced_at` | timestamptz | |

### `fact_assignment` extensions

| Column | Type |
|--------|------|
| `has_return_comparison` | bool |
| `has_return_profile` | bool |
| `parser_track2_status` | varchar | `PENDING`, `DONE`, `FAILED`, null |

### SQL views (Track B / C)

| View | Purpose |
|------|---------|
| `bi_return_comparison` | Comparison facts + client name + season |
| `bi_return_profile` | Profile facts + assignment lifecycle |
| `bi_return_metrics` | Join comparison + profile + `fact_assignment` revenue fields — **primary agent view** |
| `bi_return_coverage` | Season-level parsed counts |

**Agent allowlist:** `bi_return_metrics`, `bi_return_coverage`, `bi_assignments`, `bi_seasons`, `bi_last_etl` only.

---

## ETL contract (9.1b)

### Source

- **CRM:** `ProductAssignment.parse_job_uuid`, `parsed_at`, `parser_status`.
- **Parser:** `GET /api/jobs/{uuid}/return_facts/` (proposed) returning:

```json
{
  "job_id": "…",
  "track2_status": "DONE",
  "schema_version": 2,
  "comparison": { },
  "return_profile": { },
  "extracted_at": "2025-11-11T12:00:00Z"
}
```

Prefer **HTTP API** over cross-DB read to preserve service boundaries.

### Incremental logic

1. Select PAs where `parse_job_uuid` is set and (`parsed_at` &gt; watermark OR `has_return_comparison` is false).
2. Fetch parser return facts when `track2_status=DONE`.
3. Upsert `fact_return_comparison`, `fact_return_profile`, update `fact_assignment` flags.
4. Skip PAs with `track2_status` in (`PENDING`, `RUNNING`) — retry next ETL run.

### Error handling

- Parser 404 / FAILED → set flags; do not block assignment ETL.
- Log row-level errors on `EtlRun` (extend metadata if needed).

---

## PII and security

| Data class | Warehouse | Agent UI | BI export |
|------------|-----------|----------|-----------|
| Client name | `dim_client` | Show | LAN only |
| TIN / SSN | Store masked hash optional; full in jsonb restricted | Mask default | Avoid |
| DOB | `fact_return_profile` | Aggregate only | Avoid |
| Dependent TIN | `dependents_json` | No default drill-down | No |
| Address | Zip/state for aggregates; full line in jsonb | No default | No |

**Rules**

- Analytics DB not exposed to internet (`docs/ANALYTICS.md`).
- Shareholder agent: **read-only** `analytics` role; query allowlist.
- Audit log for agent SQL (phase A5).
- Retention policy TBD (open decision in `ANALYTICS_ROADMAP.md`).

---

## Parser API and CRM boundaries

### CRM `parse_result_json` (unchanged v1 keys)

```text
taxpayer_first_name, tax_year, federal_amount, states, tax_prep_fee,
has_tpg_pages, mailing_*, …
```

Optional future CRM flags only (not full profile):

- `has_return_facts_pending: true` — UI badge for “analytics processing”

### Parser template catalog

Extend `DRAKE` template `rules_json.field_catalog` with tier `executive` / Track 2 entries. Seed migration similar to `0008_phase5_extracted_field_lineage.py`.

---

## Extraction implementation notes

### Comparison parser

1. Locate page by outline role `extract_comparison`.
2. `page.get_text("text")` via PyMuPDF.
3. Parse header year, row labels, numeric columns (2022/2023/2024/delta).
4. Map known labels → canonical metric keys; unknown labels → `rows[]` with raw `label`.

### Return profile parser

1. Diagnostic Summary: structured block parsing (Return Information table).
2. Dependents: table under “Dependent Information”.
3. Sch C / Sch E: only if outline titles match; count Sch E properties by row pattern.

### Tests

| Test | Location (proposed) |
|------|---------------------|
| Comparison unit (fixture text) | `pdf_manager/tests/test_comparison_extraction.py` |
| Profile unit (Diagnostic fixture) | `pdf_manager/tests/test_return_profile_extraction.py` |
| Track 2 async integration | `pdf_manager/tests/test_track2_async.py` |
| ETL parser pull | `pdk_crm/analytics/tests/test_return_facts_etl.py` |

Corpus PDFs: `pdf_manager/fixtures/drake_samples/`.

---

## Performance budgets

| Stage | Budget |
|-------|--------|
| Track 1 (clearing) | p95 &lt; 5s (unchanged) |
| Track 2 (async) | p95 &lt; 5 min off-peak |
| Comparison extract | &lt; 500ms (embedded text, 1–2 pages) |
| Full profile + Sch C/E | &lt; 2s typical |
| ETL return facts | Incremental; &lt; 1s per PA (API fetch) |

---

## Coverage expectations

| Scenario | Return facts |
|----------|--------------|
| Path A + PDF with Comparison | Yes (when Track 2 DONE) |
| Path A, Track 2 failed | No; clearing still valid |
| Path B manual | No |
| S-corp | Yes with variant parser |
| Missing Sch C/E in PDF | `has_schedule_* = false`; other fields populated |

Dashboards and agent must display: **“Metrics based on {n} returns with parsed data of {m} total assignments.”**

---

## File touch list (implementation reference)

| Area | Files / modules |
|------|-----------------|
| Parser registry | `pdf_manager/fixtures/drake_samples/outline_registry.yaml` |
| Parser schema | `pdf_manager/apps/parser/extraction_schema.py` |
| Track 2 worker | TBD: `pdf_manager/apps/parser/track2_worker.py` or Compose service |
| Parser API | `pdf_manager` job detail endpoint |
| CRM ETL | `pdk_crm/analytics/services/etl.py` |
| Warehouse models | `pdk_crm/analytics/models.py` |
| Views | `pdk_crm/analytics/migrations/*_bi_return_*.py` |
| Agent (A5) | `pdk_crm/analytics/` new views + services |

---

## Revision history

| Version | Date | Notes |
|---------|------|-------|
| 1.0 | 2025-06-06 | Initial spec: Track 2 async, Comparison + return profile, warehouse + ETL contract |
