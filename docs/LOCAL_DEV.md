# Local development

Run the full stack (CRM + parser + separate PostgreSQL databases) with Docker Compose from the repo root.

**Shareholder / MVP demo on MacBook:** same Compose stack — see **`docs/MVP_TRIAL.md`**. First boot auto-seeds demo users (`seed_mvp_demo`); verify with `python manage.py check_mvp_ready`.

See also: `ROADMAP.md` (Phase 0), `docs/DEPLOYMENT.md` (production topology), `docs/MVP_TRIAL.md` (demo runbook).

---

## Prerequisites

- Docker Desktop (or Docker Engine + Compose v2)
- Git

---

## Quick start

```bash
# 1. Copy env template and adjust if needed
cp pdk_crm/.env.example pdk_crm/.env.docker

# 2. Start all services
docker compose up --build

# 3. Open in browser
#    CRM:    http://localhost:8000
#    Parser: http://localhost:8001
```

First boot runs migrations and `collectstatic` for CRM automatically via `entrypoint.sh`.

**You do not need to git commit before `docker compose up --build`.** Compose builds from files on disk; commit only when you want to save/version changes.

---

## Services & ports

| Service   | URL / port              | Database        |
|-----------|-------------------------|-----------------|
| `crm_web` | http://localhost:8000   | `tax_operations` via `crm_db` |
| `pdf_web` | http://localhost:8001   | `parser` via `pdf_db`         |
| `crm_db`  | internal `:5432`        | `POSTGRES_DB` from env        |
| `analytics_db` | **host `localhost:5433`** (internal `:5432`) | `analytics` — Power BI: see `docs/POWER_BI.md` |
| `analytics_etl` | (worker)          | Syncs CRM → analytics on interval |
| `pdf_db`  | internal `:5432`        | `pdf_manager` (fixed in compose) |

Health checks:

- CRM: `GET http://localhost:8000/health/`
- Parser: `GET http://localhost:8001/health/`

---

## Environment files

CRM loads `pdk_crm/.env.{DJANGO_ENV}` (default `development`). Compose uses `pdk_crm/.env.docker`.

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Django secret (required) |
| `DEBUG` | `True` for local dev |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD` | CRM Postgres (`crm_db` in Compose) |
| `DB_HOST` | `crm_db` in Compose; `localhost` for bare-metal Postgres |
| `FEATURE_QBO` | Set `false` locally unless testing Intuit sandbox |
| `BILLING_PROVIDER` | `fake` for local dev (default) |
| `FEATURE_AUTO_SEND_INVOICES` | `false` until prod opt-in (see `docs/BILLING.md`) |
| `BILLING_QUIET_PERIOD_MINUTES` | Minutes before auto-send (default `5`) |
| `ANALYTICS_ENABLED` | `true` in Compose; `false` for SQLite-only local runs |
| `ANALYTICS_ETL_INTERVAL_SECONDS` | Warehouse sync interval (default `1800`) |

**Primary local env file:** `pdk_crm/.env.development` (loaded when `DJANGO_ENV=development`). See **`docs/BILLING.md`** for full QBO sandbox variables.

**Note:** With `FEATURE_QBO=true`, CRM startup requires all `INTUIT_*` and `QBO_WEBHOOK_VERIFIER_TOKEN` vars. Use `FEATURE_QBO=false` for everyday local work.

---

## Running without Docker

### CRM only (SQLite)

```bash
cd pdk_crm
cp .env.example .env.development
# Set USE_SQLITE=true in .env.development
export DJANGO_ENV=development
python manage.py migrate
python manage.py runserver
```

### Parser only (SQLite)

```bash
cd pdf_manager
export USE_SQLITE=true
export DJANGO_SECRET_KEY=local-dev
python manage.py migrate
python manage.py runserver 8001
```

### Parser migrations when using Compose

`pdf_db` is **not** published to the host. Inside Compose, the DB hostname is `pdf_db`; on your Mac that name does not resolve, so this fails:

```bash
cd pdf_manager && python manage.py migrate   # USE_SQLITE=false → OperationalError
```

**Run migrations inside the parser container** (uses the same Postgres as `pdf_web`):

```bash
docker compose up -d pdf_db pdf_web
docker compose exec pdf_web python manage.py migrate
```

After pulling Phase 5+ parser changes, rebuild so new migrations are in the image:

```bash
docker compose build pdf_web && docker compose up -d pdf_web
docker compose exec pdf_web python manage.py migrate
```

---

## Tests & checks

```bash
# CRM
cd pdk_crm
export SECRET_KEY=ci-test-key FEATURE_QBO=false USE_SQLITE=true DJANGO_ENV=development
python manage.py check
python manage.py test

# Parser
cd pdf_manager
pytest
```

CI runs the same checks on push/PR (`.github/workflows/ci.yml`).

---

## Module boundaries

Cross-app workflow logic belongs in `services/` or `core/workflows/`, not view-to-view imports. Example: `billing/services/` for invoice drafting; `core/workflows/` for PA lifecycle commands.
