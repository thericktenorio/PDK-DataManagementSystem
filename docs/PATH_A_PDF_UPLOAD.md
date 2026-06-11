# Path A — global PDF upload & auto-enrollment

Spec for **header-level “Upload Tax PDF”** on the clearing page: TIN match, auto-create client/clearing rows, conflict modal, and audit-friendly replace/cancel.

**Testing checklist:** `docs/PATH_A_TESTING.md`. **Parser fields:** `docs/PARSER_EXTRACTION.md` (+ `taxpayer_tin` below).

---

## Goals

1. Staff upload **one Drake PDF** from the clearing header and get **near-complete data capture** (parse + enrollment).
2. Keep **per-row Upload Drake PDF** buttons unchanged (second path into Path A).
3. Reuse existing intake/clearing enrollment (`enroll_client_in_intake`, `activate_client_in_clearing`).
4. Preserve **audit trail** on cancel, replace, and void.

---

## UI

### Placement

Next to **Add New Client** in the clearing search/header bar (`clearing.html`).

| Control | Label / a11y |
|---------|----------------|
| Button | **Upload Tax PDF** (or Drake PDF icon + `title="Upload Drake PDF"`) |
| Action | Opens file picker → `application/pdf` only |

Per-row `parse-pdf-btn` controls: **no change**.

### New modals

| Modal | When |
|-------|------|
| **Enrollment** | Need filing type + product before creating PA (all auto-create branches) |
| **Clearing conflict** | TIN matches client already on active `DailyClearing` |

---

## Parser prerequisites (schema v1 extension)

Add to Track 1 **sync** extraction (same parse job as clearing):

| Field | Tier | Source (priority) | Notes |
|-------|------|-------------------|-------|
| `taxpayer_tin` | A | Diagnostic Summary → Comparison → 1040 page 1 | Normalize to 9 digits; strip dashes |
| `taxpayer_full_name` | C | Already v1 | Used for new `Client.name` when creating |
| `tax_year` | A | Already v1 | Drives `TaxYear` on new PA |
| (existing v1) | | Client Letter, fees, etc. | `apply_parser_pdf` unchanged |

**Joint returns:** Match CRM on **primary taxpayer TIN** (first SSN on Diagnostic / Comparison footer). Document in extraction tests.

**Not in this phase:** Infer filing type / product from PDF — staff selects in **Enrollment modal**.

Bump parser/CRM `SCHEMA_VERSION` only if key semantics change; adding `taxpayer_tin` is a minor catalog extension.

---

## End-to-end flow

```text
[Upload Tax PDF] → file selected
        │
        ▼
POST /clearing/parse-pdf/global/  (proposed)
        │
        ├─► pdf_manager: parse job (Track 1 sync)
        │       extract v1 + taxpayer_tin
        │
        ▼
Normalize TIN → lookup Client by TIN (org-scoped)
        │
        ├─► NO MATCH ──────────────────────────────┐
        │                                           │
        ├─► MATCH, no active DailyClearing ─────────┤
        │       (current tax season)                │
        │                                           │
        └─► MATCH, active DailyClearing ────────────┤
                │                                   │
                ▼                                   │
        Clearing conflict modal                     │
        (Cancel | New Entry | Replace)              │
                │                                   │
                └───────────────────────────────────┤
                                                    ▼
                              Enrollment modal (filing type + product)
                              (skip if Replace targets existing PA
                               and FT/product already set — see below)
                                                    │
                                                    ▼
                              Create/update Client, Intake, DailyClearing, PA
                                                    │
                                                    ▼
                              apply_parser_pdf(target_pa, file_or_job_id)
                                                    │
                                                    ▼
                              JSON response → refresh clearing row(s)
```

### Phase 1 API strategy (recommended)

**Two-step** to support modals without re-uploading PDF:

1. **`POST /clearing/parse-pdf/global/preview/`** — upload file, run parse, return `{ parse_job_uuid, extracted: { tin, name, tax_year, ... }, match: { ... } }`. Store file on parser job; CRM holds **staging ref** only.
2. **`POST /clearing/parse-pdf/global/commit/`** — body: `{ parse_job_uuid, action, client_id?, pa_id?, filing_type_id, product_id }`. Completes enrollment + links PA.

