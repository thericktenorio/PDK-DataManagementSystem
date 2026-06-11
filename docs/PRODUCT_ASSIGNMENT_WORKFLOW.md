# Product Assignment — Full Workflow (Planning)

**Purpose:** Complete design and development plan for the PA lifecycle after intake and clearing auto-fill are working. This doc is the working spec for clearing completion → billing → review → acknowledgments → compensation date.

**Related:** `ROADMAP.md` (Phases 6–8), `docs/LIFECYCLE.md`, `docs/BILLING.md`, `docs/CLEARING.md`, `docs/ACKNOWLEDGMENTS.md`.

---

## Decisions log (locked for implementation)

| # | Topic | Decision |
|---|--------|----------|
| 1 | Ack matching scope | Match PAs in `READY_FOR_REVIEW`, pending ack states, and `PENDING_REJECT_CORRECTION`. Acks **auto-advance** PA to the correct review stage if staff skipped **Review Complete**. |
| 2 | Review UX | **Single Review Complete** button — drop “Start review” / `IN_REVIEW` step. |
| 3 | Terminal label | DB state `CLOSED`; review UI label **Filed**. |
| 4 | Form taxonomy | Expand `form_taxonomy.py`; validate against [Drake ack KB](https://kb.drakesoftware.com/KB/Drake-Tax/10783.htm) + PDF outline titles. |
| 5 | Drake ack file | See `docs/ACKNOWLEDGMENTS.md` (parsed from sample export). |
| 6 | Expected ack count | **Primary:** Client Letter return-type column (text-first). **Fallback:** BILL_01 pages 1–2 + Diagnostic Summary state list. |
| 7 | Paper Filing product | **One** “Paper Filing” product per tax year. |
| 8 | Force completion | Clearing may still show `R`; force counts as **`A`** for TP Comp Dt. |
| 9 | TP Comp Dt | Proprietary rule: **Sunday after** latest `A` when all expected acks are `A`. Pacific (`America/Los_Angeles`). Hover shows date + PST/PDT. |

---

## North-star (your target)

```text
Intake → Clearing (Path A/B) → Complete Clearing
    │
    ├─ QBO ──▶ draft invoice → sent → AWAITING_PAYMENT ──(paid)──▶ READY_FOR_REVIEW
    ├─ Non-QBO ──▶ CLEARING_COMPLETE ──(confirm paid)──▶ READY_FOR_REVIEW
    └─ No-fee ──▶ READY_FOR_REVIEW (immediate)

READY_FOR_REVIEW ──(Review Complete)──▶ PENDING_ACKNOWLEDGMENTS
    │
    ├─ Ack "A" (all expected) ──▶ FILED (review table = done)
    ├─ Ack "R" ──▶ PENDING_REJECT_CORRECTION ──(Review Complete)──▶ PENDING_ACKNOWLEDGMENTS
    ├─ Force Completion ──▶ FILED (with note; clearing may still show R; counts as A for TP Comp Dt)
    └─ Paper File ──▶ product → Paper Filing; ack status A with mail dates

TP Comp Dt (clearing column) = Sunday after the latest A ack date (Pacific),
    only when every expected ack is A (including paper-filed and force-completed).
```

---

## What is already built (code reality)

| Area | Status | Key locations |
|------|--------|---------------|
| Lifecycle states & commands | ✅ Implemented | `core/workflows/lifecycle.py`, `core/models.py` (`LifecycleState`) |
| Complete clearing + validation | ✅ | `clearing/views.py` → `cmd_complete_clearing` |
| Billing after clearing | ✅ (needs prod QBO sign-off) | `billing/services/post_clearing.py`, `invoice_lifecycle.py` |
| QBO paid → review | ✅ | `advance_pas_when_invoice_paid` |
| Non-QBO confirm payment | ✅ | Clearing UI + `cmd_confirm_payment_received` |
| Review queue (2 tables) | ⚠️ Partial | `review/` — Ready + **In review** (not your 4-table model) |
| Ack upload + TIN/form matching | ✅ | `acknowledgments/services/reconcile.py`, `form_taxonomy.py` |
| Ack lifecycle transitions | ✅ | Reject → `PENDING_REJECT_CORRECTION`; all A → `CLOSED` |
| Clearing status columns | ❌ Headers only | `clearing.html` — Rev/Fed/St/Fed Dt/St Dt/**TP Comp Dt** empty |
| Force completion / Paper file | ❌ Not started | — |
| Parser-derived expected ack count | ❌ Planned | `PARSER_ROADMAP.md` ack hints |
| Ack `submission_id` / reject reason | ❌ Not on model | Parser ingests 5 fields today |
| `Paper Filing` product type | ❌ Not in catalog | `Product.PRODUCT_TYPE_*` |

### Lifecycle naming alignment

The codebase uses internal state names that differ slightly from review-module **table labels**:

| Your review table / concept | Code `lifecycle_state` | Notes |
|----------------------------|------------------------|-------|
| Ready for review | `READY_FOR_REVIEW` | Match ✅ |
| Pending acknowledgments | `FILED`, `ACK_RECONCILING` | After **Review Complete** or ack safety-net auto-advance |
| Pending reject correction | `PENDING_REJECT_CORRECTION` | Match ✅ (not shown in review UI yet) |
| Filed *(all acks accepted)* | `CLOSED` | UI label **Filed**; DB stays `CLOSED` |

**UX:** Remove `IN_REVIEW` from the review module — one **Review Complete** button replaces Start review + Mark filed.

---

## Workflow phases (implementation plan)

### W1 — Clearing completion & billing gate

**Goal:** Complete clearing reliably advances the PA; QBO billing checks pass without sending live invoices in dev.

| Step | Action | Status |
|------|--------|--------|
| W1.1 | `cmd_complete_clearing` + field validation | ✅ |
| W1.2 | `on_clearing_completed` — no-fee auto-advance, QBO draft link | ✅ |
| W1.3 | Invoice sent → `AWAITING_PAYMENT` | ✅ |
| W1.4 | Invoice paid → `READY_FOR_REVIEW` | ✅ (`BILLING_PROVIDER=fake` for local) |
| W1.5 | Non-QBO “Confirm payment received” in clearing UI | ✅ |
| W1.6 | Clearing row shows **Pmt Status** badge | ✅ |
| W1.7 | Document + rehearse billing preflight (draft line items, TIN on client, fee > 0) | 📋 Doc/test checklist below |
| W1.8 | Mark ROADMAP Phase 6 ✅ after MVP trial walkthrough | 📋 |

**Billing preflight (no live invoice required):** With `BILLING_PROVIDER=fake`, complete clearing on a QBO PA and verify:

1. Draft invoice created and linked (`AssignmentInvoiceLink`).
2. `/billing/` shows draft with correct fee line.
3. “Send now” (fake) moves PA to `AWAITING_PAYMENT`.
4. Mark paid (fake webhook or billing UI) moves PA to `READY_FOR_REVIEW`.
5. `ProductAssignmentEvent.READY_FOR_REVIEW` exists once (idempotent).

See `docs/MVP_TRIAL.md` and `docs/BILLING.md`.

---

### W2 — Review module (four tables)

**Goal:** Replace the current two-column queue with your four review stages and actions.

| Table | Query (`lifecycle_state`) | Primary action |
|-------|---------------------------|----------------|
| Ready for review | `READY_FOR_REVIEW` | **Review Complete** |
| Pending acknowledgments | `FILED`, `ACK_RECONCILING` | Monitor acks; upload via Acknowledgments module |
| Pending reject correction | `PENDING_REJECT_CORRECTION` | **Review Complete** (return to pending acks) |
| Filed | `CLOSED` | Read-only; optional audit links |

**Row columns (align with clearing/intake):** TIN, client name, tax year, product, filing type, preparer, payment method/status, fee, ack summary (expandable).

| Step | Action |
|------|--------|
| W2.1 | Extend `review/selectors.py` — four querysets + `build_review_row` ack summary via `build_pa_ack_summary` |
| W2.2 | Replace `review.html` — four sections (tabs or stacked cards) |
| W2.3 | **Review Complete** on Ready → `cmd_complete_review`: `READY_FOR_REVIEW` → `FILED` + `expected_ack_count` (from parser or modal) |
| W2.4 | **Remove** Start review / `IN_REVIEW` from UI and primary flow |
| W2.5 | **Review Complete** on Reject Correction → `ACK_RECONCILING` (reuse `cmd_start_ack_reconciling`) |
| W2.6 | Auto-remove row from source table on transition (HTMX/JSON + row move) |
| W2.7 | Role gating unchanged (`review/permissions.py`) |
| W2.8 | Tests: `review/tests/test_phase7.py` expanded for four tables |

**Expected ack count at Review Complete:**

| Source | Priority | Notes |
|--------|----------|-------|
| Parser — Client Letter “return type” / filed-docs table | 1 | Text layer on `extract_client_letter` role; count distinct e-file transmissions |
| Parser — Diagnostic Summary state filings list | 2 | `extract_diagnostic_invoice` role; supplement multi-state |
| Parser — BILL_01 pages 1–2 form index | 3 | If letter incomplete |
| Staff override in Review Complete modal | 4 | Fallback |
| Default `1` | 5 | Last resort |

Parser schema keys (proposed): `expected_transmissions: [{jurisdiction, form_type}]`, `expected_ack_count` (computed). Track in `PARSER_ROADMAP.md`.

---

### W3 — Acknowledgments integration

**Goal:** Drake ack upload drives review table moves, clearing columns, and safety-net auto-advance.

Full ingest spec: **`docs/ACKNOWLEDGMENTS.md`**.

#### Matching rules (confirmed)

- Match key: **TIN** + **form type** + tax year + product type.
- Eligible PA states: `READY_FOR_REVIEW`, `FILED`, `ACK_RECONCILING`, `PENDING_REJECT_CORRECTION`.
- If ack matches a PA still in `READY_FOR_REVIEW`, auto-run review-complete + ack attach (safety net).

#### Per-ack behavior

| Ack status | PA effect |
|------------|-----------|
| `A` | Count toward close; update Fed/St columns; contribute to TP Comp Dt |
| `R` | PA → `PENDING_REJECT_CORRECTION`; TP Comp Dt blank |
| Paper filed (manual) | Treat as `A` with mail date |

#### Multiple acks per PA

- One PA may have many ack rows (federal + multiple states, extensions, amendments).
- **Federal bucket:** 1040-family, 1120-family, 1065, 1041, 990, extension forms tied to federal, etc.
- **State bucket:** state form codes (CA540, HIN15, …).
- UI: expandable sub-row or hover popover listing each `{form, status, date}` color-coded (green A / red R).

#### 3-year e-file window

Only the current tax season’s active window (e.g. 2026 calendar → tax years 2023–2025 electronically fileable) receives Drake acks. Older years → **Paper file** flow (W5); set ack `A` with mail metadata.

`Acknowledgment.is_archived` exists for seasons beyond the window.

#### Ingest extensions (from sample export)

| Field | Model field |
|-------|-------------|
| Reject code | `Acknowledgment.reject_code` |
| Reject detail (Error Detail block) | `Acknowledgment.reject_reason` |
| Submission ID | `Acknowledgment.submission_id` |

See **`docs/ACKNOWLEDGMENTS.md`** for line format.

| Step | Action |
|------|--------|
| W3.1 | Migration: `submission_id`, `reject_code`, `reject_reason` on `Acknowledgment` (+ staging) |
| W3.2 | Replace `_parse_ack_text` with Drake MEF block parser (header, data row, SubmissionId, Error Detail) |
| W3.3 | Expand `ACK_ELIGIBLE_LIFECYCLE_STATES` + safety-net auto-advance from `READY_FOR_REVIEW` |
| W3.4 | Wire `build_pa_ack_summary` into clearing row payload |
| W3.5 | Expand `form_taxonomy.py` using Drake KB + corpus outlines |
| W3.6 | Deprecate `Acknowledgment.product` FK (ROADMAP 8.6) |

---

### W4 — Clearing status columns & TP Comp Dt

**Goal:** Post-clearing columns on the clearing board reflect review/ack progress without opening the review module.

| Column | Source |
|--------|--------|
| Pmt Status | ✅ `pa_billing_context` / `payment_status` |
| Rev Status | Lifecycle label or review stage (Ready / Pending acks / Reject / Filed) |
| Fed Status | Latest federal ack status (`A` / `R` / —) |
| St Status | Aggregate state acks (worst wins: any R → R; else all A → A; partial → progress) |
| Fed Dt | Date of federal ack (or paper-file date) |
| St Dt | Latest state ack date (or “multi” if several) |
| **TP Comp Dt** | See rule below |

#### TP Comp Dt rule (authoritative — proprietary)

**TP Comp Dt** is a firm-specific compensation landmark, not an IRS or industry standard.

```
IF any expected ack is missing OR any ack is not A (unless force-completed / paper-resolved as A):
    TP Comp Dt = blank
ELSE:
    landmark = max(date) over all compensating acks (status A, or force/paper treated as A)
    TP Comp Dt = the Sunday strictly AFTER landmark in America/Los_Angeles
        (if landmark is already a Sunday, use the following Sunday)
```

**Timezone:** Always **Pacific** (`America/Los_Angeles`). Ack `date` values from Drake are date-only; the Sunday rule is evaluated on the **Pacific calendar**.

**Clearing UI:** Show the date in the TP Comp Dt cell; on hover, show the same date with **`PST`** suffix (or **`PDT`** during daylight saving — use `%Z` from Pacific tz for accuracy). Example tooltip: `2025-11-09 PST`.

**Settings:** `FIRM_TIME_ZONE = "America/Los_Angeles"` (fixed for TP Comp Dt; Django `TIME_ZONE` stays UTC for audit timestamps).

**Consistency audit — places using ack-related dates today:**

| Location | Current behavior | Change when implementing W4 |
|----------|------------------|----------------------------|
| `acknowledgments/templates/acknowledgments.html` | `ack.date` as `Y-m-d` | No change |
| `acknowledgments/selectors.py` | Orders acks by `date` | Feed into `compute_tp_comp_date` |
| `analytics/services/etl.py` | Copies `ack.date` to warehouse | Add `tp_comp_date` on PA fact |
| `core/models.py` `completed_at` | Legacy wizard only | **Do not** use for TP Comp Dt |
| `pdk_crm/settings.py` `TIME_ZONE='UTC'` | Server/audit | Add `FIRM_TIME_ZONE` for date rules only |

Implement `compute_tp_comp_date(pa)` in `acknowledgments/selectors.py`. Optionally persist `ProductAssignment.tp_comp_date` (recomputed on ack / force / paper events).

| Step | Action |
|------|--------|
| W4.1 | `compute_tp_comp_date(pa)` — Pacific Sunday-after-latest-A; unit tests (Sunday landmark, all-A gate, force/paper) |
| W4.2 | `build_clearing_status_columns(pa)` → fed/st/rev/tp comp |
| W4.3 | Render `<td>` in `clearing.html` + `title`/popover: `{date} PST` (or PDT) on hover |
| W4.4 | ETL: add `tp_comp_date` to analytics facts if persisted |

---

### W5 — Force completion & paper file

**Goal:** Handle perpetual `R` acks (common on extension clients) without blocking the workflow.

#### Force completion

- Available when: PA in Pending reject correction (or Pending acks with stuck R).
- Action: modal → required note → PA → `CLOSED` (UI **Filed**); clearing Fed/St may still show `R` with **Forced** badge.
- **TP Comp Dt:** force completion counts as **`A`** — use force date (or latest real `A` if mixed) as landmark input.
- Audit: `LifecycleTransition.note` + `ProductAssignment.force_completed_at` (optional) or event payload flag `force_completed: true`.

#### Paper file

- Available when: e-file not possible (outside 3-year window, or staff choice).
- Action: modal per jurisdiction (federal / each state): mailed by firm | client; date sent; tracking; notes.
- Side effects:
  - Product → **Paper Filing** (**one product per tax year** in catalog).
  - Synthetic ack rows status `A` / `PAPER FILED`, `date` = mail date.
  - Re-run TP Comp Dt.

| Step | Action |
|------|--------|
| W5.1 | Add `Paper Filing` product type + seed one row per active `TaxYear` |
| W5.2 | Model: `PaperFilingDetail` (PA, jurisdiction, mailed_by, sent_date, tracking, notes) or JSON on PA |
| W5.3 | API endpoints: `force_complete_review`, `record_paper_filing` |
| W5.4 | UI modals in review module (+ optional clearing row actions) |
| W5.5 | Lifecycle commands + tests |

---

## Suggested build order

```text
W1 (verify billing) → W2 (review UI) → W3 (ack fields + matching polish)
    → W4 (clearing columns + TP Comp Dt) → W5 (force / paper edge cases)
```

Parser ack hints can parallel W2 once schema is defined.

---

## UI/UX notes (brainstorm — not locked)

1. **Expandable PA rows** on clearing/review: child rows list each ack `{form, A/R, date, submission_id}`.
2. **Hover popover** on Fed/St status cells for quick scan without expanding.
3. **Ack progress chip:** `2/3 ✓` with red tint if any R.
4. **Review module layout:** four collapsible cards (mobile-friendly) vs single page with tabs.
5. **Paper file multi-state:** one modal wizard with steps per state form.

---

## Testing checklist (end-to-end)

- [ ] Intake → clearing → complete (Path B)
- [ ] QBO fake: draft → sent → paid → appears in Ready for review
- [ ] Review Complete → Pending acknowledgments
- [ ] Ack upload while still in Ready for review → safety-net auto-advance + correct table
- [ ] Upload ack: federal A + state A → Filed table + TP Comp Dt populated (Sunday rule)
- [ ] Upload R ack → Pending reject correction → Review Complete → re-upload A → Filed
- [ ] Force completion with note on stuck R → Filed + TP Comp Dt set (counts as A)
- [ ] Paper file on pre-window tax year → A dates → TP Comp Dt
- [ ] Clearing columns update live after ack import

---

## Document maintenance

When implementation lands, update:

- `ROADMAP.md` — Phases 6–8 exit criteria
- `docs/LIFECYCLE.md` — review table mapping, TP Comp Dt, safety net
- `docs/CLEARING.md` — status columns, `FIRM_TIME_ZONE`
- `docs/ACKNOWLEDGMENTS.md` — parser + model fields as built
- `docs/REVIEW.md` — optional module doc (create when W2 starts)
