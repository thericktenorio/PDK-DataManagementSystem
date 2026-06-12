# Analytics reference (Track A / B / C)

Quick reference for KPI sources, warehouse fields, agent views, and infra. Operational detail: `docs/ANALYTICS.md`. Return-level spec: `docs/RETURN_ANALYTICS.md`. Roadmap: `docs/ANALYTICS_ROADMAP.md`.

**Data freshness:** All figures are as of the **last successful ETL run** (`EtlRun.finished_at`), not live `tax_operations`.

---

## Track overview

| Track | Surface | Audience | Data depth | Charts today | Status |
|-------|---------|----------|------------|--------------|--------|
| **A** | `/analytics/` in-app dashboard | Manager, owner, developer | Lifecycle, revenue, collection, parser snapshot count | No (tables + KPI cards) | MVP done |
| **B** | Power BI / LAN BI on `bi_*` views | Owner, executives | Return-level Comparison, YoY, Sch C/E | Yes (Power BI) | Planned (A2–A4) |
| **C** | Shareholder agent panel on `/analytics/` | Owner, developer | Natural language SQL on `bi_*` | Yes (Chart.js per question) | Code shipped; enable via `AGENT_ENABLED` |

---

## Shareholder agent (Track C) — infra overhead

| Resource | When agent is enabled | Notes |
|----------|----------------------|--------|
| New Docker services | No | Runs inside existing `crm_web` |
| Idle CPU/RAM on droplet | No meaningful change | No background agent worker |
| ETL schedule | Unchanged | Still `analytics_etl` at :00/:30 |
| Per user question | 2 OpenAI API calls + 1–2 read-only SQL queries on `analytics` | `generate_sql` + `summarize_results` |
| OpenAI cost | Per use | `gpt-4o-mini`; budget cap recommended (~$50/mo beta) |
| DB writes | Small audit row | `AgentQueryAudit` per question |
| Browser | Chart.js CDN | Only when panel visible |

---

## Track A — dashboard KPI cards (`/analytics/`)

Hover tooltips on each card mirror these definitions.

| Card label | Computed field | What it means |
|------------|----------------|---------------|
| **Services Pending** | `total_assignments` | Count of **all** product assignments in the selected tax season (every lifecycle state). |
| **Clients** | `clients_serviced` | **Distinct clients** with at least one assignment that season (intake through closed — not intake-only or clearing-only). |
| **Services Closed** | `closed_count` | Assignments in `CLOSED` lifecycle state. Subtext: `in_progress_count` = total − closed. |
| **Tax PDFs Parsed** | `parser_assisted_count` | Assignments with a Path A parser snapshot (`has_parser_snapshot` / `parse_result_json`). Not a raw PDF upload count. |

### Track A — other on-page metrics (revenue & lifecycle)

| UI label | Source | Meaning |
|----------|--------|---------|
| Expected (fees at clearing) | Sum `expected_fee` | Fees set at clearing |
| Recognized (collected) | Sum `actual_revenue_recognized` | Collected / recognized revenue |
| Gap (expected − recognized) | Sum `revenue_gap` | Uncollected portion where both sides exist |
| Collection rate | recognized / expected | Percent when expected > 0 |
| Median days to payment | Median `days_to_payment` | Days from `expected_fee_at` to `actual_paid_at` |
| Outstanding (pre-payment pipeline) | Sum `expected_fee` | States: clearing complete, awaiting payment |
| Lifecycle breakdown | Count by `lifecycle_state` | See lifecycle states table below |
| Data as of banner | `EtlRun.finished_at` | Last successful warehouse sync |

### Track A — lifecycle states (lifecycle breakdown table)

| State code | Display label |
|------------|---------------|
| `IN_CLEARING` | In clearing |
| `CLEARING_COMPLETE` | Clearing complete |
| `AWAITING_PAYMENT` | Awaiting payment |
| `READY_FOR_REVIEW` | Ready for review |
| `IN_REVIEW` | In review |
| `FILED` | Filed |
| `ACK_RECONCILING` | Ack reconciling |
| `PENDING_REJECT_CORRECTION` | Pending reject |
| `CLOSED` | Closed |