Alternative: single multipart endpoint with `action` on second request using session staging — document chosen approach in implementation PR.

---

## Branch rules

### A — No client match (`taxpayer_tin` not in CRM)

**Decision:** Auto-create client (option A).

1. Create `Client` with extracted `taxpayer_tin`, `taxpayer_full_name` (fallback: “Unknown” + TIN).
2. Show **Enrollment modal** — user picks **filing type** + **product** (tax year from PDF, validate against `get_valid_tax_years()`).
3. `enroll_client_in_intake(client)`
4. `activate_client_in_clearing(client, actor=request.user)`
5. Create or select PA for chosen product/tax year (see `get_or_create_product_assignment_for_tax_year` if tax year differs from default).
6. `apply_parser_pdf(pa, …)` linking `parse_job_uuid`.
7. Mark parser job **`APPLIED`** (see § Parser job disposition).

### B — Client match, no active clearing entry

**“No entry”** = no `DailyClearing` with `is_active=True` for **active tax season**.

1. **Enrollment modal** (filing type + product).
2. `get_or_create_intake(client)`
3. `activate_client_in_clearing(client, actor=request.user)`
4. Create PA per modal selections.
5. `apply_parser_pdf(pa, …)`.

### C — Client match, already on clearing

Show **Clearing conflict modal**.

**Header copy:** TIN and name found; client already on clearing.

**Table:** All **active** PAs for this client on current season’s intake/clearing:

| Column | Source |
|--------|--------|
| Tax year | `pa.tax_year` |
| Filing type | `pa.filing_type` |
| Product | `pa.product.product_type` |

**Buttons**

| Button | Behavior |
|--------|----------|
| **Cancel** | Parser job → `CANCELLED`; no CRM changes; see § Cancel |
| **New Entry** | Enrollment modal if needed → `add_product_assignment` pattern (new subrow PA) → `apply_parser_pdf` on **new** PA |
| **Replace Entry** | Enable **single-select** radio on one PA → validate not locked → void + new PA or void + re-link — see § Replace |

---

## Replace entry (audit-friendly)

**User intent:** One PDF ↔ one product assignment. **Only one** PA selectable.

### Lock guard

If selected PA `lifecycle_state != IN_CLEARING` (`is_pa_locked_for_editing`):

- **Block** replace.
- Message: *“This entry has already completed clearing. Create a new entry with the appropriate fee instead.”*
- Offer **New Entry** path only (no replace).

### Recommended audit pattern (void + supersede)

Avoid silent overwrite of `parse_result_json` on the same PA.

1. **Void** selected PA (implementation adds metadata):

   | Field / event | Purpose |
   |---------------|---------|
   | `is_active=False` on voided PA | Hide from default clearing board (or show struck-through — UX choice) |
   | `voided_at`, `voided_by`, `void_reason=PDF_REPLACED` | Audit columns (new migration) |
   | `superseded_by_pa_id` | Link to replacement PA |
   | `ProductAssignmentEvent` `PARSE_SUPERSEDED` | Lifecycle audit trail with old `parse_job_uuid` |

2. **Create new PA** (subrow) with same client; copy filing type / product / tax year from voided PA unless Enrollment modal overrides.

3. **`apply_parser_pdf(new_pa, …)`** with new parse job (or same `parse_job_uuid` from preview — prefer **same job** from global preview commit).

4. Voided PA **retains** historical `parse_result_json` and fee/message for shareholder audit.

**Alternative rejected for v1:** In-place overwrite of same PA without void marker — poor audit visibility.

Document final column names in migration PR; this spec defines required **semantics**.

---

## Cancel (audit)

**Requirement:** Retain parse data; mark cancelled.

### Parser DB (`ParseJob`)

Add status value:

```text
PENDING → SUCCESS (parse finished)
       → CANCELLED (user cancelled from conflict modal)
       → APPLIED (committed to a PA)
       → FAILED
```

- **`CANCELLED`:** Extraction and output PDFs remain stored; job not linked to any PA (or `linked_pa_id` null).
- Optional: `cancelled_at`, `cancelled_by_user_id` on job or `AuditEvent`.

### CRM

- No `Client` / `PA` / `DailyClearing` changes on Cancel.
- Optional: `ParseUploadStaging` row (ephemeral) deleted on cancel — staging only, not warehouse.

