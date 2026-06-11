# PDK Tax Operations — Development Roadmap

**Architecture decisions (fixed):**

- **CRM:** modular monolith (Django apps = bounded modules)
- **Databases:** `tax_operations` (CRM) · `parser` (pdf_manager) · `analytics` (ETL-fed, later)
- **Parser:** separate app/service + separate DB; CRM stores references and extracted-field snapshots only
- **Production hosting:** office server via **Docker Compose** (not cloud PaaS); staff access via **browser inside existing RDP** (LAN); **tunnel** (e.g. Cloudflare) for public HTTPS only where Intuit/QBO requires it — details in `docs/DEPLOYMENT.md` and Phase 10

```text
┌─────────────────────────────────────────────────────────┐
│  CRM modular monolith (pdk_crm)                         │
│  accounts | intake | core | clearing | billing          │
│  review | acknowledgments | calendar | client_portfolio │
└────────────┬──────────────────────────────┬─────────────┘
             │                              │
             ▼                              ▼
    tax_operations (PostgreSQL)     parser (PostgreSQL)
             │
             │ ETL (Phase 9)
             ▼
    analytics (PostgreSQL / warehouse)
```

---

## Target workflow (north star)

| Step | Stage | Outcome |
|------|--------|---------|
| 0 | Auth | Staff sign-in, org-scoped access |
| 1 | Intake | Client added (new or existing) |
| 2A | Clearing + parser | Upload PDF → fast parse → auto clearing entry, client message, signature/sorted docs → send to client |
| 2B | Clearing manual | Manual entry + manual message (no parser) |
| 3 | Clearing complete | Triggers billing (QBO when applicable) |
| 4 | QBO paid | PA → `READY_FOR_REVIEW` |
| 5 | Review | Human reviews, files in Drake; ack data uploaded when ready |
| 6 | Ack reconcile | Acks paired to PA; accept/reject + date visible |
| 7 | Reject handling | PA → `PENDING_REJECT_CODE` |

**Lifecycle states** (implement these; deprecate old `CompletionState` parser→ack→complete flow):

```text
IN_CLEARING → CLEARING_COMPLETE → AWAITING_PAYMENT (QBO only)
  → READY_FOR_REVIEW → IN_REVIEW → FILED
  → ACK_RECONCILING → CLOSED
                              └→ PENDING_REJECT_CODE (on reject ack)
```

Non-QBO payment methods: `CLEARING_COMPLETE` → `READY_FOR_REVIEW` (skip `AWAITING_PAYMENT`).

---

## Phase 0 — Foundation & repo hygiene ✅ (done)

**Goal:** Stable dev environment; clear module boundaries; blockers removed.

> **Note:** Marked complete for Phase 1 onward. Revisit **0.2** only if `pdf_manager` deploy fails (historical `audit` app note; audit data lives under `core` today).

| Step | Action |
|------|--------|
| 0.1 | Document local run: `compose.yaml`, env files, ports (CRM `:8000`, parser `:8001`) |
| 0.2 | Fix `pdf_manager` deploy blockers (missing `audit` app in `INSTALLED_APPS`) |
| 0.3 | Add CRM `/health/` endpoint; add `healthcheck` for `crm_web` in Compose |
| 0.4 | Confirm DB separation in Compose: `crm_db` ↔ `tax_operations`, `pdf_db` ↔ `parser` |
| 0.5 | Minimal CI: `manage.py check`, CRM tests, `pdf_manager` pytest |
| 0.6 | Enforce modular monolith boundaries: cross-app logic via `services/` and workflow commands, not view-to-view imports |
| 0.7 | Create `docs/LIFECYCLE.md` and `docs/CLEARING.md` (states, transitions, path A vs B) |
| 0.8 | Create `docs/DEPLOYMENT.md` — office prod topology (`compose.yaml` / prod overlay), LAN URL + TLS, tunnel for QBO, firewall rules, backup schedule outline, staging approach (aligns with Phase 10) |

**Exit criteria:** Both services start cleanly; health checks pass; lifecycle and deployment docs written.

