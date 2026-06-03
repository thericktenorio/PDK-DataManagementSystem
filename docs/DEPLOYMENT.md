# PDK Tax Operations — Deployment (office server)

Production hosting is **on the office server** using **Docker Compose**, not cloud PaaS. This document is the runbook outline; fill in host-specific values during Phase 10.

> **MacBook shareholder demo:** Use root `compose.yaml` on Docker Desktop — see **`docs/MVP_TRIAL.md`**. That path is **Phase 10.MVP** (demo-ready) and does **not** satisfy Phase 10 exit criteria below.

> **Cloud shareholder beta (~1–2 months):** DigitalOcean Droplet + Cloudflare Tunnel/Access — see **`docs/CLOUD_BETA.md`** (Phase 10.Beta). Does **not** satisfy Phase 10 exit criteria below.

See also: `ROADMAP.md` (architecture decisions, Phase 0.8, Phase 10), `docs/MVP_TRIAL.md` (pre-prod trial), `docs/CLOUD_BETA.md` (cloud beta runbook).

---

## Topology

| Component | Role | Default dev port |
|-----------|------|------------------|
| `crm_web` | CRM modular monolith (`pdk_crm`) | 8000 |
| `crm_db` | PostgreSQL `tax_operations` | (internal) |
| `pdf_web` | Parser service (`pdf_manager`) | 8001 |
| `pdf_db` | PostgreSQL `parser` | (internal) |
| `analytics` DB | ETL-fed reporting (Phase 9) | **LAN only** in prod — no host port, no tunnel |

**Prod:** Same services as `compose.yaml` (or `compose.prod.yaml` overlay) on the office server. Deploy from **Docker images** — do not clone application source onto the server.

---

## Staff access

- Workers use **Remote Desktop** as today.
- CRM is opened in a **browser inside the RDP session** (e.g. `https://crm.office.internal` — set actual hostname during Phase 10.2).
- CRM is **not** exposed to the public internet for general staff use.

---

## QBO / Intuit (public edge only)

- **Cloudflare Tunnel** (or equivalent low-cost tunnel) terminates HTTPS for OAuth redirect and **QBO webhooks** only.
- Tunnel points at the internal reverse proxy → `crm_web`.
- **Do not** expose Postgres, parser admin, or Django `/admin/` on the public hostname without IP restrictions / separate controls.

Env vars (CRM): `INTUIT_*`, `QBO_WEBHOOK_VERIFIER_TOKEN`, `INTUIT_REDIRECT_URI` must use the **tunnel/public URL** where Intuit requires it.

---

## Reverse proxy & TLS (LAN)

- Run **Caddy** or **nginx** in front of `crm_web` (and optionally `pdf_web` if called only from CRM on LAN).
- TLS certificate: internal CA or Let's Encrypt (if internal DNS allows); document renewal in this file.
- Windows Firewall: allow CRM HTTPS from RDP subnet / office LAN only.

---

## Resource limits (protect RDP VMs)

Before go-live on the shared office host:

1. Record host **RAM, CPU, disk** under peak load (Task Manager / Hyper-V on host).
2. Set Compose `mem_limit` / CPU constraints for `crm_web`, `pdf_web`, and databases so CRM stack cannot starve existing VMs.
3. Prefer CRM data on a **dedicated volume** (e.g. `D:\pdk_crm\`) rather than system `C:`.

---

## Secrets & updates

- Prod secrets live in a **prod `.env`** file with restricted NTFS permissions (deploy user + service account only).
- **Updates:** build/push new image tags from dev machine or CI; on server run `docker compose pull && docker compose up -d` (document exact commands here once prod path is chosen).
- Application **git repo stays off the prod server**.

---

## Backups (Phase 10.5)

| Asset | Method | Schedule |
|-------|--------|----------|
| `tax_operations` | `pg_dump` from `crm_db` container | Daily (document time) |
| `parser` | `pg_dump` from `pdf_db` container | Daily |
| `analytics` | `pg_dump` when DB exists | Daily |
| CRM `media/`, parser `DATA_ROOT` | robocopy or volume snapshot | Daily |
| Off-site | Encrypted copy (e.g. B2 + restic) and/or weekly USB rotation | Weekly |

**Restore drill:** quarterly — restore dumps to a temp database name and verify one record. Document steps below after first successful drill.

### Restore procedure (TBD)

```
# Add commands after first restore test
```

---

## Staging

- **Option A:** Second Compose project on office server (different ports / project name).
- **Option B (MacBook MVP trial):** Developer Mac running root `compose.yaml` + `pdk_crm/.env.docker` — documented in **`docs/MVP_TRIAL.md`**. Intended for shareholder demo and rehearsal; **not** a substitute for Option A when validating office LAN/TLS/tunnel.

Staging must mirror prod **service topology** (CRM + parser + separate DBs), not a single-process cloud demo.

---

## Checklists

### MacBook MVP trial (Phase 10.MVP — demo-ready, **not** Phase 10 complete)

See **`docs/MVP_TRIAL.md`** for commands and demo script.

- [ ] `docker compose up --build` healthy (`/health/` on CRM and parser)
- [ ] `docker compose exec crm_web python manage.py check_mvp_ready` passes
- [ ] Demo logins work (`preparer@demo.pdk.local` / `demo-mvp`)
- [ ] One full workflow rehearsed (intake → clearing → billing → review → acks)
- [ ] Analytics page reviewed (`manager@demo.pdk.local`)

### Office production (Phase 10 exit — **required for Phase 10 complete**)

- [ ] Prod Compose up on office server
- [ ] Staff can open CRM from browser inside RDP
- [ ] Tunnel delivers QBO test webhook
- [ ] Daily backup job runs; restore tested once
- [ ] `docs/LIFECYCLE.md` and `docs/CLEARING.md` complete (Phase 0.7) — see repo `docs/`

---

## Host-specific values (fill during Phase 10)

| Item | Value |
|------|--------|
| Office server hostname / RDP host | |
| Internal CRM URL | |
| Tunnel hostname | |
| Data disk path | |
| Backup destination | |
| Deploy / restore owner | |
