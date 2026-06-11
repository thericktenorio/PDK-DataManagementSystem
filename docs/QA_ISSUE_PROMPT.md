# QA issue thread — copy-paste prompt

Use this when self-testing before the shareholder presentation. Start a **new Cursor thread per issue** (or per small group of related issues). Paste the block below and fill in the `[brackets]`.

---

## Standard prompt (copy from here)

```markdown
## Context
- **Goal:** Pre-shareholder QA — find and fix issues before presentation on `https://pdk.godelta.us`
- **Environment where I saw the issue:** [droplet | local Mac | both]
- **Beta host:** `godelta-beta` — `/opt/pdk/pdk_crm_postgresql`
- **Local repo:** `pdk_crm_postgresql` (Mac, Docker Compose)
- **Workflow preference:** Reproduce on droplet when possible → fix in repo → verify locally if helpful → deploy to droplet → confirm on live URL

## Issue
**Area / page:** [e.g. Clearing → global upload, Review queue, Intake form]

**Steps to reproduce:**
1. [Login as preparer@demo.pdk.local / etc.]
2. […]
3. […]

**Expected:**
[What should happen]

**Actual:**
[What happened — error message, screenshot description, HTTP status, etc.]

**Severity:** [blocker | major | minor | cosmetic]

**Notes:** [Path A vs B, browser, sample PDF, PA lifecycle state, etc.]

## What I want from you
1. **Diagnose** the root cause (check codebase; do not guess).
2. **Implement the fix** in the repo — minimal, focused diff; match existing conventions.
3. **When the code change is complete**, give me **ordered steps** in two sections:

   ### A. Local (Mac)
   - Commands to pull/build/test
   - How to verify the fix locally (specific URL, user, action)
   - Any pytest or manage.py checks to run

   ### B. Droplet (beta)
   - Exact commands on `godelta-beta` (`git pull`, `bash scripts/beta/deploy.sh`, etc.)
   - How to verify on `https://pdk.godelta.us` (or `curl` on server if Access blocks you)
   - What success looks like at end of `deploy.sh` (e.g. `disposition route OK`)

4. **Do not commit or push** unless I explicitly ask.
5. If the issue is droplet-only (env, cache, data) and not a code bug, say so and give infra steps only.

## Reference docs (if relevant)
- `docs/MVP_TRIAL.md` — demo script
- `docs/CLOUD_BETA.md` — droplet deploy
- `docs/PATH_A_PDF_UPLOAD.md` — global upload / parser
- `ROADMAP.md` — phase context
```

---

## Short prompt (quick bugs)

```markdown
**QA (pre-shareholder)** — Issue on [droplet/local]: [one-line summary]

Repro: [2–3 steps]
Expected: […]
Actual: […]

Fix in repo, then give ordered **Local** and **Droplet** verify steps. No commit unless I ask.
```

---

## Multi-issue session (same thread)

Use only when issues are tightly related (same page/feature). Otherwise prefer one thread per issue.

```markdown
## QA batch — [feature area]
Testing on: [droplet | local]

| # | Issue | Severity | Status |
|---|--------|----------|--------|
| 1 | […] | […] | open |
| 2 | […] | […] | open |

Work **one issue at a time**. After each fix: local verify → droplet deploy steps → mark done before starting the next.
```

---

## Post-fix checklist (you run; agent can remind you)

### Local
```bash
cd /path/to/pdk_crm_postgresql
git pull   # if collaborating
docker compose up --build -d   # or targeted service rebuild
# Optional:
docker compose exec crm_web python manage.py check
docker compose exec crm_web pytest path/to/test -q
# Manual: http://localhost:8000 — repeat repro steps → confirm fixed
```

### Droplet
```bash
ssh root@godelta-beta   # or your SSH alias
cd /opt/pdk/pdk_crm_postgresql
git pull --ff-only
bash scripts/beta/deploy.sh
# Expect: CRM healthy, disposition route OK (if parser touched)
# Manual: https://pdk.godelta.us — same repro steps → confirm fixed
```

### After all fixes in a session (when you ask agent to commit)
```bash
# On Mac — after agent commits
git push origin main

# On droplet
git pull --ff-only && bash scripts/beta/deploy.sh
```

---

## Demo users (beta / local)

| Email | Role |
|-------|------|
| `preparer@demo.pdk.local` | Intake, clearing |
| `reviewer@demo.pdk.local` | Review, acks |
| `manager@demo.pdk.local` | Analytics |
| `developer@demo.pdk.local` | Admin |

Password: `demo-mvp` unless `MVP_DEMO_PASSWORD` was changed in `.env.docker`.

---

## Tips for good issue reports

- Include **lifecycle state** if clearing/review/billing (e.g. `IN_CLEARING`, `READY_FOR_REVIEW`).
- Say **Path A or B** for clearing/parser issues.
- Paste **exact error text** from UI or browser network tab.
- Note if **only broken on droplet** (often deploy/env) vs **both** (usually code).