---

## Phase 1 — Lifecycle & data model ✅ (done)

**Goal:** One authoritative PA lifecycle replacing `core/workflows/completion.py` parser→ack→complete machine.

Implemented: `lifecycle_state`, `LifecycleTransition`, `core/workflows/lifecycle.py`, parser snapshot fields, `PDF_MANAGER_*` settings. `cmd_complete_clearing` stops at `CLEARING_COMPLETE`; payment gate via `cmd_apply_post_clearing_payment_gate` (Phase 6 wiring).

| Step | Action |
|------|--------|
| 1.1 | Add `lifecycle_state` (or rename/refactor `completion_state`) on `ProductAssignment` with states above |
| 1.2 | Add `lifecycle_events` audit trail (extend `ProductAssignmentEvent` or new model) |
| 1.3 | Implement transition commands in `core/workflows/` (e.g. `cmd_complete_clearing`, `cmd_mark_ready_for_review`, `cmd_mark_filed`, `cmd_set_pending_reject`) |
| 1.4 | Define payment-method gates: QBO → billing path; others → skip to review |
| 1.5 | Mark old completion wizard states deprecated; map any in-flight data if needed |
| 1.6 | Add CRM settings: `PDF_MANAGER_BASE_URL`, parser timeout, optional API key |
| 1.7 | Add CRM fields for parser linkage: `parse_job_uuid`, `parse_result_json`, `parsed_at`, output doc references |

**Exit criteria:** Migrations applied; transition commands tested; old clearing completion flow no longer required for downstream steps.

---

## Phase 2 — Intake (light hardening) ✅ (done)

**Goal:** Reliable entry point before clearing; already mostly built.

Implemented: active tax season scoping, `intake.services.enrollment`, server-side auto-enroll on intake create, remove bug fix, `docs/INTAKE.md`, intake tests.

| Step | Action |
|------|--------|
| 2.1 | Verify new vs existing client flows in `intake/` |
| 2.2 | Ensure `ProductAssignment` + `Intake` + `DailyClearing` creation rules are documented |
| 2.3 | Clean up intake deprecate TODOs where safe |
| 2.4 | Role checks: preparers can intake; data scoped to org/tax season |

**Exit criteria:** Preparer can add client and PA that is eligible for clearing.

---

## Phase 3 — Clearing (path B manual first) ✅ (done)

**Goal:** Staff can complete clearing without parser; clearing completion is the billing gate.

Implemented: lifecycle status per PA row, `validate_pa_ready_for_clearing`, complete/reopen endpoints, client message modal (edit + copy), fee default at PA creation, preparer on `PA.preparer`, legacy completion wizard removed from clearing UI.

| Step | Action |
|------|--------|
| 3.1 | Refactor clearing UI: show lifecycle state, payment method, fee, preparer |
| 3.2 | **Path B:** manual clearing entry — edit client/PA data, compose client message manually |
| 3.3 | “Complete clearing” action → `CLEARING_COMPLETE` via workflow command |
| 3.4 | Remove/replace dummy parser modal and ack-count steps in `clearing.html` |
| 3.5 | Finish clearing TODOs in `clearing/views.py` (fee from product, preparer, status display) |
| 3.6 | Optional: attach/send client message + docs (download or email — start simple) |
| 3.7 | Gate: cannot complete clearing until required fields set (fee, payment method, product, etc.) |

**Exit criteria:** Path B end-to-end: intake → manual clearing → complete clearing → lifecycle at `CLEARING_COMPLETE`.

---

## Phase 4 — Clearing path A (parser integration)

**Goal:** Upload PDF in clearing → auto-populate entry + message + output docs.

| Step | Action |
|------|--------|
| 4.1 | Define **Parser Result Schema v1**: fields for clearing auto-fill, message template vars, ack hints (for later) |
| 4.2 | CRM parser client: upload, poll, fetch detail from `pdf_manager` API |
| 4.3 | **Path A UI:** upload PDF from clearing row/modal |
| 4.4 | On success: create/update clearing entry, store `parse_job_uuid` + `parse_result_json` on PA |
| 4.5 | Surface generated client message (editable before send) |
| 4.6 | Link output PDFs: main packet, signature request, payment voucher (from parser job) |
| 4.7 | Parser failure: allow retry or fall back to path B without blocking workflow |
| 4.8 | Parser DB stays in `parser`; CRM never duplicates full parse job tables |

