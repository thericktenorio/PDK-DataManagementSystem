# Analytics feature roadmap

Phased plan for **return-level facts**, **executive reporting**, and **shareholder analytics** on the existing `analytics` PostgreSQL warehouse.

**Not a replacement for `ROADMAP.md`.** Cross-cutting product phases (clearing, billing, deploy) stay in the main roadmap. This document sequences analytics-only work.

See also:

| Doc | Purpose |
|-----|---------|
| `docs/ANALYTICS.md` | Warehouse operations today (ETL, env, Track A/B access) |
| `docs/RETURN_ANALYTICS.md` | Technical spec: fields, tables, parser contract, PII rules |
| `docs/PARSER_EXTRACTION.md` | Clearing schema v1 (Path A message/fee) |
| `docs/PARSER_ROADMAP.md` | Parser pause/resume, Phase 4–5 backlog (Track 1) |
| `docs/POWER_BI.md` | Track B Power BI runbook (deferred on Mac) |
| `ROADMAP.md` | Phase 9 (foundation done), Phase 10 (prod hardening) |

---

## Design principles (fixed)

1. **Operations and analytics are separated.** Preparers use `tax_operations` + clearing. Shareholders and managers query **`analytics` only** at report time — never live `tax_operations` or `parser` DB.
2. **Parser produces facts; ETL moves them.** Rich return data lives in **parser DB** first, then batch-syncs to the warehouse. CRM keeps a **slim** `parse_result_json` (schema v1 clearing fields only).
3. **Clearing must stay fast.** Schema v1 (message, fee, packets) is **Track 1 (sync)**. Return profile + Comparison KPIs are **Track 2 (async)** — same upload, deferred worker.
4. **One warehouse, multiple surfaces.** Track A (in-app), Track B (Power BI / deep executive), Track C (AI agent) all read the same `analytics` DB via `bi_*` views.
5. **Coverage is honest.** Path B (no PDF), failed Track 2, or missing outline pages → NULL facts. Dashboards and agents must show **parsed count / total count**.

---

## Track definitions

```text
                    ┌─────────────────────────────────────┐
                    │  analytics (PostgreSQL warehouse)    │
                    └─────────────────┬───────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          ▼                           ▼                           ▼
    Track A                     Track B                     Track C
    In-app /analytics/          Power BI / LAN BI           Shareholder AI agent
    Light ops KPIs              Deep executive reports      Natural language + charts
    Manager / Owner             Owner / external execs      Owner (primary shareholders)
```

| Track | Audience | Data depth | Status |
|-------|----------|------------|--------|
| **A** | Manager, owner, developer | Lifecycle, revenue, collection, parser-assisted count | ✅ MVP done |
| **B** | Owners, executives | Return-level Comparison, YoY, Sch C/E aggregates, PII-enriched dims | Planned (A2–A4) |
| **C** | Primary shareholders | Text-to-SQL on `bi_*` views, visual summaries | Planned (A5) |

**Return-level analytics (Comparison, return profile, agent) is primarily Track B/C.** Track A may add a few headline widgets (e.g. median AGI, refund mix) once A2 data exists — keep A light.

---

## Prerequisites

**Path A clearing (Track 1)** must be signed off per `docs/PATH_A_TESTING.md` before starting **A1** (Track 2 parser). KPI extraction is not part of Path A testing.

---

## Phase overview

```text
A0  Foundation (done)     warehouse, ETL from CRM, Track A dashboard
A1  Async parser Track 2  deferred extraction → parser DB
A2  Return facts ETL      fact_return_* tables, bi_* views, 9.1b
A3  Track A enrichment    optional summary KPIs on /analytics/
A4  Track B executive     Power BI semantic model / deep reports
A5  Shareholder AI agent  governed queries + charts on analytics only
```

| Phase | Depends on | Parser touch | CRM touch | Ops strain |
|-------|------------|--------------|-----------|------------|
| A0 | — | — | ETL reads PA rows | None at query time |
| A1 | Phase 5 v1 stable | Queue + extractors | `parse_job_uuid` only | +0s clearing wait (async) |
| A2 | A1 | ETL pulls parser API/DB | None at query time | ETL worker only |
| A3 | A2 | — | Dashboard template | None |
| A4 | A2 | — | — | BI refresh schedule |
| A5 | A2 + views | — | New `/analytics/` agent UI | LLM + analytics DB |

---

## A0 — Foundation ✅ (done)

**Goal:** Reporting without touching `tax_operations` during peak.

**Delivered:** `analytics_db`, `dim_*` / `fact_*`, `sync_analytics_warehouse`, `analytics_etl` worker, `/analytics/` dashboard, `bi_*` views, `docs/ANALYTICS.md`.

