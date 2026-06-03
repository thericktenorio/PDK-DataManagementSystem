# Analytics warehouse (Phase 9)

Reporting and KPIs read from a dedicated **`analytics`** PostgreSQL database. Operational workflows continue to use **`tax_operations`** only.

See `ROADMAP.md` (Phase 9) and `docs/DEPLOYMENT.md` (prod topology).

---

## Architecture

```text
tax_operations (CRM)  ──ETL (batch)──▶  analytics (warehouse)
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
              In-app KPI dashboard (Track A, later)     Power BI / Python (Track B)
```

**Snapshot semantics:** All figures are **as of the last successful ETL run**. They are not real-time. The in-app UI should show `EtlRun.finished_at` when built (Phase 9.6).

---

## Local Compose

| Service | Role |
|---------|------|
| `analytics_db` | PostgreSQL 16, database `analytics` |
| `analytics_etl` | Runs `sync_analytics_warehouse` on an interval (default 30 min) |

CRM (`crm_web`) sets `ANALYTICS_ENABLED=true` and migrates both databases on boot.

### First load

```bash
docker compose exec crm_web python manage.py sync_analytics_warehouse --full
```

The ETL worker also runs `--full` once on startup, then incremental syncs.

### Manual sync

```bash
docker compose exec crm_web python manage.py sync_analytics_warehouse
docker compose exec crm_web python manage.py sync_analytics_warehouse --full
```

---

## Environment variables

| Variable | Default (Compose) | Purpose |
|----------|-------------------|---------|
| `ANALYTICS_ENABLED` | `true` in Compose | Second DB + router |
| `ANALYTICS_DB_NAME` | `analytics` | Warehouse database |
| `ANALYTICS_DB_USER` | `analytics` | ETL + app write user |
| `ANALYTICS_DB_PASSWORD` | `analyticspw` (local only) | |
| `ANALYTICS_DB_HOST` | `analytics_db` | |
| `ANALYTICS_ETL_INTERVAL_SECONDS` | `1800` | ETL worker sleep between runs |

CI uses `ANALYTICS_ENABLED=false` (SQLite single-DB).

---

## Warehouse tables

| Table | Grain | Notes |
|-------|--------|------|
| `dim_tax_season` | Tax season | Season filter for reports |
| `dim_client` | Client | Name, TIN, contact, filing type |
| `dim_product` | Product catalog | Type + tax year |
| `fact_assignment` | ProductAssignment | **Primary KPI grain** — lifecycle, expected fee, invoice actuals, turnover |
| `fact_invoice` | Invoice | AR / QBO amounts |
| `fact_ack` | Acknowledgment | Post-filing outcomes |
| `fact_lifecycle_event` | LifecycleTransition | Cycle-time and funnel analysis |
| `etl_run` | ETL execution | Status, row counts, errors |
| `etl_watermark` | Incremental cursors | Internal |

### Revenue / payment turnover (dual measures)

On `fact_assignment`:

- **`expected_fee`** — `ProductAssignment.fee` at clearing.
- **`expected_fee_at`** — first transition to `CLEARING_COMPLETE`.
- **`invoice_amount` / `invoice_paid_amount`** — QBO invoice (via `AssignmentInvoiceLink`).
- **`actual_revenue_recognized` / `actual_paid_at`** — paid invoice (QBO) or recognized fee for non-QBO methods after clearing.
- **`revenue_gap`** — `expected_fee − actual_revenue_recognized` when both are set.
- **`days_to_payment`** — calendar days from `expected_fee_at` to `actual_paid_at`.

---

## Incremental ETL

Default run (no `--full`):

1. Refresh dimensions (clients, seasons, products).
2. Append lifecycle events since last transition id.
3. Upsert assignments touched by: new transitions, invoice activity, new acks, review updates, or **active tax season** (keeps open PAs fresh).
4. Upsert changed invoices and acks.

Use `--full` for initial deploy, schema changes, or repair.

---

## In-app dashboard (Track A)

URL: `/analytics/` (CRM nav **Analytics**).

| Role | Access |
|------|--------|
| Manager, Owner, Developer | Yes |
| All other roles | 403 Forbidden |

KPIs (per selected tax season, from `fact_assignment`):

- Product assignments, clients serviced, closed vs in progress
- Expected vs recognized revenue, gap, collection rate, median days to payment
- Outstanding expected in clearing-complete / awaiting-payment pipeline
- Lifecycle state breakdown, parser-assisted count

Banner shows **last successful ETL** timestamp.

---

## Access control (BI)

| Role | In-app analytics | BI connection |
|------|------------------|---------------|
| Manager, Owner, Developer | Yes | Read-only `analytics_reader` (prod) |
| Other staff roles | No | No |

---

## Power BI (Track B)

Step-by-step: **`docs/POWER_BI.md`**.

Local Compose exposes the warehouse at **`localhost:5433`**. Use Import mode and the **`bi_*`** SQL views (`bi_assignments`, `bi_seasons`, `bi_clients`, `bi_invoices`, `bi_last_etl`).

**Free license limits:** personal **My workspace** only; secure team sharing needs **Power BI Pro** or Premium capacity. Desktop + LAN Postgres is sufficient for solo executive MVP.

---

## Production notes

- Do not expose `analytics_db` on the internet.
- Create a read-only role for BI:

```sql
CREATE ROLE analytics_reader WITH LOGIN PASSWORD '…';
GRANT CONNECT ON DATABASE analytics TO analytics_reader;
GRANT USAGE ON SCHEMA public TO analytics_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO analytics_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO analytics_reader;
```

- Backup `analytics` with daily `pg_dump` (see `docs/DEPLOYMENT.md`).
- Peak season: 15–60 min ETL interval; off-peak: nightly is acceptable.

---

## Not in v1 ETL

- Parser DB `ExtractedField` facts (optional Phase 9.1b).
- CRM fields not yet modeled (DOB, dependents, address) — extend `dim_client` when added to intake/CRM.

Parser snapshot hints on `fact_assignment`: `parser_federal_amount`, `parser_states`, `parser_tax_prep_fee` from `parse_result_json`.