**Exit criteria:** Path A works for at least one template; path B still available; both paths end at `CLEARING_COMPLETE`.

**Resume / backlog:** `docs/PARSER_ROADMAP.md`, `docs/PATH_A_TESTING.md`, `docs/PATH_A_PDF_UPLOAD.md`.

---

## Phase 5 — Parser quality & speed (in progress)

**Goal:** Sub-5s for text-native PDFs; hybrid extraction behind same API contract.

**Started:** `docs/PARSER_EXTRACTION.md`, extraction schema + `message_ready` gate, optional BILL OCR (`OCR_EXTRACT_BILL`), DRAKE template catalog seed, `ExtractedField` lineage per job, corpus benchmark test.

**Resume / backlog:** `docs/PARSER_ROADMAP.md` (Phase 5.4–5.6, corpus tests, Path A validation).

| Step | Action |
|------|--------|
| 5.1 | Text-first extraction strategy (embedded PDF text before OCR) |
| 5.2 | OCR fallback only when text layer missing/low confidence |
| 5.3 | Field registry in parser DB (template → field keys from schema v1) |
| 5.4 | Remove debug/TODO noise in extraction strategies |
| 5.5 | Benchmark; if sync exceeds budget, add queue + workers (same API contract) |
| 5.6 | Optional: 3–10 parser worker replicas in Compose for peak bursts |

**Exit criteria:** Majority of text-native PDFs parse in <5s; schema v1 stable; no CRM contract changes required.

---

## Phase 6 — Billing (QBO)

**Status:** Code + tests implemented; formal ✅ pending MVP trial sign-off. Full workflow spec: **`docs/PRODUCT_ASSIGNMENT_WORKFLOW.md`** (W1).

**Goal:** Clearing complete triggers billing; paid invoice advances lifecycle.

| Step | Action |
|------|--------|
| 6.1 | **Move billing trigger** from `is_complete` signal to `CLEARING_COMPLETE` (QBO payment method only) |
| 6.2 | Draft invoice via `billing/services/drafts.py`; link PA via `AssignmentInvoiceLink` |
| 6.3 | Send invoice (manual + `auto_send_invoices` after quiet period) |
| 6.4 | Run `process_qbo_events` as Compose worker/cron |
| 6.5 | On invoice `PAID` (webhook + `sync.py`): transition linked PA(s) → `READY_FOR_REVIEW` |
| 6.6 | Non-QBO: transition `CLEARING_COMPLETE` → `READY_FOR_REVIEW` immediately (or after manual “payment confirmed”) |
| 6.7 | Billing UI: show invoice status per client/PA in clearing context |

**Exit criteria:** QBO client: clearing complete → invoice → paid webhook → `READY_FOR_REVIEW`. Non-QBO bypass works.

---

## Phase 7 — Review

**Status:** Two-table queue shipped (`READY_FOR_REVIEW`, `IN_REVIEW`); **four-table review model** (Ready / Pending acks / Reject correction / Filed) planned in **`docs/PRODUCT_ASSIGNMENT_WORKFLOW.md`** (W2).

**Goal:** Human-in-the-loop after payment; gate before ack upload.

| Step | Action |
|------|--------|
| 7.1 | `review` models: queue entry, assigned reviewer, status, notes, timestamps |
| 7.2 | Review queue view: PAs in `READY_FOR_REVIEW` and `IN_REVIEW` |
| 7.3 | Actions: claim/start review, complete review, **mark filed** → `FILED` |
| 7.4 | Role gating (`reviewer` role in `accounts`) |
| 7.5 | Replace empty `review/review.html` stub with functional queue |
| 7.6 | Optional: in-app notifications when PA enters review queue |

