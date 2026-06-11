# Product Assignment lifecycle

Authoritative workflow states for a `ProductAssignment` (PA). Phase 1 will replace the legacy `CompletionState` machine with this model.

See also: `docs/CLEARING.md`, `ROADMAP.md`.

---

## Target states

| State | Meaning |
|-------|---------|
| `IN_CLEARING` | PA is active in daily clearing; fee, payment method, message may be edited |
| `CLEARING_COMPLETE` | Clearing finished; triggers billing (QBO) or advances to review (non-QBO) |
| `AWAITING_PAYMENT` | QBO invoice sent; waiting for payment (skipped for non-QBO) |
| `READY_FOR_REVIEW` | Paid (or non-QBO path); eligible for review queue |
| `IN_REVIEW` | Reviewer claimed / actively reviewing |
| `FILED` | Return filed in Drake; ack upload allowed |
| `ACK_RECONCILING` | Acks imported and being matched to PA |
| `CLOSED` | All acks accepted; PA finished |
| `PENDING_REJECT_CORRECTION` | Reject ack received; staff must resolve reject code |

---

## Transition diagram

```text
IN_CLEARING
    │
    ▼
CLEARING_COMPLETE ──(QBO)──▶ AWAITING_PAYMENT ──(paid)──▶ READY_FOR_REVIEW
    │                              │
    └──(non-QBO)───────────────────┘
                                   │
                                   ▼
                              IN_REVIEW
                                   │
                                   ▼
                                 FILED
                                   │
                                   ▼
                            ACK_RECONCILING
                              │         │
                    (all accepted)   (reject ack)
                              │         │
                              ▼         ▼
                           CLOSED   PENDING_REJECT_CORRECTION
```

---

## Payment-method gates

| Payment method | After `CLEARING_COMPLETE` |
|----------------|---------------------------|
| QBO | → `AWAITING_PAYMENT` until invoice paid → `READY_FOR_REVIEW` |
| Cash, check, Square, TPG, pro bono, etc. | → `READY_FOR_REVIEW` directly (no QBO invoice step) |

---

## Legacy `CompletionState` (deprecated)

The current code uses `core/workflows/completion.py` with states like `PENDING_PARSER`, `PENDING_ACK_COUNT`, and `COMPLETED`. That flow conflates clearing, parser, and ack-count steps.

**Phase 1 (implemented):**

1. `lifecycle_state` on `ProductAssignment` (`completion_state` retained but deprecated).
2. `LifecycleTransition` — append-only audit log for every state change.
3. `ProductAssignmentEvent` — idempotent side-effect markers (`CLEARING_COMPLETED`, `READY_FOR_REVIEW`, etc.); unique per `(PA, event_type)`.
4. Commands in `core/workflows/lifecycle.py` (full transition set).
5. `IN_CLEARING` is set when a client is added to **daily clearing**, not at intake.

Legacy completion wizard (`core/workflows/completion.py`) remains for existing UI until Phase 3 replaces it.

---

## Audit trail

**LifecycleTransition** (every transition): `from_state`, `to_state`, `actor`, `created_at`, optional `note` / `payload`.

**ProductAssignmentEvent** (idempotent side effects): at most one row per `(product_assignment, event_type)` — use for billing hooks, analytics milestones, and deduplicating concurrent workers. Do not use for full history.

## Review module ↔ lifecycle (display mapping)

Staff-facing **review tables** use labels that map to `lifecycle_state` (see **`docs/PRODUCT_ASSIGNMENT_WORKFLOW.md`**):

| Review table | `lifecycle_state` |
|--------------|-------------------|
| Ready for review | `READY_FOR_REVIEW` |
| Pending acknowledgments | `FILED`, `ACK_RECONCILING` |
| Pending reject correction | `PENDING_REJECT_CORRECTION` |
| Filed *(done)* | `CLOSED` |

Optional intermediate: `IN_REVIEW` — **removed from target UX**; single **Review Complete** action instead.

## Ack safety net (decided)

Ack CSV import matches PAs in `READY_FOR_REVIEW`, `FILED`, `ACK_RECONCILING`, and `PENDING_REJECT_CORRECTION`. If staff forgot **Review Complete**, a matching ack auto-advances the PA into ack reconciliation. See `docs/ACKNOWLEDGMENTS.md`.

## Acknowledgments (Phase 8)

- **`expected_ack_count`** on `ProductAssignment` — staff-set at filing (default 1). PA reaches `CLOSED` when received ack count matches and all are accepted (`A`). Parser may suggest a count later (Phase 4/5); staff confirms.
- Reject ack (`R`) → immediate `PENDING_REJECT_CORRECTION`. Corrected acceptance → `ACK_RECONCILING`, then close when complete.
- **Force completion** and **paper file** synthetic acks count as **`A`** for TP Comp Dt. Details: `docs/PRODUCT_ASSIGNMENT_WORKFLOW.md` (W5).

## TP Comp Dt (clearing column — proprietary)

Preparer compensation date on the clearing board:

- **Blank** unless every expected ack is **`A`** (force completion / paper file count as `A`).
- **Set** to the **Sunday after** the latest accepted ack date (Pacific calendar).
- If the latest `A` date is itself a Sunday, use the **following** Sunday.
- **UI:** cell shows the date; hover tooltip shows the same date with **PST** or **PDT**.

Implementation: `compute_tp_comp_date()` + `FIRM_TIME_ZONE = America/Los_Angeles`. Full spec: **`docs/PRODUCT_ASSIGNMENT_WORKFLOW.md`** (W4).

## `is_complete` (legacy)

- **Not** derived from `lifecycle_state` or `completion_state` in `save()`.
- Lifecycle commands **never** set `is_complete`.
- Phase 6: billing uses `CLEARING_COMPLETED` event / `on_clearing_completed()` — not `is_complete`.
- Legacy completion wizard may still set `is_complete` for in-flight data only.
