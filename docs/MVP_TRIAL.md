# MacBook MVP trial (Phase 10.MVP)

Run the full PDK Tax Operations stack on a **MacBook via Docker Compose** for a shareholder or internal demo **before** deploying to the office server.

> **Phase 10 is not complete** until office-server exit criteria in `ROADMAP.md` and `docs/DEPLOYMENT.md` are met. This document covers **demo readiness only**.

See also: `docs/LOCAL_DEV.md` (day-to-day dev), `docs/CLOUD_BETA.md` (multi-week shareholder beta on DigitalOcean), `docs/DEPLOYMENT.md` (office prod), `ROADMAP.md` (Phase 10.MVP vs 10.Beta vs 10.0).

---

## Why Docker on the MacBook

| Approach | Recommendation |
|----------|----------------|
| **Docker Compose** (`compose.yaml`) | **Yes** — matches office prod topology (CRM + parser + 3 Postgres DBs + billing/ETL workers). One command to start/stop. |
| Bare-metal `runserver` | No for demo — SQLite skips analytics warehouse, workers, and parser Postgres separation. |
| Office server early | Defer until after demo — shared Hyper-V host needs resource limits and LAN/TLS work (Phase 10.1–10.2). |

**Hardware:** Docker Desktop with **≥ 8 GB RAM** allocated to Docker (16 GB Mac RAM recommended). First `docker compose up --build` may take several minutes.

---

## Quick start

```bash
# From repo root
cp pdk_crm/.env.example pdk_crm/.env.docker   # if missing; adjust SECRET_KEY

docker compose up --build
```

On first boot, `crm_web` runs **`seed_mvp_demo`** automatically (`SEED_MVP_DEMO=true` in `compose.yaml`). Demo users share password **`demo-mvp`** unless you set `MVP_DEMO_PASSWORD` in Compose.

Verify seed data:

```bash
docker compose exec crm_web python manage.py check_mvp_ready
```

| URL | Service |
|-----|---------|
| http://localhost:8000 | CRM (staff UI) |
| http://localhost:8000/health/ | CRM health |
| http://localhost:8001 | Parser admin/API |
| http://localhost:8000/analytics/ | In-app KPI dashboard (manager/owner/developer roles) |

### Demo logins (dev only)

| Email | Role | Use in demo |
|-------|------|-------------|
| `preparer@demo.pdk.local` | tax_preparer | Intake, clearing |
| `reviewer@demo.pdk.local` | reviewer | Review queue, acks |
| `manager@demo.pdk.local` | manager | Analytics dashboard |
| `developer@demo.pdk.local` | developer | Admin + full access |

Password: **`demo-mvp`** (override with `MVP_DEMO_PASSWORD` in `compose.yaml`).

Compose defaults (see `compose.yaml`): `FEATURE_QBO=false`, `BILLING_PROVIDER=fake`, parser path A enabled (`PDF_MANAGER_BASE_URL=http://pdf_web:8000`), analytics ETL on 30-minute interval.

Stop: `Ctrl+C` or `docker compose down`. Data persists in named volumes until `docker compose down -v`.

---

## Manual seed / reset

Auto-seed runs once per fresh volume. To re-seed or add a sample client:

```bash
docker compose exec crm_web python manage.py seed_mvp_demo --reset-passwords
docker compose exec crm_web python manage.py seed_mvp_demo --with-sample-client
```

Disable auto-seed: set `SEED_MVP_DEMO=false` on `crm_web` in `compose.yaml`.

---

## First-time data setup (legacy manual path)

Prefer **`seed_mvp_demo`** above. Manual admin setup is only needed if auto-seed is disabled.

### 1. Create organization and tax season

Django admin: http://localhost:8000/admin/

1. **Core → Organizations → Add** — e.g. `PDK Tax Demo`.
2. **Core → Tax seasons → Add** — e.g. year `2025`, active, dates covering the demo period.

Or via shell:

