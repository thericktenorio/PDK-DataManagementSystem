# Path A testing plan

Validation checklist for **clearing parser (Track 1 / schema v1)** before starting **analytics development** (Track 2 / `ANALYTICS_ROADMAP.md` A1).

**Global PDF upload feature:** `docs/PATH_A_PDF_UPLOAD.md`.

**Parser backlog:** `docs/PARSER_ROADMAP.md`. **Field spec:** `docs/PARSER_EXTRACTION.md`.

---

## What “Path A complete” means

Path A is **done for analytics gate** when:

1. Track 1 clearing automation is verified on real Drake PDFs.
2. Global upload flow (`PATH_A_PDF_UPLOAD.md`) is implemented and smoke-tested.
3. Per-row upload buttons still work (regression).

**Not required for this gate:**

- Track 2 KPI / Comparison extraction (`RETURN_ANALYTICS.md`) — tested in **analytics A1**, not here.
- Power BI or shareholder agent.

```text
Path A testing (this doc)  →  analytics A1 (Track 2 parser)  →  analytics A2 (warehouse ETL)
```

---

## Test environments

| Environment | Use |
|-------------|-----|
| Local Compose | Dev + pytest |
| Beta droplet (`pdk.godelta.us`) | Real preparer UX, timing |
| Corpus samples | `pdf_manager/fixtures/drake_samples/` |

Ensure `FEATURE_PARSER_PATH_A=true` and `PDF_MANAGER_BASE_URL` points at `pdf_web`.

---

## 1. Real PDF — clearing automation

### Per-row upload (existing)

**Steps**

1. Open clearing with a client already on the board (`IN_CLEARING`).
2. Use row **Upload Drake PDF** (toolbar or overflow menu).
3. Upload a real Drake return PDF.

**Expect**

| Check | Pass criteria |
|-------|----------------|
| HTTP response | `status: success` |
| `parse_job_uuid` | Set on PA |
| `parse_result_json` | Schema v1 fields present |
| `parser_status` | `DONE` |
| Fee | Set when `tax_prep_fee` extracted |
| TPG | `payment_method` → TPG when `has_tpg_pages` |
| Output refs | Main / signature / voucher paths when applicable |
| Locked row | Upload disabled when not `IN_CLEARING` |

### Global upload (new — `PATH_A_PDF_UPLOAD.md`)

**Steps**

1. Click **Upload Tax PDF** (header, next to Add New Client).
2. Upload same corpus PDFs through each branch (see §4 in `PATH_A_PDF_UPLOAD.md`).

**Expect**

- Correct branch: new client / new clearing row / conflict modal.
- Intake + `DailyClearing` created via existing enrollment helpers.
- Final state matches per-row parse outcome on target PA.

---

## 2. Dynamic client messages

**Samples:** personal TPG, personal non-TPG (Diagnostic fee), S-corp.

| Check | Pass criteria |
|-------|----------------|
| `message_ready` | `true` when first name + tax year extracted |
| Message modal | `closing_message_text` auto-filled when ready |
| No false fill | Message **not** overwritten when `message_ready` is false |
| Refund variants | Federal refund / balance due / state lines / direct deposit vs mail (see `message_builder.py`) |
| Edit before complete | Staff can edit message; required for complete clearing |

**Manual spot-check:** Open message modal and confirm readable, client-specific text.

---

## 3. Document sorting (packets)

| Output | Pass criteria |
|--------|----------------|
| Main packet | Download opens; client-facing pages present |
| Signature packet | Present when 8879 / TPG / engagement pages exist |
| Payment voucher | Present when federal/state vouchers in PDF |
| Diagnostic Summary | Excluded from main client packet (`extract_diagnostic_invoice` → exclude) |
| TPG_INFO | In signature packet, not main |

**Regression:** Compare page count/order to manual expectation on one familiar return.

---

## 4. KPI extraction — out of scope for Path A

| Track | Scope | Test doc |
|-------|--------|----------|
| **Track 1** | Message, fee, packets, v1 fields | This file |
| **Track 2** | Comparison, return profile, executive KPIs | `RETURN_ANALYTICS.md` + `ANALYTICS_ROADMAP.md` A1 |

Do **not** block analytics kickoff on Comparison parsing. Block on **Path A sections 1–3 + global upload** in this doc.

---

