# Billing (Phase 6)

QBO invoicing wired to the PA lifecycle. See `docs/LIFECYCLE.md`, `ROADMAP.md`.

---

## Flow summary

| Payment method | After clearing complete | Advance to review |
|----------------|-------------------------|-------------------|
| QBO | Draft invoice linked; stay `CLEARING_COMPLETE` | Invoice **sent** → `AWAITING_PAYMENT`; **paid** → `READY_FOR_REVIEW` |
| Cash, check, Square, TPG, etc. | Stay `CLEARING_COMPLETE` | Staff **Confirm payment received** |
| No-fee (pro bono / dependent) | Auto → `READY_FOR_REVIEW` | N/A |

**Quiet period:** completed QBO PAs join a per-client draft; `auto_send_invoices` sends after `BILLING_QUIET_PERIOD_MINUTES` when `FEATURE_AUTO_SEND_INVOICES=true`.

---

## Environment (`.env.development`)

Copy these into `pdk_crm/.env.development` (not committed; see `.gitignore`).

```bash
# Core
SECRET_KEY=your-dev-secret
DEBUG=True
USE_SQLITE=true
DJANGO_ENV=development

# Billing — everyday local work (no Intuit)
FEATURE_QBO=false
BILLING_PROVIDER=fake
FEATURE_AUTO_SEND_INVOICES=false
BILLING_QUIET_PERIOD_MINUTES=5

# QBO sandbox (enable when testing Intuit)
# FEATURE_QBO=true
# BILLING_PROVIDER=qbo
# INTUIT_ENV=sandbox
# INTUIT_CLIENT_ID=
# INTUIT_CLIENT_SECRET=
# INTUIT_REDIRECT_URI=https://YOUR-NGROK-HOST/billing/qbo/callback/
# QBO_WEBHOOK_VERIFIER_TOKEN=
# FEATURE_AUTO_SEND_INVOICES=false

# Optional sandbox shortcuts
# QBO_DEFAULT_ITEM_ID=
# QBO_DEFAULT_ITEM_NAME=Tax Preparation
# QBO_ENABLE_CARD=true
# QBO_ENABLE_ACH=true
```

### ngrok (local QBO)

1. `ngrok http 8000`
2. Register redirect URI and webhook URL in the Intuit developer app:
   - Redirect: `https://<ngrok-host>/billing/qbo/callback/`
   - Webhook: `https://<ngrok-host>/billing/qbo/webhook/`
3. Add ngrok host to `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` in `.env.development`.
4. Visit `/billing/qbo/connect/` while logged in.

Production uses a stable tunnel (see `docs/DEPLOYMENT.md`).

---

## Compose workers

| Service | Command | Interval |
|---------|---------|----------|
| `billing_process_qbo_events` | `process_qbo_events` | ~2 min |
| `billing_auto_send_invoices` | `auto_send_invoices` | ~5 min (no-op if `FEATURE_AUTO_SEND_INVOICES=false`) |

---

## UI

- **Clearing row:** lifecycle badge, invoice badge (draft/sent/partial), Confirm paid (non-QBO), Unlock with tiered warnings.
- **`/billing/`:** draft queue, sent/unpaid, recent paid, QBO errors, manual Send now.

---

## Key modules

| Path | Role |
|------|------|
| `billing/services/post_clearing.py` | Draft link + no-fee advance after clearing |
| `billing/services/invoice_lifecycle.py` | Sent → awaiting; paid → review |
| `billing/selectors.py` | PA billing context for UI |
| `core/workflows/lifecycle.py` | `cmd_confirm_payment_received`, reopen tiers |

Legacy `is_complete` billing signal removed (Phase 6).