**Exit criteria:** Reviewer can process paid assignment through filing; PA reaches `FILED`. Four-table UI, parser ack hint prefill, force complete, and paper file — see **`docs/REVIEW.md`** and **`docs/PRODUCT_ASSIGNMENT_WORKFLOW.md`** (W2, W5).

---

## Phase 8 — Acknowledgments & reject handling ✅ (core done)

**Goal:** Post-filing ack upload, reconcile to PA, reject code workflow.

Implemented: lifecycle-gated ack matching (`FILED`/`ACK_RECONCILING`/`PENDING_REJECT_CORRECTION`), `expected_ack_count` at filing, auto-transitions (`ACK_RECONCILING` → `CLOSED` / `PENDING_REJECT_CORRECTION`), expanded form taxonomy, clearing ack badges, unmatched staging banner, `ACK_ALLOW_AUTO_CREATE_PA` flag (default off). **Remaining:** 8.6 — remove required `Acknowledgment.product` FK once PA linkage is proven in prod; expand matching to `READY_FOR_REVIEW` safety net + Drake MEF parser — see **`docs/ACKNOWLEDGMENTS.md`** and **`docs/PRODUCT_ASSIGNMENT_WORKFLOW.md`** (W3).

| Step | Action |
|------|--------|
| 8.1 | Gate ack upload on `FILED` (or `ACK_RECONCILING`) |
| 8.2 | Repurpose ack staging/matching in `acknowledgments/` for post-filing import |
| 8.3 | Pair acks to `ProductAssignment`; display accept/reject + date |
| 8.4 | Expand form-type taxonomy (`acknowledgments/views.py`) as matching rules mature |
| 8.5 | On reject ack → PA `PENDING_REJECT_CORRECTION`; on all accepted → `CLOSED` |
| 8.6 | Deprecate `Acknowledgment.product` when PA linkage is stable |
| 8.7 | UI: PA detail shows ack status at a glance |

**Exit criteria:** Full ack lifecycle after filing; reject path sets `PENDING_REJECT_CORRECTION`.

**Remaining workflow work (cross-phase):** ~~parser ack hints~~ ✅; optional HTMX row moves (W2.6), fuller review columns, deprecate `Acknowledgment.product` FK — see **`docs/PRODUCT_ASSIGNMENT_WORKFLOW.md`**.

---

## Phase 9 — Analytics database & reporting ✅ (core done; executive BI deferred)

**Goal:** Executive reports without touching `tax_operations` during peak.

**Done (MVP):** `analytics_db` + `analytics_etl`, warehouse schema, `sync_analytics_warehouse`, in-app KPI dashboard (`/analytics/`, manager/owner/developer), `bi_*` views, `docs/ANALYTICS.md`, `docs/POWER_BI.md` (reference only).

**Deferred → Phase 10 / office setup (see below):** Power BI Desktop (Windows or office PC), semantic models / `.pbix`, on-premises data gateway, prod `analytics_reader` credentials. **Mac dev:** use in-app Analytics or office LAN BI; do not rely on Power BI Desktop natively on macOS.

| Step | Status | Action |
|------|--------|--------|
| 9.1 | ✅ | Provision `analytics` PostgreSQL (separate from CRM and parser) |
| 9.2 | ✅ | Star schema: `dim_*`, `fact_*`, `etl_run` / watermarks |
| 9.3 | ✅ | ETL: `manage.py sync_analytics_warehouse` (+ incremental); includes `tp_comp_date` on assignment facts |
| 9.4 | ✅ | `analytics_etl` Compose worker (tune interval via env) |
| 9.5 | **Deferred** | Executive BI (Power BI or Python) on `analytics` only — **read-only** role; no ops DB |
| 9.6 | ✅ | In-app analytics module (warehouse reads only) |
| 9.7 | ✅ | Snapshot semantics in `docs/ANALYTICS.md` |

**Exit criteria (met for ops path):** In-app reports and ETL use `analytics` only; no heavy analytics on `tax_operations`. Executive BI hookup is an explicit follow-on, not a blocker.

