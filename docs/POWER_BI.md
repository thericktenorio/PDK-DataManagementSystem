# Power BI — connect to the analytics warehouse

> **Status:** Deferred for office-server / Windows setup (Phase 10). On **Mac**, use CRM **Analytics** (`/analytics/`) for KPIs until then. This doc remains the runbook when you enable executive BI.

Track B executive reporting against the **`analytics`** database only (never `tax_operations`).

Prerequisites: Docker Compose stack running, ETL has run at least once, **Power BI Desktop** on **Windows** (or office PC) — not native macOS.

See also: `docs/ANALYTICS.md`, `docs/LOCAL_DEV.md`.

---

## 1. Expose Postgres to your PC (local dev)

Compose maps the warehouse to the host:

| Setting | Value |
|---------|--------|
| Server | `localhost` |
| Port | **5433** (not 5432 — avoids conflict with a local Postgres) |
| Database | `analytics` |
| User | `analytics` |
| Password | `analyticspw` (local Compose only; change in production) |

Restart Compose after pulling this port change:

```bash
docker compose up -d
docker compose exec crm_web python manage.py migrate --database=analytics --noinput
docker compose exec crm_web python manage.py sync_analytics_warehouse --full
```

Quick connectivity test (optional):

```bash
docker compose exec analytics_db psql -U analytics -d analytics -c "SELECT COUNT(*) FROM bi_assignments;"
```

---

## 2. Install Power BI Desktop

1. Sign in with your Power BI / Microsoft account.
2. Download **Power BI Desktop** from [https://powerbi.microsoft.com/desktop](https://powerbi.microsoft.com/desktop).
3. Open Desktop (reports are built here; publishing to the cloud is optional for MVP).

---

## 3. Connect to PostgreSQL

1. **Home → Get data → More… → Database → PostgreSQL database**
2. Enter:
   - **Server:** `localhost:5433`
   - **Database:** `analytics`
3. **DirectQuery** = live queries (heavier on Postgres). **Import** = snapshot in the `.pbix` file (recommended for MVP; refresh after each ETL).
4. Choose **Import**, then **OK**.
5. Credentials: **Database**, user `analytics`, password `analyticspw`.
6. In the navigator, select these **views** (friendly names):

   | View | Use |
   |------|-----|
   | `bi_assignments` | Main fact table (one row per PA) |
   | `bi_seasons` | Tax season filter |
   | `bi_clients` | Client attributes |
   | `bi_invoices` | Invoice / AR detail |
   | `bi_last_etl` | Single row — “as of” timestamp for report header |

7. **Load** (or Transform data first if you prefer Power Query tweaks).

If `bi_*` views are missing, run analytics migrations:

```bash
docker compose exec crm_web python manage.py migrate --database=analytics --noinput
```

---

## 4. Model relationships (Model view)

There are no foreign keys in the warehouse; create relationships manually:

| From | To | Cardinality |
|------|-----|-------------|
| `bi_seasons[tax_season_year]` | `bi_assignments[tax_season_year]` | One to many |
| `bi_clients[source_client_id]` | `bi_assignments[source_client_id]` | One to many (optional) |

Do not relate `bi_last_etl` to other tables; use it in a card visual or DAX measure.

---

## 5. Suggested first report page

**Filters:** `bi_seasons[tax_season_year]` slicer (active season).

**Cards / KPIs (DAX measures):**

```dax
Total Assignments = COUNTROWS(bi_assignments)

Clients Serviced = DISTINCTCOUNT(bi_assignments[source_client_id])

Expected Revenue =
    SUM(bi_assignments[expected_fee])

Recognized Revenue =
    SUM(bi_assignments[actual_revenue_recognized])

Revenue Gap =
    [Expected Revenue] - [Recognized Revenue]

Collection Rate % =
    DIVIDE([Recognized Revenue], [Expected Revenue], BLANK())

Closed Count =
    CALCULATE(
        COUNTROWS(bi_assignments),
        bi_assignments[lifecycle_state] = "CLOSED"
    )
```

**Charts:**

- Bar: `lifecycle_state` vs count of `source_pa_id`
- Clustered bar: `payment_method` vs sum of `expected_fee` and `actual_revenue_recognized`
- Card: max of `bi_last_etl[finished_at]` with label **“Data as of”**

---

## 6. Refresh data

After CRM ETL runs:

1. **Home → Refresh** (Import mode), or
2. Schedule refresh later via **on-premises data gateway** when on the office server.

ETL in Compose runs every 30 minutes by default (`analytics_etl` service). Manual sync:

```bash
docker compose exec crm_web python manage.py sync_analytics_warehouse
```

---

## 7. Publish to Power BI Service (optional)

- **Free account:** publish to **My workspace** only; you can view your own reports in the browser.
- **Sharing with other executives securely** requires **Power BI Pro** (~$10/user/month) or Premium capacity — not required for solo Desktop use.
- Do **not** use **Publish to web** for reports that include TIN or client PII.

---

## 8. Production (office server)

- Do **not** publish port `5433` on the public internet.
- BI connects over **office LAN** or RDP to a machine that can reach Postgres.
- Use the read-only role from `docs/ANALYTICS.md` (`analytics_reader`), not the ETL user.
- Same `bi_*` views after `migrate --database=analytics`.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Cannot connect to `localhost:5433` | `docker compose ps` — ensure `analytics_db` is up; port `5433` listed |
| Empty tables | Run `sync_analytics_warehouse --full` |
| `bi_*` not in navigator | `migrate --database=analytics` |
| Numbers differ from CRM | Expected — warehouse is **as of last ETL**; compare after sync |
| SSL errors | Use non-SSL / prefer non-SSL in connector advanced options for local dev |

---

## Table reference (underlying Django tables)

If you load raw tables instead of views:

| Django table | Grain |
|--------------|--------|
| `analytics_factassignment` | Product assignment |
| `analytics_dimtaxseason` | Tax season |
| `analytics_dimclient` | Client |
| `analytics_factinvoice` | Invoice |
| `analytics_etlrun` | ETL history |

Prefer **`bi_*` views** for reporting.
