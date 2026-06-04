# Cloud beta deployment (Phase 10.Beta)

**Purpose:** Single runbook to **stand up** the shareholder cloud beta (~1–2 months). **Compute:** [DigitalOcean](https://www.digitalocean.com) Basic Droplet (8 GiB, $48/mo, US region). Use **`ROADMAP.md`** (Phase 10.Beta exit criteria) and **`docs/MVP_TRIAL.md`** (seed data, demo workflow) for **product readiness** before the shareholder presentation.

**Does not complete Phase 10.** Office production remains **`docs/DEPLOYMENT.md`** + Phase **10.0** in `ROADMAP.md`.

See also: `ROADMAP.md` (Phase 10.Beta), `docs/BILLING.md` (QBO sandbox), `docs/LOCAL_DEV.md` (Compose services).

---

## Architecture (what talks to what)

```text
Shareholder browser
    │  HTTPS
    ▼
Cloudflare edge (DNS + TLS + Access + WAF)
    │  Cloudflare Tunnel (outbound from VPS; no open :443 required on VPS for CRM)
    ▼
cloudflared on VPS → http://127.0.0.1:8000
    ▼
┌─────────────────────────────────────────────────────────┐
│  VPS — Docker Compose (compose.yaml)                    │
│  crm_web :8000  ←→  crm_db (tax_operations)            │
│  pdf_web         ←→  pdf_db (parser)                    │
│  analytics_etl   ←→  analytics_db (analytics)           │
│  billing_* workers, volumes: media + parser DATA_ROOT   │
└─────────────────────────────────────────────────────────┘
    │
    ▼ (optional, encrypted)
Off-VPS backups (e.g. B2) — pg_dump + media archives
```

| Hostname (fill in) | Points to | Exposed publicly? |
|--------------------|-----------|-------------------|
| `pdk.godelta.us` | Tunnel → `crm_web` | Yes (via Cloudflare; gate with **Access**) |
| `godelta.us` / `www` | Optional marketing later | Your choice |
| Postgres `5432` / `5433` | — | **Never** |

---

## Subscriptions & services

Fill in **your price** and **renewal date** as you purchase. Typical ranges are shown where helpful.

### Required for cloud beta

| Service | Provider | Billing | Your price | Typical range | Purpose in architecture | Status |
|---------|----------|---------|------------|---------------|-------------------------|--------|
| **Domain** `godelta.us` | Cloudflare Registrar | Prepaid multi-year | **$13 / 2 yr** | ~$10–15/yr (.us/.com); you paid ~$13/2yr | **Identity** for `pdk.godelta.us`; stable Intuit OAuth/webhook URLs | ☑ |
| **DNS + Tunnel + Access** | Cloudflare (Free plan) | $0 / ongoing | **$0** | $0 | **DNS** for hostname; **Tunnel** = HTTPS to VPS without exposing CRM port to internet; **Access** = email allowlist before Django | ☐ |
| **VPS** (Linux, 8 GB RAM, US region) | **DigitalOcean** | Monthly recurring | **$48 /mo** | ~$48/mo (DO Basic 8 GiB) | **Compute host** for entire Compose stack (CRM, parser, 3× Postgres, workers) | ☐ |

### Recommended (not strictly required day one)

| Service | Provider | Billing | Your price | Typical range | Purpose in architecture | Status |
|---------|----------|---------|------------|---------------|-------------------------|--------|
| **Off-site backups** | _Backblaze B2 / similar_ | Monthly + storage | **$ /mo** _(fill after B2 setup)_ | ~$1–5/mo | **Disaster recovery** — encrypted `pg_dump` + optional media; VPS disk alone is not enough | ☐ |

### Already have / no incremental cost for beta

| Service | Provider | Billing | Your price | Purpose in architecture | Status |
|---------|----------|---------|------------|-------------------------|--------|
| **Source control** | GitHub | $0 (or existing plan) | **$0** | Deploy via `git pull` on VPS; CI optional | ☐ |
| **Application** | (this repo) | — | — | CRM + parser monolith; no per-seat license | ☑ |
| **Docker Engine + Compose** | On VPS | $0 | **$0** | Orchestrates all services on the VPS | ☐ |

### Optional (enable only when testing real QBO in beta)

| Service | Provider | Billing | Your price | Typical range | Purpose in architecture | Status |
|---------|----------|---------|------------|---------------|-------------------------|--------|
| **Intuit Developer** (sandbox app) | Intuit | $0 | $0 | $0 | **OAuth + webhooks** — redirect/webhook URLs on `https://pdk.godelta.us/...` | ☐ |
| **QuickBooks Online** | Intuit | Firm subscription (existing) | $ | (existing) | **Live or sandbox** invoicing when `FEATURE_QBO=true`, `BILLING_PROVIDER=qbo` | ☐ |

### Explicitly not required for beta

| Item | Why skip |
|------|----------|
| Cloudflare Pro / Business | Free plan suffices for Tunnel + Access at ~5 users |
| Tailscale | Optional extra; only if policy forbids public CRM URL (QBO still needs public webhook path) |
| ngrok paid | Use Cloudflare Tunnel instead |
| Managed DB (RDS, etc.) | Postgres runs in Compose on VPS |
| PaaS (Render, Heroku, etc.) | Different architecture; harder office migration |
| Squarespace / web hosting | Domain DNS is on Cloudflare; CRM runs on VPS |
| Power BI / on-prem gateway | Use in-app `/analytics/` for beta |
| Business email on domain | Optional; not needed for CRM login |

---

## Cost summary (fill in)

| Period | Line items | Your total |
|--------|------------|------------|
| **One-time / prepaid** | Domain (2 yr): **$13** | **$13** |
| **Monthly recurring** | VPS (DigitalOcean): **$48** + Backups (B2): **~$3** | **~$51 /mo** |
| **2-month beta estimate** | Prepaid domain + (monthly × 2) | **~$115** _($13 + 2×$51)_ |

---

## Accounts & credentials checklist (non-subscription)

Prepare before or during VPS setup. **Do not commit secrets to git.**

| Item | Example / note | Done |
|------|----------------|------|
| Cloudflare account (zone `godelta.us` active) | Registrar + DNS + Zero Trust | ☐ |
| VPS SSH key | Ed25519; no password-only root login | ☐ |
| `SECRET_KEY` (Django) | Long random string in `pdk_crm/.env.docker` on VPS | ☐ |
| `ALLOWED_HOSTS` | `pdk.godelta.us` | ☐ |
| `PDF_MANAGER_BASE_URL` | `http://pdf_web:8000` (inside Compose network) | ☐ |
| Cloudflare Access allowlist | Shareholder/staff emails (5) | ☐ |
| Django users + roles | preparer, reviewer, manager/owner | ☐ |
| Organization + tax season + products | Admin or `seed_mvp_demo` — see `docs/MVP_TRIAL.md` | ☐ |
| Tunnel hostname | `pdk.godelta.us` → `http://127.0.0.1:8000` | ☐ |
| 2FA | Cloudflare, registrar, VPS provider | ☐ |
| WISP / vendor note | Document **Cloudflare + DigitalOcean** as subprocessors for beta PII | ☐ |

### Default beta app settings (recommended start)

```bash
FEATURE_QBO=false
BILLING_PROVIDER=fake
FEATURE_AUTO_SEND_INVOICES=false
FEATURE_PARSER_PATH_A=true
```

Enable QBO later per `docs/BILLING.md` (Intuit redirect + webhook on `https://pdk.godelta.us/...`).

---

## Acquire a VPS (step-by-step)

**Chosen provider: [DigitalOcean](https://www.digitalocean.com)** — US-friendly signup, familiar to shareholders, good docs. Postgres still runs **inside Docker** on the Droplet (no managed DB bill).

### 1. Droplet spec (do not undersize)

| Setting | Value |
|---------|--------|
| **Plan** | **Basic** (shared CPU) |
| **Size** | **8 GiB RAM / 4 vCPUs / 160 GiB SSD / 5 TB transfer** |
| **Price** | **$48 / month** ([pricing](https://www.digitalocean.com/pricing/droplets)) |
| **Image** | **Ubuntu 24.04 (LTS) x64** |
| **Region** | US — **NYC1**, **NYC3**, or **SFO3** (pick closest to shareholders) |
| **Auth** | **SSH key** only (no root password email) |
| **Hostname** | e.g. `godelta-beta` |
| **Add-ons** | **Monitoring** (free) OK; **skip DO Backups** for now — use B2 + `scripts/beta/backup_beta.sh` |

**Do not use** the 4 GiB ($24) Droplet — insufficient RAM for CRM + parser + 3× Postgres + workers.

<details><summary>Alternatives (not the beta default)</summary>

| Provider | Plan | Notes |
|----------|------|-------|
| Hetzner Cloud CPX31 | ~8 GB, ~$14/mo | Lower cost; may require passport KYC for US accounts |
| Linode Akamai 8 GB | ~$48/mo | Similar to DO |
| AWS Lightsail 8 GB | ~$44/mo | Fine if already on AWS |

</details>

### 2. Create the Droplet

1. [Sign up / log in](https://cloud.digitalocean.com) → **Billing** on file.
2. **Account → Security → SSH Keys → Add SSH Key** (generate on Mac if needed):
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/godelta_beta -C "godelta-beta"
   cat ~/.ssh/godelta_beta.pub   # paste into DigitalOcean
   ```
3. **Create → Droplets → Ubuntu 24.04** → **Basic** → **8 GiB / 4 vCPU** ($48) → US region → select SSH key → create.
4. Note the **public IPv4** (e.g. `203.0.113.10`). Fill host table below: region + IP.
5. First login:
   ```bash
   ssh -i ~/.ssh/godelta_beta root@YOUR_DROPLET_IP
   ```

### 3. DigitalOcean Cloud Firewall (recommended)

In DO console: **Networking → Firewalls → Create**:

| Inbound | Protocol | Port | Sources |
|---------|----------|------|---------|
| SSH | TCP | 22 | **Your home/office IP** (not `0.0.0.0/0`) |

**No inbound** rules for 8000, 8001, 5432, or 5433 — Cloudflare Tunnel reaches CRM on localhost. Attach firewall to the Droplet.

`scripts/beta/setup_vps.sh` also enables **UFW** (SSH only) as a second layer.

### 4. Install Docker on the Droplet

```bash
apt update && apt upgrade -y
apt install -y git ca-certificates curl
curl -fsSL https://get.docker.com | sh
docker compose version   # should show Compose v2
```

### 5. Clone the app

```bash
mkdir -p /opt/pdk && cd /opt/pdk
git clone YOUR_REPO_URL pdk_crm_postgresql
cd pdk_crm_postgresql
```

Deploy steps continue in **Deployment sequence** below (`.env.docker`, `compose up`, Tunnel).

**Repo helpers (this branch):**

| Script | Purpose |
|--------|---------|
| `scripts/beta/setup_vps.sh` | Docker, git clone, UFW |
| `scripts/beta/deploy.sh` | `git pull` + `compose.beta.yaml` up + health check |
| `scripts/beta/install_cloudflared.sh` | cloudflared binary + Zero Trust checklist |
| `scripts/beta/backup_beta.sh` | pg_dump ×3 + B2 upload (cron) |
| `pdk_crm/.env.beta.example` | Template → copy to `pdk_crm/.env.docker` on VPS |
| `compose.beta.yaml` | Overlay: no public analytics/parser ports; `DEBUG=False` |

```bash
# On VPS after clone:
cp pdk_crm/.env.beta.example pdk_crm/.env.docker   # edit secrets
ln -sf pdk_crm/.env.docker .env                    # required for crm_db ${DB_*} vars
docker compose -f compose.yaml -f compose.beta.yaml up --build -d
```

---

## Database & backup pathway

### How data is stored (no managed DB)

| Database | Compose service | Data on disk |
|----------|-----------------|--------------|
| `tax_operations` | `crm_db` | Docker volume `crm_pgdata` |
| `parser` | `pdf_db` | Docker volume `pdf_pgdata` |
| `analytics` | `analytics_db` | Docker volume `analytics_pgdata` |
| CRM uploads | `crm_web` | volume `crm_media` |
| Parser PDFs | `pdf_web` | volume `pdf_data` |

**Beta:** keep `analytics_db` **without** a public host port (same as prod intent). Do not publish `5432`/`5433` on the VPS firewall.

### Backup strategy (recommended)

```text
Nightly cron on VPS
  → pg_dump (×3 databases from containers)
  → optional: tar media/pdf volumes
  → upload encrypted files to Backblaze B2 (off-VPS)
```

If the VPS dies, you restore dumps + volumes on a new machine or the office server.

### Acquire Backblaze B2 (step-by-step)

1. Sign up at [backblaze.com/b2](https://www.backblaze.com/b2/cloud-storage.html).
2. Create a **bucket** (e.g. `godelta-beta-backups`) — **private**.
3. Create an **Application Key** with read/write on that bucket only; save `keyID` and `applicationKey` (once).
4. Note **endpoint** (e.g. `s3.us-west-004.backblazeb2.com`) and bucket name.
5. Fill in host table: backup bucket name.

**Cost:** storage + egress; beta with nightly SQL dumps is usually **~$1–5/month**.

**Alternative:** provider **VPS snapshots** (weekly) — easier but less granular than SQL dumps; best used **with** `pg_dump`, not instead of it.

### Install backup tools on VPS

```bash
apt install -y postgresql-client gzip
# B2 via AWS CLI (S3-compatible):
apt install -y awscli
# OR: rclone (configure B2 remote)
```

### Example backup script (customize paths)

Use **`scripts/beta/backup_beta.sh`** in the repo (reads `DB_*` from `pdk_crm/.env.docker`). On VPS:

```bash
chmod 700 /opt/pdk/pdk_crm_postgresql/scripts/beta/backup_beta.sh
# B2: export AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (B2 application key)
#     aws configure set default.s3.signature_version s3v4  # if needed
30 2 * * * /opt/pdk/pdk_crm_postgresql/scripts/beta/backup_beta.sh >> /var/log/pdk-backup.log 2>&1
```

<details><summary>Inline script (legacy reference)</summary>

Save on VPS as `/opt/pdk/backup_beta.sh` (chmod `700`), **do not commit secrets**:

```bash
#!/bin/bash
set -euo pipefail
STAMP=$(date +%Y%m%d_%H%M)
DIR=/var/backups/pdk/$STAMP
mkdir -p "$DIR"
cd /opt/pdk/pdk_crm_postgresql

docker compose exec -T crm_db pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$DIR/tax_operations.sql.gz"
docker compose exec -T pdf_db pg_dump -U pdfmgr pdf_manager | gzip > "$DIR/parser.sql.gz"
docker compose exec -T analytics_db pg_dump -U analytics analytics | gzip > "$DIR/analytics.sql.gz"

# Optional: export env for CRM DB names from pdk_crm/.env.docker before running, or hardcode beta values.

tar -czf "$DIR/crm_media.tar.gz" -C /var/lib/docker/volumes pdk_crm_postgresql_crm_media/_data 2>/dev/null || true

# Upload to B2 (AWS CLI example — set keys in ~/.aws/credentials or env):
# aws s3 sync "$DIR" "s3://godelta-beta-backups/$STAMP/" --endpoint-url "https://s3.us-west-004.backblazeb2.com"

find /var/backups/pdk -maxdepth 1 -type d -mtime +14 -exec rm -rf {} +
```

</details>

**Note:** `DB_USER` / `DB_NAME` must match `pdk_crm/.env.docker` (`crm_db` service). Adjust volume path after first `compose up` (`docker volume ls`).

### Schedule nightly backups

```bash
chmod +x /opt/pdk/backup_beta.sh
crontab -e
# 2:30 AM daily:
30 2 * * * /opt/pdk/backup_beta.sh >> /var/log/pdk-backup.log 2>&1
```

### Prove restore works (once)

1. Download one night's `.sql.gz` from B2.  
2. On a test DB container or local Compose: `gunzip -c tax_operations.sql.gz | docker compose exec -T crm_db psql -U ... -d ...`  
3. Confirm a known client/PA row exists.

Document “restore worked on DATE” in the host table or your WISP notes.

---

## Deployment sequence (implementation order)

Use this order in a new thread; check off as you go.

1. ☐ **DigitalOcean Droplet** — 8 GiB Basic, Ubuntu 24.04, US region; DO Cloud Firewall (SSH from your IP only)  
2. ☐ **Droplet software** — `bash scripts/beta/setup_vps.sh` (Docker + clone)  
3. ☐ **Cloudflare Tunnel** — `bash scripts/beta/install_cloudflared.sh`; publish `pdk.godelta.us` → `http://127.0.0.1:8000`  
4. ☐ **Cloudflare Access** — policy on `pdk.godelta.us` (allowed emails only)  
5. ☐ **`.env.docker`** — `cp pdk_crm/.env.beta.example pdk_crm/.env.docker`; set `SECRET_KEY`, `DB_PASSWORD`, `ALLOWED_HOSTS=pdk.godelta.us`  
6. ☐ **`docker compose -f compose.yaml -f compose.beta.yaml up --build -d`** — or `bash scripts/beta/deploy.sh`  
7. ☐ **Migrations** — CRM auto via entrypoint; `docker compose exec pdf_web python manage.py migrate`  
8. ☐ **Seed** — auto via `SEED_MVP_DEMO=true`; verify `check_mvp_ready` (`docs/MVP_TRIAL.md`)  
9. ☐ **Smoke test** — `https://pdk.godelta.us/health/` → login → intake → clearing upload (one PDF)  
10. ☐ **Backups** — B2 bucket + `scripts/beta/backup_beta.sh` cron + one restore test  
11. ☐ **Shareholder beta** — send URL + Access invite; collect feedback  

---

## After infrastructure: app readiness before shareholder presentation

Infrastructure up ≠ beta ready to pitch. Complete product checks separately:

| Document | Use for |
|----------|---------|
| **`ROADMAP.md`** | Phase 4–9 gaps, 10.Beta exit criteria, what “done” means for workflow |
| **`docs/MVP_TRIAL.md`** | Demo script, seed users, path A/B walkthrough |
| **`docs/BILLING.md`** | If demonstrating QBO (sandbox + tunnel URLs) |
| **`docs/PARSER_EXTRACTION.md`** | Parser expectations, `message_ready`, sample PDFs |
| **`docs/LIFECYCLE.md`** | Payment-method → billing → review gates |

**10.Beta exit criteria** (from roadmap): five users complete intake → clearing → billing gate → review on `https://pdk.godelta.us`; backups verified; feedback captured.

### Product readiness checklist (before shareholder pitch)

Run on VPS after step 6 above (or locally to rehearse):

```bash
docker compose exec crm_web python manage.py check_mvp_ready
```

| Check | Command / action | Doc |
|-------|------------------|-----|
| Health | `curl -sf https://pdk.godelta.us/health/` | — |
| Demo users | `preparer@demo.pdk.local`, `reviewer@`, `manager@` — password from `MVP_DEMO_PASSWORD` | `MVP_TRIAL.md` |
| Full workflow once | Intake → clearing (path A PDF) → fake billing → review → acks | `MVP_TRIAL.md` demo script |
| Analytics | Log in as `manager@demo.pdk.local` → `/analytics/` | `MVP_TRIAL.md` |
| Parser path A | Upload sample PDF in clearing; confirm `message_ready` | `PARSER_EXTRACTION.md` |
| Lifecycle gates | Payment method → billing → review | `LIFECYCLE.md` |
| Beta exit | 5 users × full loop on beta URL | `ROADMAP.md` 10.Beta |

Replace demo passwords before inviting external shareholders (`MVP_DEMO_PASSWORD` in Compose or `seed_mvp_demo --reset-passwords` with production-strength secrets).

---

## Cutover to office server (after beta)

1. Maintenance window → stop writes  
2. `pg_dump` for `tax_operations`, `parser`, `analytics`  
3. Copy Docker volumes (`crm_media`, `pdf_data`, etc.)  
4. Restore on office Compose (Phase **10.0**)  
5. Repoint DNS/Tunnel to office **or** switch staff to LAN URL (`docs/DEPLOYMENT.md`)  
6. Update Intuit app URLs if public hostname changes  
7. Decommission or snapshot cloud VPS; revoke old tunnel tokens  

---

## Host-specific values (this beta)

| Item | Value |
|------|--------|
| Domain | `godelta.us` |
| CRM URL | `https://pdk.godelta.us` |
| Git remote | `https://github.com/thericktenorio/PDK-DataManagementSystem.git` |
| VPS provider | **DigitalOcean** |
| VPS plan | **Basic Droplet — 8 GiB / 4 vCPU / 160 GiB SSD ($48/mo)** |
| VPS public IP | **157.230.164.176** |
| VPS region | **SFO2** |
| Backup bucket | _fill in_ |
| Beta start / end | _fill in_ |
| Beta users (emails) | _fill in_ |