## 5. Schema v1 field matrix (corpus)

Run on each sample type when possible:

| Sample type | `message_ready` | Fee source | OCR pages ≤2 | p95 time |
|-------------|-----------------|------------|--------------|----------|
| Personal TPG | ✓ | TPG_INFO | ✓ | &lt;5s |
| Personal non-TPG | ✓ | Diagnostic | ✓ | &lt;5s |
| S-corp | ✓ | BILL_01 p2 | ✓ | &lt;5s |
| Multi-state personal | ✓ | (varies) | ✓ | &lt;5s |

**New field (global upload):** `taxpayer_tin` — normalized 9 digits; matches CRM `Client.TIN`.

---

## Automated tests

```bash
# Parser unit + fee + TIN
docker compose exec pdf_web pytest pdf_manager/tests/test_tin_extraction.py pdf_manager/tests/test_fee_extraction.py pdf_manager/tests/test_extraction_schema.py pdf_manager/tests/test_parsejob_status.py -q

# Corpus (local samples)
docker compose exec pdf_web pytest pdf_manager/tests/test_parser_corpus.py pdf_manager/tests/test_parser_benchmark.py -q

# CRM Path A (mocked)
docker compose exec crm_web python manage.py test clearing.tests.test_clearing_phase4 -v 2

# After global upload implemented
docker compose exec crm_web python manage.py test clearing.tests.test_path_a_global_upload -v 2
```

Add `test_path_a_global_upload.py` when feature lands (see `PATH_A_PDF_UPLOAD.md` § Tests).

---

## Local Compose UI smoke (global upload)

Manual steps when no browser test harness is available. Requires `FEATURE_PARSER_PATH_A=true` and rebuilt `crm_web`.

**Setup**

```bash
docker compose build crm_web && docker compose up -d crm_web
```

Open clearing as a logged-in preparer. Confirm **Upload Tax PDF** appears next to **Add New Client**.

| Branch | Steps | Pass criteria |
|--------|--------|---------------|
| No TIN | Upload a PDF fixture missing `taxpayer_tin` (or corrupt sample) | Alert: cannot extract TIN; no client/PA created |
| New client | Upload corpus PDF with unknown TIN | Enrollment modal → filing type + product → row appears after reload; parser downloads available |
| Enroll | Upload PDF for existing CRM client not on clearing board | Enrollment modal → client added to board with new PA |
| Conflict — Cancel | Upload PDF for client already on clearing; click **Cancel** | Toast “Upload cancelled”; no new PA; job not applied |
| Conflict — New Entry | Same; **New Entry** → enrollment | Additional subrow PA; parse applied |
| Conflict — Replace | Same; select unlocked PA → **Replace Entry** | Old PA voided/hidden; replacement PA has parser data |
| Replace blocked | Select PA in `CLEARING_COMPLETE` (or later) | Inline warning; **Replace** disabled or 409 message without full TIN |
| Regression | Per-row **Upload Drake PDF** on an existing row | Unchanged behavior |

**Parser corpus samples:** `pdf_manager/fixtures/drake_samples/`

---

## Beta smoke checklist (sign-off)

Copy to issue/PR when validating on droplet:

- [ ] Per-row parse — personal TPG
- [ ] Per-row parse — personal non-TPG
- [ ] Per-row parse — S-corp
- [ ] Global upload — unknown TIN → new client + board row
- [ ] Global upload — known client, not on clearing → auto-add
- [ ] Global upload — known client on clearing → modal (Cancel / New / Replace)
- [ ] Replace blocked when PA `CLEARING_COMPLETE` (or later)
- [ ] Cancel marks parser job cancelled; no CRM PA created/updated
- [ ] Messages correct for refund and balance-due cases
- [ ] Three packet types download correctly
- [ ] Parse failure → staff can continue Path B
- [ ] Upload timing acceptable on droplet

**Sign-off:** Path A ready for production default / analytics A1 when all checked or exceptions documented.

---

## Thread prompt (implementation)

> Implement and test Path A per `docs/PATH_A_TESTING.md` and `docs/PATH_A_PDF_UPLOAD.md`. Track 2 KPI extraction is out of scope.

---

## Revision history

| Version | Date | Notes |
|---------|------|-------|
| 1.0 | 2025-06-06 | Initial testing plan; KPI gated to Track 2 |