```bash
docker compose exec crm_web python manage.py shell -c "
from core.models import Organization, TaxSeason
from datetime import date
org, _ = Organization.objects.get_or_create(name='PDK Tax Demo')
TaxSeason.objects.get_or_create(
    year=2025,
    defaults=dict(start_date=date(2025,1,1), end_date=date(2025,12,31), is_active=True),
)
print('org id', org.pk)
"
```

### 2. Create demo users

Superuser (developer role — full access including Analytics):

```bash
docker compose exec -it crm_web python manage.py createsuperuser
# Email, password; organization id = 1 (or your org pk); role = developer
```

Add role-specific users in admin (**Accounts → Internal users**) or repeat `createsuperuser` with roles `tax_preparer`, `reviewer`, `manager` for walkthrough handoffs.

### 3. Products (if intake requires them)

**Core → Products** — at least one active product linked to the org/tax season rules your intake form expects.

---

## Shareholder demo script (~20–30 min)

Walk the **north star** from `ROADMAP.md`. Use **path B (manual clearing)** unless parser sample PDFs are on the machine.

| # | Stage | Who | What to show |
|---|--------|-----|--------------|
| 1 | Intake | Preparer | Add client → PA created for active tax season |
| 2 | Clearing | Preparer | Manual entry, client message, complete clearing → `CLEARING_COMPLETE` |
| 3 | Billing | Preparer / billing | Fake provider: confirm payment or no-fee → `READY_FOR_REVIEW` (see `docs/BILLING.md`) |
| 4 | Review | Reviewer | Claim queue, complete review, mark filed → `FILED` |
| 5 | Acknowledgments | Reviewer | Upload/match acks → `CLOSED` or reject path |
| 6 | Analytics | Manager/owner | `/analytics/` KPIs after ETL (may need intake data first; see `ROADMAP.md` Phase 9 note) |

**Talking points:** modular monolith + separate parser DB; lifecycle replaces old completion wizard; analytics reads warehouse only; office prod adds LAN TLS, tunnel for QBO, backups.

### Optional: parser path A

1. Place Drake sample PDFs under `pdf_manager/fixtures/drake_samples/` (gitignored — copy from secure storage).
2. In clearing, upload PDF on a PA row; show auto-fill and generated message.
3. Mention Phase 5 speed/quality work in progress if parse is slow on scanned PDFs.

---

## What this demo does **not** prove

Keep expectations clear for shareholders:

| Office Phase 10 item | MVP trial |
|----------------------|-----------|
| RDP + LAN URL (`https://crm.office.internal`) | localhost only |
| Cloudflare tunnel + QBO webhooks | QBO off; fake billing |
| Daily backups + restore drill | Docker volumes only |
| Compose memory/CPU limits vs Hyper-V | N/A on MacBook |
| Power BI + on-premises gateway | Use in-app Analytics |
| Parser API key (10.6) | Not enforced locally |
| Deploy from images (no git on server) | Build from source on Mac |

---

## Presentation tips

- **In-room:** Browser full-screen on Mac; no network setup required.
- **Remote shareholders:** Screen share (Zoom/Meet) from the same Mac running Compose — still no public URL needed.
- **Do not** expose Postgres (`5433`) or CRM to the internet for demo unless you accept security review (see Phase 9 security table in `ROADMAP.md`).

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| CRM won't start / QBO env error | Ensure `FEATURE_QBO=false` in `.env.docker` or Compose env |
| `createsuperuser` asks for organization | Create Organization in admin first; pass org id when prompted |
| Analytics empty | Add CRM data, wait for ETL or run `docker compose exec crm_web python manage.py sync_analytics_warehouse --full` |
| Parser migrate error on host | Run migrations inside container: `docker compose exec pdf_web python manage.py migrate` |
| Port in use | Stop other stacks or change host ports in `compose.yaml` |

---

## After the demo

1. **Office server:** Follow `docs/DEPLOYMENT.md` checklist (Phase 10 exit criteria).
2. **Optional:** Export demo data via `pg_dump` from containers if you want to seed office staging — not required for MVP.
3. **QBO sandbox:** When ready, use ngrok flow in `docs/BILLING.md` on Mac or wait for office tunnel (Phase 10.2).