---

## Track A — warehouse tables (for custom KPIs / future widgets)

Queryable via Django ORM on the `analytics` database. Grain and ETL: `docs/ANALYTICS.md`.

### `dim_tax_season`

| Field | Type / notes |
|-------|----------------|
| `source_tax_season_id` | CRM tax season id |
| `year` | Tax season year |
| `start_date`, `end_date` | Season bounds |
| `is_active`, `is_archived` | Flags |
| `synced_at` | ETL timestamp |

### `dim_client`

| Field | Type / notes |
|-------|----------------|
| `source_client_id` | CRM client id |
| `name`, `tin`, `email`, `phone` | Identity / contact (PII) |
| `filing_type`, `prior_filing_type`, `appointment_type` | Client attrs |
| `client_created_at`, `synced_at` | Timestamps |

### `dim_product`

| Field | Type / notes |
|-------|----------------|
| `source_product_id` | CRM product id |
| `product_type`, `tax_year`, `default_price` | Catalog |
| `synced_at` | ETL timestamp |

### `fact_assignment` (primary KPI grain — one row per ProductAssignment)

| Category | Fields |
|----------|--------|
| Keys / links | `source_pa_id`, `source_client_id`, `tax_season_year`, `source_product_id`, `source_intake_id` |
| Assignment | `lifecycle_state`, `payment_method`, `product_type`, `filing_type`, `tax_year`, `is_active`, `is_archived`, `preparer_email` |
| Fees | `expected_fee`, `discount`, `expected_fee_at` |
| Invoice (on PA) | `source_invoice_id`, `invoice_amount`, `invoice_balance`, `invoice_paid_amount`, `invoice_status`, `invoice_paid_at` |
| Revenue / turnover | `actual_revenue_recognized`, `actual_paid_at`, `revenue_gap`, `days_to_payment` |
| Lifecycle timestamps | `clearing_complete_at`, `ready_for_review_at`, `filed_at`, `closed_at`, `review_started_at`, `intake_created_at` |
| Ack summary | `ack_count`, `ack_accepted_count`, `ack_rejected_count`, `expected_ack_count`, `tp_comp_date` |
| Path A parser (CRM snapshot) | `has_parser_snapshot`, `parser_federal_amount`, `parser_states`, `parser_tax_prep_fee` |
| Meta | `etl_synced_at` |

### `fact_invoice` (invoice grain)

| Field |
|-------|
| `source_invoice_id`, `source_client_id`, `status`, `qbo_invoice_number` |
| `amount`, `balance`, `paid_amount`, `is_paid` |
| `txn_date`, `due_date`, `created_at`, `last_activity_at`, `linked_pa_count`, `etl_synced_at` |

### `fact_ack` (acknowledgment grain)

| Field |
|-------|
| `source_ack_id`, `source_pa_id`, `source_client_id`, `tax_season_year` |
| `form_type`, `ack_year`, `ack_date`, `status` |
| `client_name`, `client_tin`, `created_at`, `etl_synced_at` |

### `fact_lifecycle_event` (transition grain — funnel / cycle time)

| Field |
|-------|
| `source_transition_id`, `source_pa_id`, `tax_season_year` |
| `from_state`, `to_state`, `actor_email`, `created_at`, `etl_synced_at` |

### `etl_run` (sync metadata)

| Field |
|-------|
| `started_at`, `finished_at`, `status`, `is_full_refresh` |
| `rows_dimensions`, `rows_assignments`, `rows_invoices`, `rows_acks`, `rows_lifecycle_events` |
| `error_message` |

### Not in warehouse yet (planned A2)