**Return-level analytics (next):** Comparison, return profile, async parser Track 2, shareholder agent — phased in **`docs/ANALYTICS_ROADMAP.md`** with technical spec **`docs/RETURN_ANALYTICS.md`** (phases A1–A5; Phase 9.1b parser facts).

### ETL shows zero rows?

ETL copies from **`tax_operations`**. `assignments=0` with `ETL SUCCESS` usually means the CRM database has no clients/PAs yet (fresh volume), not a broken pipeline. Add intake/clearing data in the CRM UI, then re-run `sync_analytics_warehouse --full`.

### Executive BI & analytics endpoint — security (must hold in prod)

Address when implementing **9.5** on the office server (Phase 10). **Do not skip.**

| Risk | Mitigation |
|------|------------|
| Postgres exposed to internet | **Never** publish `analytics_db` on the tunnel or a public IP. Prod Compose overlay: **no** host port on `analytics_db` (dev-only `localhost:5433` is for local Mac/PC tools). |
| BI tool uses ETL/admin creds | Create **`analytics_reader`** (SELECT only on `analytics` / `bi_*`). ETL user stays internal to Compose. |
| Cloud BI (Power BI Service) reaching LAN DB | Use **on-premises data gateway** on office server, or Import refresh on a LAN machine — not raw exposure of Postgres to Microsoft cloud. |
| PII in warehouse (TIN, names) | LAN + RDP only; no **Publish to web**; restrict BI workspace to owner/manager roles. |
| Stale or empty reports | Label “as of last ETL”; monitor `EtlRun` failures in `analytics_etl` logs. |

Reference: `docs/ANALYTICS.md`, `docs/POWER_BI.md`, Phase **10.2** (firewall: tunnel → CRM HTTPS only).

---

## Phase 10 — Production hardening

**Status:** **In progress.** MacBook MVP trial via root `compose.yaml` is the recommended pre-sales path (see **`docs/MVP_TRIAL.md`**). **Phase 10 is not complete** until the **office-server exit criteria** at the bottom of this section are met — a successful Mac demo does not substitute for LAN/TLS, tunnel, backups, or resource limits on the shared host.

**Goal:** Safe, observable, deployable modular monolith + parser sidecar on the **office server** (Docker Compose), with staff access via **browser inside existing RDP** and **public HTTPS only where required** (QBO OAuth/webhooks).

**Hosting (decided):** Production runs on the current office server — not cloud PaaS. Use a low-cost tunnel (e.g. Cloudflare Tunnel) for Intuit/QBO connectivity; keep CRM/parser/Postgres on the LAN.

=================================================================
### 10.MVP — MacBook trial (shareholder demo) — **available now**
=================================================================

Use Docker Desktop on the MacBook; same service topology as prod (CRM + parser + three Postgres DBs + workers). This is **staging option B** from step 10.8 — not office production.

| Step | Action | Status |
|------|--------|--------|
| 10.MVP.1 | Run `docker compose up --build` from repo root; CRM `:8000`, parser `:8001` | ✅ `compose.yaml` |
| 10.MVP.2 | Seed org, tax season, demo users (roles: preparer, reviewer, manager/owner) | ✅ `seed_mvp_demo` + Compose `SEED_MVP_DEMO` |
| 10.MVP.3 | Walk through north-star workflow: intake → clearing (path B) → fake billing → review → acks → analytics | Demo script in `docs/MVP_TRIAL.md` |
| 10.MVP.4 | Optional path A: parser upload with Drake sample PDFs in `pdf_manager/fixtures/drake_samples/` | Requires local PDFs (gitignored) |
| 10.MVP.5 | Present on Mac screen or projector; **no tunnel required** for in-room demo (`FEATURE_QBO=false`, `BILLING_PROVIDER=fake`) | Default in Compose |

**MVP scope limits (explicit):** no Cloudflare tunnel, no LAN TLS, no scheduled backups, no `analytics_reader` / Power BI gateway, no Compose CPU/RAM caps for Hyper-V coexistence, no parser API key enforcement (10.6). QBO sandbox + ngrok is optional post-demo (`docs/BILLING.md`).

