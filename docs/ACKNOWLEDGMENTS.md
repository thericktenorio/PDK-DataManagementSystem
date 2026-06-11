# Acknowledgments module

Upload, parse, match, and lifecycle integration for Drake MEF acknowledgment files. See **`docs/PRODUCT_ASSIGNMENT_WORKFLOW.md`** for the full PA workflow.

---

## Upload entry point

Staff paste text or upload a file on **`/acknowledgments/`** (`post_acknowledgments`). Parsed rows are matched to `ProductAssignment` records and stored as `Acknowledgment` rows (or `AckStaging` when unmatched).

---

## Drake MEF ack file format (sample-derived)

Based on redacted sample `TEST R ACK.xlsx` (Drake export):

```text
Drake 2024 - MEF ACK files processed
IDNumber   Type      Acc  Date          Name                                     Reject Codes
000000005  1040      R    11-02-2025    CLIENT 5, TEST                           IND-181-01
SubmissionId:  3387962025306aifuwko

                                                    Error Detail
IDNumber      Rule #               Message
000000005     IND-181-01           The Primary Taxpayer did not enter a valid Identity Protection Personal ...
                                   (wrapped message lines)
```

| Field | Source in file | CRM storage (planned) |
|-------|----------------|----------------------|
| TIN | `IDNumber` column | `Acknowledgment.client_tin` |
| Form type | `Type` column (1040, CA540, …) | `Acknowledgment.type` |
| Status | `Acc` column (`A`, `R`, …) | `Acknowledgment.status` |
| Ack date | `Date` (`MM-DD-YYYY`) | `Acknowledgment.date` |
| Client name | `Name` column | `Acknowledgment.client_name` |
| Reject code(s) | `Reject Codes` on data row | `Acknowledgment.reject_code` |
| Reject detail | `Error Detail` block (`Rule #` + `Message`) | `Acknowledgment.reject_reason` |
| Submission ID | Next line `SubmissionId: …` | `Acknowledgment.submission_id` |
| Tax season year | Header `Drake YYYY` | `Acknowledgment.year` / active `TaxSeason` |

**Parser work (W3):** extend `_parse_ack_text` beyond the current 5-token line parser to handle:

1. Header year inference (`Drake (\d{4})`)
2. Fixed-width or whitespace-split data rows
3. `SubmissionId:` following line
4. Optional `Error Detail` section for rejects

**Drake ack code reference:** [Search EF Database, Common Acks, and Rejection Codes](https://kb.drakesoftware.com/KB/Drake-Tax/10783.htm) · [ACK Codes in PCM](https://kb.drakesoftware.com/kb/Drake-Tax/13235.htm). Codes beyond `A` / `R` (e.g. `P`, `D`, `B`) should be normalized or staged for staff review.

---

## Matching rules

### Keys

1. **TIN** (`client_tin` = Drake `IDNumber`)
2. **Form type** (`type` = Drake `Type`: 1040, CA540, HIN15, 1120, …)
3. **Tax year** (from ack header / row)
4. **Product type** (via `acknowledgments/services/form_taxonomy.py`)

### Eligible PA lifecycle states (decided)

Ack import is a **safety net**: matching applies even if staff forgot **Review Complete**.

| State | Match acks? | Auto-advance on match |
|-------|-------------|------------------------|
| `READY_FOR_REVIEW` | ✅ | Yes — treat as review complete + enter ack reconciliation |
| `FILED` | ✅ | Continue ack reconciliation |
| `ACK_RECONCILING` | ✅ | Evaluate close / reject |
| `PENDING_REJECT_CORRECTION` | ✅ | Re-evaluate on new ack |
| `IN_CLEARING`, `CLEARING_COMPLETE`, `AWAITING_PAYMENT` | ❌ | Stage unmatched (or match client only for banner) |
| `CLOSED` | ❌ | Terminal |

**Implementation note:** expand `ACK_ELIGIBLE_LIFECYCLE_STATES` in `reconcile.py` and add `cmd_advance_pa_for_ack_safety_net` when a PA is still in `READY_FOR_REVIEW` (skip `IN_REVIEW` — removed from UX).

### Lifecycle after attach

| Event | PA transition |
|-------|----------------|
| Any `R` ack on PA | → `PENDING_REJECT_CORRECTION`; TP Comp Dt blank |
| All expected acks `A` (or force/paper resolved as `A`) | → `CLOSED` (review UI label: **Filed**) |
| `A` ack but count < expected | Stay in pending acknowledgments |

---

## Federal vs state buckets

Used for clearing columns **Fed Status / St Status / Fed Dt / St Dt**.

- **Federal:** 1040-family, 1120/1065/1041/990, federal extensions (4868, 7004, …) — see `PERSONAL_FORM_TYPES`, `CORPORATE_FORM_TYPES`, `EXTENSION_FORM_TYPES` in `form_taxonomy.py`.
- **State:** state form codes in the same module (CA540, HIN15, …).

**Canonical source:** expand taxonomy from Drake KB + return-status docs; cross-check PDF outline titles in `pdf_manager/fixtures/drake_samples/outline_registry.yaml` as samples arrive. Drake documents federal vs state ack categories in [Return Status: Checking Acknowledgments](https://kb.drakesoftware.com/kb/Drake-Tax/12462.htm).

---

## 3-year e-file window

Only returns within the IRS e-file window receive electronic acks (e.g. calendar 2026 → tax years 2023–2025). Older returns use **Paper file** flow (`docs/PRODUCT_ASSIGNMENT_WORKFLOW.md` W5); ack status stored as `A` with mail date.

`Acknowledgment.is_archived` flags seasons beyond the active window.

---

## Force completion & paper file

| Action | Ack treatment for TP Comp Dt |
|--------|------------------------------|
| **Force completion** | Treated as **`A`** for compensation date; clearing may still display underlying `R` with a “Forced” badge |
| **Paper file** | Synthetic ack row(s) status `A` (or `PAPER FILED`) with mail date; product → **Paper Filing** (one product per tax year) |

---

## Related code

| Path | Role |
|------|------|
| `acknowledgments/views.py` | Upload UI, `_parse_ack_text` |
| `acknowledgments/services/reconcile.py` | Match + lifecycle |
| `acknowledgments/services/form_taxonomy.py` | Form → product family |
| `acknowledgments/selectors.py` | `build_pa_ack_summary` for UI |
| `core/models.py` | `Acknowledgment`, `AckStaging` |