| Table / columns | Purpose |
|-----------------|---------|
| `fact_return_comparison` | YoY Comparison page metrics |
| `fact_return_profile` | Diagnostic / Sch C/E profile |
| `fact_assignment` extensions | `has_return_comparison`, `has_return_profile`, `parser_track2_status` |

---

## Track C — SQL views & fields (LLM agent)

Agent code: `pdk_crm/analytics/services/agent.py`. Rules: `SELECT` only, `LIMIT ≤ 500`, allowlisted `bi_*` views only, audited.

### Views that exist today (migrations)

| View | Columns |
|------|---------|
| **`bi_seasons`** | `source_tax_season_id`, `tax_season_year`, `start_date`, `end_date`, `is_active`, `is_archived`, `synced_at` |
| **`bi_clients`** | `source_client_id`, `client_name`, `tin`, `email`, `phone`, `filing_type`, `prior_filing_type`, `appointment_type`, `client_created_at`, `synced_at` |
| **`bi_assignments`** | All `fact_assignment` columns (including `tp_comp_date`, parser snapshot fields) |
| **`bi_invoices`** | `source_invoice_id`, `source_client_id`, `status`, `qbo_invoice_number`, `amount`, `balance`, `paid_amount`, `is_paid`, `txn_date`, `due_date`, `created_at`, `last_activity_at`, `linked_pa_count`, `etl_synced_at` |
| **`bi_last_etl`** | `id`, `started_at`, `finished_at`, `status`, `is_full_refresh`, `rows_assignments`, `rows_invoices`, `rows_acks`, `rows_lifecycle_events`, `rows_dimensions` |

### Views in agent allowlist but not yet migrated (A2 — queries will fail until shipped)

| View | Planned purpose / columns |
|------|---------------------------|
| **`bi_return_coverage`** | Season `parsed_returns`, `total_assignments` |
| **`bi_return_comparison`** | Comparison facts + client name + season (AGI YoY, refund, rates, `comparison_full_json`, …) |
| **`bi_return_profile`** | Profile + lifecycle (`deduction_type`, `has_schedule_c`, `has_schedule_e`, Sch amounts, JSON blobs) |
| **`bi_return_metrics`** | Join comparison + profile + assignment revenue — primary executive view (`agi_current`, `taxable_income_current`, `refund_current`, `filing_status`, `return_type`, …) |

### Track C — chart output (per question, not stored)

| JSON field | Values |
|------------|--------|
| `chart.type` | `bar`, `line`, `pie` |
| `chart.label_column` | Result column for labels |
| `chart.value_column` | Result column for values |
| `chart.title` | Chart title |

Rendered in-browser with Chart.js from SQL result rows.

### Track C vs Track A access

| | Track A | Track C |
|--|---------|---------|
| Roles | Manager, owner, developer | Owner, developer only |
| Env | `ANALYTICS_ENABLED=true` | + `AGENT_ENABLED=true`, `AGENT_LLM_*` |
| Return-level KPIs | After A2/A3 | After `bi_return_*` views exist |

---

## Charts & visuals summary

| Surface | Pre-built dashboard charts | Updates with ETL | Implementation |
|---------|---------------------------|------------------|----------------|
| Track A `/analytics/` | No | On page reload (data as-of ETL) | `selectors.py` + template |
| Track C agent | Per question | Per question (data as-of ETL) | `agent.py` + Chart.js |
| Track B Power BI | Yes (user-built) | Import/refresh schedule | `docs/POWER_BI.md` |

Adding Track A charts (lifecycle bar, collection trend, etc.) is a template + selector change — no new warehouse architecture (roadmap **A3**).

---

## Related docs

| Doc | Topic |
|-----|--------|
| `docs/ANALYTICS.md` | ETL, env vars, local Compose |
| `docs/AGENT_SETUP.md` | Enable Track C on droplet |
| `docs/RETURN_ANALYTICS.md` | Track 2 parser + return fact schema |
| `docs/POWER_BI.md` | Track B setup |