======================================================================
### 10.Beta — Cloud shareholder beta (~1–2 months) — **optional path**
======================================================================

**Runbook (start here for deployment):** **`docs/CLOUD_BETA.md`** — subscriptions (with price columns to fill in), architecture roles, deployment sequence, env checklist, cutover to office. Use a **new thread** focused on that doc to stand up `https://crm.godelta.us` (or your hostname).

**Goal:** Let shareholders and staff **use the full app daily** on a stable HTTPS URL (feedback on workflow), while **Phase 10 office exit criteria remain deferred**. Same Compose topology as prod; **not** a second architecture.

**Does not complete Phase 10.** Office server (10.0), RDP + LAN TLS, Hyper-V resource limits, and image-only deploy without git on the host are still required for **Phase 10 complete**.

| Area | Beta choice |
|------|-------------|
| **Compute** | **DigitalOcean Basic Droplet** (8 GiB RAM, 4 vCPU, 160 GiB SSD, US region, **$48/mo**); root `compose.yaml` + `compose.beta.yaml` |
| **Domain + edge** | Domain on **Cloudflare Registrar** (e.g. `godelta.us`); DNS + **Tunnel** + **Access** (allowlist staff emails before Django) |
| **Staff URL** | `https://crm.<domain>` (subdomain; do not expose Postgres/parser ports) |
| **Billing** | Start with `FEATURE_QBO=false`, `BILLING_PROVIDER=fake`; optional QBO sandbox later with Intuit URLs on same hostname |
| **Parser** | Set `PDF_MANAGER_BASE_URL=http://pdf_web:8000` in prod `.env` on VPS (not `localhost:8001` from inside `crm_web`) |
| **Backups** | Nightly `pg_dump` (+ media) to encrypted off-VPS storage (e.g. B2); restore test once |
| **Deploy loop** | Develop on Mac → `git pull` + `compose build` + `up -d` + `migrate` on VPS; brief maintenance window OK for ~5 users |
| **Cutover to office** | `pg_dump` × 3 + volume copy → office Compose; repoint Tunnel/DNS or LAN URL; update Intuit redirect/webhook if hostname changes |

**Security minimum (PII):** See `docs/CLOUD_BETA.md` — Access on `crm.<domain>`; Tunnel only to CRM port; DO Cloud Firewall + UFW; per-user Django roles; 2FA; WISP vendor note (**Cloudflare + DigitalOcean**); US-region Droplet.

**Beta exit criteria:** Five users can complete intake → clearing (path A and/or B) → billing gate → review on the beta URL; backups verified; feedback captured; decision to migrate to office (10.0) or extend beta.

**Before shareholder presentation:** Infrastructure from `docs/CLOUD_BETA.md` + product readiness from **`docs/MVP_TRIAL.md`** (demo script, seed users) and remaining **`ROADMAP.md`** phases as needed.

**MacBook trial (10.MVP) vs cloud beta:** 10.MVP = in-room demo, no tunnel (`docs/MVP_TRIAL.md`). 10.Beta = shared URL, multi-user (`docs/CLOUD_BETA.md`).

=============================================================
### 10.0 — Office server (required for Phase 10 **complete**)
=============================================================

