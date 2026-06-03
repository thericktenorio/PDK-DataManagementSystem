# Clearing workflow

Clearing is where staff finalize client data, compose the client message, and mark a `ProductAssignment` ready for billing/review.

See also: `docs/LIFECYCLE.md`, `ROADMAP.md` (Phases 3–4).

---

## Entry

A PA enters clearing when:

1. Client is added via **intake** (`Intake` + `ProductAssignment` created), then
2. Client is added to **daily clearing** (`DailyClearing.is_active = True`).

See `docs/INTAKE.md` for intake creation rules. Helpers: `core.utils.get_or_create_intake`, `get_or_create_product_assignment`, `intake.services.enrollment.enroll_client_in_intake`.

---

## Path A vs Path B

| | Path A (parser) | Path B (manual) |
|---|-----------------|-----------------|
| **When** | Phase 4+ | Phase 3 (go-live first) |
| **Input** | Upload PDF in clearing | Staff edits fields by hand |
| **Output** | Auto-filled entry, generated message, sorted/signature PDFs | Manual message; optional attachments |
| **Failure** | Retry or fall back to path B | N/A |
| **End state** | `CLEARING_COMPLETE` | `CLEARING_COMPLETE` |

**Build order:** Path B first so billing → review → acks can ship without parser dependency.

---

## Required fields before complete

Staff cannot complete clearing until:

- Product / tax year / filing type
- Fee (auto-filled from `product.default_price` at PA creation; must be &gt; 0 unless no-fee payment method)
- Payment method
- Preparer (`ProductAssignment.preparer`)
- Client message (`closing_message_text`)

---

## Complete clearing action

“Complete clearing” runs `cmd_complete_clearing` → PA `lifecycle_state = CLEARING_COMPLETE`.

Validation (`validate_pa_ready_for_clearing`) blocks completion until product, tax year, filing type, payment method, preparer (`ProductAssignment.preparer`), client message (`closing_message_text`), and fee rules are satisfied. Fee must be &gt; 0 unless payment method is no-fee (pro bono / dependent). Verify product catalog `default_price` values are maintained — fee is auto-filled from `product.default_price` at PA creation.

Staff can **unlock** a row from `CLEARING_COMPLETE` back to `IN_CLEARING` via `cmd_reopen_clearing`; fee must be explicitly confirmed (stricter copy for QBO).

Legacy completion wizard (`start_completion` → parser/ack steps → `finalize_completion`) is no longer used from the clearing UI; endpoints remain for in-flight data only.

---

## Client message (Path B)

Each PA row has a message button opening a modal to edit `closing_message_text`, save, and **copy to clipboard** for paste into email/SMS/etc. Message is required before complete clearing.

---

## Preparer vs appointment

**Preparer** is stored on `ProductAssignment.preparer`. The appointment type column still autosaves to `Appointment` (Calendar module will own scheduling later).

---

## Billing gate

`CLEARING_COMPLETE` is the billing trigger (Phase 6):

- **QBO:** draft invoice (quiet period) → send → `AWAITING_PAYMENT` → paid → `READY_FOR_REVIEW`
- **Non-QBO:** staff **Confirm payment received** → `READY_FOR_REVIEW`
- **No-fee:** auto → `READY_FOR_REVIEW`

See `docs/BILLING.md`.

---

## Parser integration (Path A preview)

CRM stores on the PA (Phase 1.7):

- `parse_job_uuid` — reference to parser job
- `parse_result_json` — snapshot of extracted fields (schema v1)
- `parsed_at`
- Output doc paths/URLs (main packet, signature request, payment voucher)

Parser DB (`pdf_manager`) owns full job tables; CRM never duplicates them.

CRM calls parser via `PDF_MANAGER_BASE_URL` (Phase 1.6): upload → poll → fetch detail.

---

## UI modules

| Module | Role |
|--------|------|
| `clearing/` | Daily clearing board, add client, complete clearing |
| `intake/` | New/existing client entry before clearing |
| `core/workflows/` | Transition commands and guards |

Cross-app calls use services/workflows, not view imports (see `docs/LOCAL_DEV.md`).