**No delete** of parser artifacts for v1 (supports forensic review).

---

## Enrollment modal

Shown for branches **A**, **B**, and **New Entry** (and **Replace** when product/filing type not copied).

| Field | Source |
|-------|--------|
| Tax year | Read-only from `tax_year` extract (allow override only if invalid vs catalog) |
| Filing type | User select (`FilingType` dropdown) |
| Product | User select (filtered by tax year, dedupe by `product_type`) |

Pre-fill filing type from `Client.filing_type` when set.

**Future:** Infer filing type / product from PDF outline (1040 vs 1120-S) — out of scope v1.

---

## Intake sync

Use existing helpers (same as `create_new_client` / `add_client_to_clearing`):

```python
enroll_client_in_intake(client)
activate_client_in_clearing(client, actor=request.user)
```

Ensures `Intake` exists and PAs transition to `IN_CLEARING` via `enter_clearing_for_client_assignments`.

**New subrow:** `add_product_assignment` API (existing) after client on board.

---

## CRM / parser integration summary

| Component | Change |
|-----------|--------|
| `clearing.html` | Header upload button + modals |
| `clearing/views.py` | `parse_pdf_global_preview`, `parse_pdf_global_commit` |
| `clearing/services/parse_upload.py` | Optional: accept `parse_job_uuid` reuse |
| `clearing/services/global_parse.py` | **New** — match, branch, void, commit |
| `core/models.py` | PA void/supersede fields; optional staging model |
| `core/workflows/lifecycle.py` | `cmd_void_pa_for_parse_replace` (proposed) |
| `pdf_manager` | `taxpayer_tin` extraction; `ParseJob.Status.CANCELLED`, `APPLIED` |
| `parser_schema.py` | Add `taxpayer_tin` to public keys if needed in preview API |

Per-row `parse_pdf_upload(pa_id)`: **unchanged**.

---

## Response shapes (sketch)

### Preview success

```json
{
  "status": "success",
  "parse_job_uuid": "…",
  "extracted": {
    "taxpayer_tin": "123456789",
    "taxpayer_full_name": "JOHN & JANE DOE",
    "tax_year": "2024",
    "message_ready": true
  },
  "match": {
    "client_id": 42,
    "client_name": "…",
    "on_clearing": true,
    "product_assignments": [
      {"id": 101, "tax_year": 2024, "filing_type": "Married Joint", "product_type": "1040 Preparation", "is_locked": false}
    ]
  }
}
```

`match.client_id` null when no TIN match.

### Commit success

```json
{
  "status": "success",
  "action": "new_entry",
  "client_id": 42,
  "product_assignment_id": 105,
  "voided_product_assignment_id": null,
  "parse_job_uuid": "…",
  "message": "…",
  "downloads": { }
}
```

---

## Security & permissions

- Same auth as clearing: `@login_required`, org-scoped `Client` lookup.
- TIN is PII — log minimal fields; do not echo full TIN in client-side errors.
- Validate uploaded file type and size (match existing per-row limits).

---

## Tests to add

| Test module | Cases |
|-------------|-------|
| `clearing/tests/test_path_a_global_upload.py` | No match → client created; match off clearing → activated; conflict modal actions; cancel → job CANCELLED; replace blocked when locked; replace voids old PA |
| `pdf_manager/tests/test_tin_extraction.py` | Diagnostic / Comparison fixtures |
| Extend `test_clearing_phase4.py` | `taxpayer_tin` in snapshot when present |

---

## Open implementation choices (resolve in PR)

1. Preview staging: server-side cache keyed by `parse_job_uuid` vs temp file re-upload on commit.
2. Voided PA visibility on clearing board (hidden vs gray “voided” row).
3. Whether `taxpayer_tin` appears in CRM `parse_result_json` or preview-only until commit.

---

## Related docs

| Doc | Role |
|-----|------|
| `docs/PATH_A_TESTING.md` | Sign-off checklist |
| `docs/PARSER_ROADMAP.md` | Parser pause/resume |
| `docs/CLEARING.md` | Path A vs B |
| `docs/ANALYTICS_ROADMAP.md` | Track 2 after Path A sign-off |

---

## Revision history

| Version | Date | Notes |
|---------|------|-------|
| 1.0 | 2025-06-06 | Initial spec from product decisions |
