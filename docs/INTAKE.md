# Intake workflow

Intake is the entry point before clearing. Staff add clients (new or existing) and create one or more `ProductAssignment` rows for the **active tax season**.

See also: `docs/CLEARING.md`, `docs/LIFECYCLE.md`, `ROADMAP.md` (Phase 2).

---

## Tax season scope

An **Intake** record represents all services rendered for a client in a given tax season (`Intake.client` + `Intake.tax_season`, unique together).

- The intake UI lists only intakes for the **active** `TaxSeason` (`is_active=True`, highest year wins).
- Search flags (`in_intake`, `in_daily_clearing`) are scoped to the active season.
- Historical intakes from prior seasons remain in the database but are hidden until that season is active again.

---

## Creation rules

| Action | Creates `Intake` | Creates `ProductAssignment` | Creates `DailyClearing` | Sets `lifecycle_state` |
|--------|------------------|---------------------------|-------------------------|------------------------|
| Add existing client to intake | Yes (active season) | Yes (default PA) | No | No |
| Create new client **from intake page** | Yes | Yes | No | No |
| Create new client **from client portfolio** | No | No | No | No |
| Add client to **daily clearing** | Reactivates if needed | Reactivates if needed | Yes | `IN_CLEARING` (Phase 3) |

**Default PA:** current calendar year minus one, default filing type, default product type (`TBD`). All product types are seeded on the client's `TaxYear` row when the first PA is created.

**Service:** `intake.services.enrollment.enroll_client_in_intake(client)` — shared by `add_client_to_intake` and `create_new_client`.

**Helpers:** `core.utils.get_active_tax_season`, `get_or_create_intake`, `get_or_create_product_assignment`.

---

## Endpoints (`intake/`)

| View | Method | Purpose |
|------|--------|---------|
| `intake` | GET | Active-season intake board |
| `search_clients` | GET | Find clients by name/TIN |
| `add_client_to_intake` | POST | Enroll existing client |
| `create_new_client` | POST | Create client + enroll (intake only) |
| `remove_client_from_intake` | POST | Deactivate intake + PAs (frozen PA guard) |
| `add_product_assignment` | POST | Additional PA subrow |
| `remove_product_assignment` | POST | Deactivate PA subrow |

---

## Access control (Phase 2)

- **Authentication:** all views require login.
- **Roles:** all staff roles may read and write intake (single-org office for now).
- **Organization:** not filtered at the data layer yet; users belong to an org but clients are shared office-wide.

---

## Eligibility for clearing

A PA is eligible to enter clearing when:

1. It belongs to an active `Intake` for the active tax season, and
2. Staff adds the client to daily clearing (creates/reactivates `DailyClearing` and runs `cmd_enter_clearing`).

Intake alone does **not** set `lifecycle_state`; that happens in clearing.

---

## Remove / freeze guardrails

Removing a client from intake or deactivating a PA is blocked once the PA has left `IN_CLEARING` (lifecycle) or started legacy completion (`enforce_pa_not_frozen_for_action` in `core.utils`).