**Grain:** `fact_assignment` (one row per ProductAssignment).

**Parser hints on assignment (from CRM snapshot only):** `parser_federal_amount`, `parser_states`, `parser_tax_prep_fee`, `has_parser_snapshot`.

**Exit criteria:** Met — see `ROADMAP.md` Phase 9.

---

## A1 — Async parser Track 2

**Goal:** On PDF upload, extract return-level facts **without** extending clearing wait or blocking Path A.

### Flow

```text
Clearing upload (Path A)
    │
    ▼
pdf_manager parse job
    │
    ├─ Track 1 (sync) ──▶ packets + schema v1 fields + CRM snapshot
    │                     preparer sees message/fee/downloads
    │
    └─ Track 2 (async) ─▶ queue worker
                          Comparison, Diagnostic, Sch C/E (when present)
                          persist to parser DB only
                          job.track2_status = PENDING → DONE | FAILED
```

### Steps

| Step | Action |
|------|--------|
| A1.1 | Add `track2_status` (or equivalent) on parser `ParseJob` |
| A1.2 | Track 1 returns after packets + v1 fields; enqueue Track 2 task |
| A1.3 | Compose worker or Celery/RQ worker for Track 2 (same repo pattern as `analytics_etl`) |
| A1.4 | New registry roles: `extract_comparison`, `extract_return_profile` (Diagnostic + forms) |
| A1.5 | Schema v2 catalog in parser (`RETURN_ANALYTICS.md`) — **not** in CRM snapshot |
| A1.6 | Persist to `ExtractedField` + optional JSON blobs (`comparison_json`, `return_profile_json`) |
| A1.7 | Parser API: `GET /jobs/{id}/return_facts` for ETL consumption |
| A1.8 | Corpus tests: personal + S-corp Comparison; Diagnostic; optional Sch C/E samples |
| A1.9 | Document failure semantics: clearing success even when Track 2 fails |

### Exit criteria

- Upload → clearing message/fee in &lt;5s p95 (Track 1 only).
- Track 2 completes within N minutes for corpus samples.
- Parser DB has Comparison + return profile for ≥1 personal and ≥1 S-corp sample.
- CRM `parse_result_json` unchanged (schema v1 keys only).

### Out of scope

- Analytics warehouse tables (A2).
- AI agent (A5).

**Spec:** `docs/RETURN_ANALYTICS.md` § Parser Track 2.

---

## A2 — Return facts warehouse (Phase 9.1b)

**Goal:** Batch-load parser return facts into `analytics` for executive queries. **No runtime dependency on ops DB.**

### Steps

| Step | Action |
|------|--------|
| A2.1 | Add `fact_return_comparison` (1 row per PA with parsed Comparison) |
| A2.2 | Add `fact_return_profile` (Diagnostic + form detail: DOB, dependents, Sch C/E, etc.) |
| A2.3 | Optional `dim_dependent` (normalized dependents; PII-sensitive) |
| A2.4 | SQL views: `bi_return_comparison`, `bi_return_profile`, `bi_return_metrics` (join assignment + client) |
| A2.5 | Extend ETL: for PAs with `parse_job_uuid` + Track 2 DONE, pull parser return facts |
| A2.6 | ETL watermark: `parser_return_facts` cursor (by `parsed_at` or job id) |
| A2.7 | `fact_assignment` flags: `has_return_comparison`, `has_return_profile`, `track2_status` |
| A2.8 | Tests: ETL fixture with mock parser response |
| A2.9 | Update `docs/ANALYTICS.md` warehouse table list |

### Exit criteria

- `sync_analytics_warehouse --full` populates return facts for parsed PAs.
- Shareholder-style SQL (e.g. `AVG(agi_current)`) runs on `bi_return_metrics` without touching `tax_operations`.
- ETL banner still shows `EtlRun.finished_at`.

### Out of scope

- Power BI `.pbix` (A4).
- Agent UI (A5).

**Spec:** `docs/RETURN_ANALYTICS.md` § Warehouse schema + ETL.

---

## A3 — Track A enrichment (optional)

**Goal:** A few headline return KPIs on existing `/analytics/` — not a full executive suite.

### Candidate widgets

- Parsed return coverage (% with Comparison data).
- Median AGI / taxable income (current season).
- Refund vs balance-due mix (federal).
- Share of returns with Schedule C / Schedule E (from profile flags).

### Steps

| Step | Action |
|------|--------|
| A3.1 | Extend `analytics/selectors.py` with return-metric aggregates |
| A3.2 | Add cards to `analytics/analytics.html` |
| A3.3 | Show “based on N parsed returns” disclaimer |

