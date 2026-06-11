# Review module

Four-table workflow for paid Product Assignments after clearing: **Ready for review** → **Pending acknowledgments** → **Pending reject correction** → **Filed**.

**Related:** `docs/PRODUCT_ASSIGNMENT_WORKFLOW.md` (W2), `docs/LIFECYCLE.md`, `docs/ACKNOWLEDGMENTS.md`.

---

## Tables and lifecycle states

| Review table | `lifecycle_state` values | Primary action |
|--------------|--------------------------|----------------|
| Ready for review | `READY_FOR_REVIEW` | **Review Complete** |
| Pending acknowledgments | `FILED`, `ACK_RECONCILING` | Monitor acks (upload in Acknowledgments module) |
| Pending reject correction | `PENDING_REJECT_CORRECTION` | **Review Complete** (return to pending acks) |
| Filed | `CLOSED` | Read-only |

There is no separate “Start review” step — one **Review Complete** button advances `READY_FOR_REVIEW` → `FILED`.

---

## Review Complete — expected ack count

At **Review Complete**, staff confirm how many Drake acknowledgments to expect (federal + state e-file transmissions).

| Source | Priority | Notes |
|--------|----------|-------|
| Parser — Client Letter e-file list | 1 | `expected_ack_count` + `expected_transmissions[]` on `parse_result_json` |
| Parser — Diagnostic Summary state list | 2 | Supplements multi-state when letter incomplete |
| Parser — BILL_01 form index | 3 | Fallback when letter/diagnostic incomplete |
| Staff override in modal | 4 | Prompt default from parser when available; else `1` |

**Code:** `clearing/services/parser_schema.py` (`suggested_expected_ack_count`), `review/selectors.py` (`build_review_row`), `review/templates/review/review.html` (modal prefill).

---

## Other actions

| Action | When | Effect |
|--------|------|--------|
| **Force complete** | Stuck `R` acks | `CLOSED` with note; counts as `A` for TP Comp Dt |
| **Paper file** | Outside e-file window or staff choice | Synthetic `A` acks; product → Paper Filing |

See `docs/PRODUCT_ASSIGNMENT_WORKFLOW.md` (W5).

---

## Permissions

`reviewer` role (and above) via `review/permissions.py`.

---

## Tests

```bash
docker compose exec crm_web python manage.py test review.tests.test_phase7 review.tests.test_parser_ack_hints -v 2
```

---

## Key files

| Path | Purpose |
|------|---------|
| `review/selectors.py` | Four table querysets, `build_review_row` |
| `review/views.py` | Complete review, force complete, paper file |
| `review/services/queue.py` | Lifecycle command wrappers |
| `review/templates/review/review.html` | Four-table UI |
