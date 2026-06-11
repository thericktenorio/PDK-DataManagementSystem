# Track C agent — OpenAI setup (beta Droplet)

Shareholder analytics agent (`/analytics/` → **Shareholder agent** panel). Queries the **analytics warehouse only** via governed SQL on `bi_*` views.

**Code:** `pdk_crm/analytics/services/agent.py`  
**Roadmap:** `docs/ANALYTICS_ROADMAP.md` (A5)

---

## 1. OpenAI Platform (before enabling agent)

Do this on [platform.openai.com](https://platform.openai.com) with the **owner** account (not preparer staff).

| Step | Action |
|------|--------|
| 1 | Create or confirm **organization** for PDK |
| 2 | **Billing** → add payment method |
| 3 | **Limits** → set **monthly budget cap** (~$50 for beta) |
| 4 | **Data controls** → confirm **NO** opt-in to API data sharing for model training |
| 5 | **API keys** → **Create new secret key** (server-only; never commit to git) |

Recommended model: **`gpt-4o-mini`** (cost-effective for text-to-SQL + short summaries).

---

## 2. Droplet environment variables

Add to production `.env` (or Compose `environment` for `crm_web`):

```bash
AGENT_ENABLED=true
AGENT_LLM_API_KEY=sk-...          # server-only; rotate if exposed
AGENT_LLM_MODEL=gpt-4o-mini
AGENT_LLM_BASE_URL=https://api.openai.com/v1
AGENT_LLM_TIMEOUT_SECONDS=60
```

`ANALYTICS_ENABLED=true` must already be set. Agent uses the **`analytics`** DB connection only.

Restart CRM after changes:

```bash
docker compose up -d crm_web
```

---

## 3. Smoke test from Droplet

SSH to the 8GB Droplet and run (replace key if using env file instead):

```bash
# Models list
curl -sS https://api.openai.com/v1/models \
  -H "Authorization: Bearer $AGENT_LLM_API_KEY" \
  | head -c 500

# Minimal chat completion
curl -sS https://api.openai.com/v1/chat/completions \
  -H "Authorization: Bearer $AGENT_LLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Reply with OK"}],
    "max_tokens": 5
  }'
```

In-app: log in as **owner** or **developer** → `/analytics/` → ask a simple question (e.g. assignment count by lifecycle state).

Optional automated smoke (live API, compares to Track A dashboard):

```bash
AGENT_LLM_SMOKE=1 AGENT_LLM_API_KEY=sk-... \
  docker compose exec crm_web python manage.py test analytics.tests.test_agent.AgentLiveSmokeTests -v 2
```

---

## 4. Privacy & security checklist

| Control | Implementation |
|---------|----------------|
| Server-side only | API key on Droplet env; never in browser or mobile |
| Role gate | **Owner + developer** only (`AGENT_ACCESS_ROLES`); managers see Track A dashboard but not agent |
| No ops DB | Agent connection = `analytics` warehouse; cannot query `tax_operations` or parser |
| SQL guard | `SELECT` only; allowlisted `bi_*` views; `LIMIT` ≤ 500; no multi-statement |
| Audit log | `analytics_agentqueryaudit` — question hash, SQL text, user email, status |
| Minimize PII in prompts | Catalog instructs aggregates; avoid `tin` in SELECT; mask in UI summaries |
| Staleness | UI shows last ETL time + coverage disclaimer (N of M parsed returns) |
| Cost cap | OpenAI monthly budget + `AGENT_ENABLED` kill switch |
| Training opt-out | Confirm disabled in OpenAI org data controls |

---

## 5. ETL schedule (infra)

`analytics_etl` worker runs `sync_analytics_warehouse` at **:00** and **:30** each hour (wall-clock), after an initial `--full` on startup.

Manual sync:

```bash
docker compose exec crm_web python manage.py sync_analytics_warehouse
```

---

## 6. Return-level questions (Track 2 / A2)

When parser Track 2 and ETL A2 ship, these views join the agent catalog:

- `bi_return_metrics`, `bi_return_coverage`, `bi_return_comparison`, `bi_return_profile`

Until then, agent answers operations KPIs from `bi_assignments` and shows honest coverage using `has_parser_snapshot` (Path B rows = ops-only, no return facts).

See `docs/RETURN_ANALYTICS.md`.