| Step | Action |
|------|--------|
| 10.1 | **Office production deploy:** extend `compose.yaml` (or prod overlay) on office server — CRM monolith + parser service + Postgres (`tax_operations`, `parser`, **`analytics`**). Deploy from **images** (no application source on server). **Prod:** remove `analytics_db` host port mapping; analytics reachable on LAN only. Set Compose **CPU/RAM limits** so CRM/parser do not starve existing RDP VMs; confirm host capacity before go-live. |
| 10.2 | **Internal access + TLS:** reverse proxy (e.g. Caddy/nginx) with TLS on **LAN** for staff (`https://crm.office.internal` or equivalent). Secrets in prod `.env` (restricted file permissions). **Tunnel** exposes only CRM HTTPS paths needed for QBO OAuth + webhooks; firewall — **no public Postgres** (ops, parser, or analytics) and no public Django `/admin/`. |
| 10.1b | **Executive BI hookup (Phase 9.5 carryover):** `analytics_reader` role, optional Power BI gateway on office server, LAN connection docs; confirm `bi_*` views migrated. See Phase 9 security table. |
| 10.3 | **Persistent files:** CRM `media/` and parser `DATA_ROOT` on Docker volumes (dedicated office data disk). **Optional later:** object storage (S3-compatible) if volume growth or off-site file backup warrants it — not required for initial prod. |
| 10.4 | Structured logging + error tracking (e.g. Sentry free tier) |
| 10.5 | **Scheduled backups + restore runbook:** daily `pg_dump` for ops/parser/analytics DBs; robocopy or archive of media/PDF volumes; weekly copy to external drive and/or encrypted off-site (e.g. B2 + restic). Quarterly restore drill documented. |
| 10.6 | Service-to-service auth for parser API |
| 10.7 | QBO webhook + ETL workers as dedicated Compose services/cron on office server |
| 10.8 | **Staging on office server:** second Compose stack (alternate ports / project name) mirroring prod topology — MacBook trial above is **not** a substitute for this when testing office-specific networking |

**Exit criteria (office server only — Phase 10 complete):** Prod Compose stack runs on office server; staff reach CRM via browser inside RDP; tunnel delivers QBO webhooks; backups tested; deploy/restore runbooks exist. See checklist in `docs/DEPLOYMENT.md`.

**MacBook MVP exit criteria (demo-ready, not Phase 10 complete):** Compose stack healthy; demo org + users exist; one full workflow walkthrough rehearsed; shareholders see in-app Analytics (not Power BI Desktop on macOS).

---

## Phase 11 — Polish & secondary modules

**Goal:** UX and peripheral features after core loop is solid.

| Step | Action |
|------|--------|
| 11.1 | `client_portfolio` — PA/season summary views |
| 11.2 | `pdk_calendar` — tie to intake/clearing appointments |
| 11.3 | Auto-send all parser output PDFs; improve send-to-client UX |
| 11.4 | Admin tooling, bulk actions, season archive |
| 11.5 | Expand test coverage on lifecycle transitions and billing webhooks |

---

## Cross-cutting rules (all phases)

- **CRM monolith** owns workflow truth in `tax_operations`; parser owns jobs/files in `parser`; analytics owns report tables in `analytics`.
- **Path B before path A** for go-live risk reduction (manual clearing unblocks billing → review → acks).
- **Parser contract versioning** — bump schema version only when extracted fields change; CRM stores snapshots.
- **No analytics on ops DB** in production.
- **Analytics Postgres** is LAN-internal only in prod; executive BI uses **read-only** creds and must not be exposed via the QBO tunnel (see Phase 9 security table).
- **Feature flags** for QBO, parser path A, auto-send invoice (pattern already in settings).

---

## Phase dependency map

```text
Phase 0 ──▶ Phase 1 ──▶ Phase 2 ──▶ Phase 3 (path B)
                              │
                              ├──▶ Phase 6 (billing) ──▶ Phase 7 (review) ──▶ Phase 8 (acks)
                              │
                              └──▶ Phase 4 (path A) ──▶ Phase 5 (parser speed)

Phase 8 + stable ops ──▶ Phase 9 (analytics DB)

Phase 6–8 stable ──▶ Phase 10 (prod) ──▶ Phase 11 (polish)
```

---

## Recommended build order (summary)

1. **0 → 1 → 2 → 3** — Lifecycle + manual clearing
2. **6 → 7 → 8** — Billing → review → acks (full business loop)
3. **4 → 5** — Parser path + speed (parallel once step 1 done)
4. **9** — Analytics DB after core loop is stable
5. **10.MVP** — MacBook Docker demo (`docs/MVP_TRIAL.md`) when ready to pitch stakeholders; **10.Beta** — optional cloud beta (`docs/CLOUD_BETA.md`) for multi-week shareholder use
6. **10 (office)** → **11** — Office hardening then polish