### Exit criteria

- Dashboard loads from `analytics` DB only; no new ops queries.

---

## A4 — Track B executive reporting

**Goal:** Deep executive reporting for owners — Power BI or equivalent on LAN.

### Steps

| Step | Action |
|------|--------|
| A4.1 | Prod `analytics_reader` role (see `docs/ANALYTICS.md`) |
| A4.2 | Power BI semantic model over `bi_return_*` + `bi_assignments` |
| A4.3 | Standard report pages: YoY AGI, revenue vs tax burden, Sch C/E practice mix |
| A4.4 | Office gateway / Import refresh per `docs/POWER_BI.md` |
| A4.5 | PII policy: masked TIN in reports; LAN-only |

### Exit criteria

- Owner can refresh executive workbook without CRM or parser access.
- Reports label ETL as-of date.

**Deferred on:** Mac dev (use in-app Track A + future agent); office Windows / gateway for Power BI Desktop.

---

## A5 — Shareholder AI agent (Track C)

**Goal:** Primary shareholders ask natural-language questions; system answers from **analytics warehouse only** with charts.

### Architecture

```text
Owner question → Agent (owner role)
    → Intent + SQL against bi_* views (read-only)
    → Execute on analytics_db
    → Summarize + chart (Vega / Chart.js)
    → Audit log (query hash, user, timestamp)
```

### Guardrails (required)

| Rule | Implementation |
|------|----------------|
| No ops DB | Agent DB connection = `analytics` only |
| No live parser | Never re-parse PDFs for a question |
| Aggregates default | Row-level PII only on explicit drill-down |
| TIN masking | `***-**-6789` in UI and prompts |
| Coverage disclaimer | “Based on N of M returns with parsed data” |
| Staleness | Show last ETL time |
| Role gate | `owner` (and optionally `manager`); not preparers |

### Steps

| Step | Action |
|------|--------|
| A5.1 | `bi_*` view catalog + column descriptions (agent system context) |
| A5.2 | `/analytics/ask/` or dedicated agent view |
| A5.3 | Text-to-SQL with allowlisted views only |
| A5.4 | Chart renderer from tabular result |
| A5.5 | Query audit table in `analytics` |
| A5.6 | Rate limits + cost controls (LLM API) |

### Exit criteria

- Sample questions (“average AGI by filing status”, “% balance due &gt; $5k”) return correct aggregates.
- Agent cannot `SELECT` from `tax_operations` or parser schemas.

### Out of scope (v1 agent)

- Ad-hoc PDF upload in agent.
- Real-time (sub-ETL-interval) answers.
- Preparer-facing copilot.

---

## Dependencies on other roadmap phases

| External phase | Relationship |
|----------------|--------------|
| **Phase 5** (parser speed) | Track 1 must stay &lt;5s before A1 ships |
| **Phase 4** (Path A) | `parse_job_uuid` on PA required for ETL linkage |
| **Phase 3** (Path B) | Manual clearing → no return facts (expected) |
| **Phase 10** (prod) | `analytics_reader`, firewall, backups for A4 |
| **Phase 9.5** (Power BI) | Absorbed into A4 |

---

## Recommended thread split (implementation)

Use this roadmap as the handoff doc for focused dev threads:

| Thread | Phase | Deliverable |
|--------|-------|-------------|
| 1 | A1 | Parser async Track 2 + Comparison/Diagnostic extractors |
| 2 | A2 | Warehouse models + ETL 9.1b + `bi_return_*` views |
| 3 | A3 | Optional Track A dashboard cards |
| 4 | A4 | Power BI / executive workbook |
| 5 | A5 | Shareholder AI agent |

---

## Success metrics

| Metric | Target |
|--------|--------|
| Clearing p95 (Track 1 only) | &lt;5s (unchanged) |
| Track 2 completion | &lt;5 min p95 off-peak |
| Parsed coverage | Track in dashboard (“N/M returns”) |
| Shareholder query load on ops | **Zero** at query time |
| ETL failure visibility | `EtlRun` + alerts on `analytics_etl` logs |

---

## Open decisions (resolve in implementation threads)

1. **Queue technology:** Django-Q, RQ, Celery, or parser-side polling worker (match `analytics_etl` pattern).
2. **ETL transport:** Parser HTTP API vs read-only cross-DB connection (prefer API for boundary).
3. **Dependent storage:** JSONB on `fact_return_profile` vs normalized `dim_dependent`.
4. **PII retention:** Season-scoped purge vs indefinite in warehouse (legal/policy).
5. **Agent LLM:** Hosted API vs local (beta droplet constraints).

Document resolutions in `RETURN_ANALYTICS.md` or ADR when decided.
