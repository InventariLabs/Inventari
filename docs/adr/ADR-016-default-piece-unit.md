# ADR-016: A Product Without a Unit Is Counted in Pieces

## Status

Accepted — 2026-08-30; amended 2026-09-12. A product without a unit is
still counted in pieces, but three details below changed: a matched catalogue
card's unit now wins over pieces; the unit is settled **before** the
quantity-precision gate, so a fractional quantity without a unit is refused
as it is with `pcs` named (an import or scan row with one is refused too);
and the create form no longer preselects "pcs" (2026-09-09) — the service
decides.

## Context

`Item.uom_id` was optional, and in practice most products had no unit at
all. The quantity column on the product list was
therefore mostly unreadable: "10" could be grams, litres or pieces. An
earlier fix made the column honest — it renders "—" for a missing unit —
but an honest gap is still a gap, and the create form kept allowing it.

The product question: should a unit be **required**, or **defaulted**?
Prior art is uniform:

- **Odoo** — the product form carries a required Unit of Measure, defaulted
  to "Units".
- **ERPNext** — every Item master mandates a Default UoM, conventionally
  "Nos".
- **Zoho Inventory** — the form preselects a default unit (pcs/kg); the API
  keeps `unit` optional but the UI never leaves it blank.

Nobody blocks product creation on the question "of what?". Everyone answers
it with a countable default the user can change. Lightweight trackers that
only label items with a unit (Sortly offers standard units on all plans and
custom ones on paid plans, but no conversions) sit below what Inventari
already does with UoM conversions, recipes and valuations.

## Decision

**A product created without a unit is counted in pieces. `uom_id` stays
optional in the schema; the default is applied by the create service, never
by rejecting the request.**

- `create_item_async` fills a missing `uom_id` with the organization's own
  `pcs` row, falling back to the system one (`organization_id IS NULL`,
  `is_system`). Every creation path — form, API, import — goes through the
  service, so the default is not a form-only nicety.
- The default is applied **after** the quantity-precision gate: it labels
  the quantity, it does not change what is accepted. A caller who never
  picked a unit keeps recording fractional quantities; a caller who picked
  pieces is bound by whole numbers (rounding 1.0), as before.
- The archived migration `uompcs01` backfills `items.uom_id IS NULL` with the system
  piece unit. One direction only — a defaulted row and a deliberately-pieces
  row are indistinguishable afterwards, so the downgrade is a documented
  no-op.
- The create form preselects "pcs" (shipped earlier); editing never rewrites
  a unit the user did not touch.

## Rationale

A piece is the one unit every vertical shares — a warehouse counts pieces, a
kitchen counts pieces, an IT inventory counts pieces. That makes it the
core-neutral default: Odoo's "Units" and ERPNext's "Nos" are the same
concept. Core neutrality (§4) is preserved because the default is a unit,
not a domain assumption: it says "this row is countable", nothing more.

Defaulting instead of requiring keeps imports and scan flows working: an
OFF product or a CSV row without a unit lands as pieces instead of failing
validation for a question the source data could not answer.

## Consequences

**Good**

- The quantity column always says what it counts; "—" survives only where a
  record predates the backfill on another environment.
- Data quality improves without a single validation error: the form, the
  API and imports converge on the same answer.
- An organization can still keep its own `pcs` vocabulary — the org-owned
  row wins over the system one.

**Costs**

- Unitless historical quantities that *meant* something else (0.5 of a
  kilogram recorded with no unit) now read as pieces. The backfill cannot
  know better; the audit log and history keep the original numbers.
- Two conventions for "no unit chosen" remain in old dumps elsewhere
  (`NULL` vs `pcs`) until those environments migrate.

## Alternatives considered

**Require the unit (form + API validation).** Rejected: it breaks imports,
OFF and scan flows that cannot know the unit, and no competitor does it —
they all default.

**Keep the unit optional with no default.** Rejected: that is the status quo
the earlier honesty fix only papered over; the column stays unreadable for
most rows.

## Implementation

- `backend/app/services/items/_create.py` — `_default_piece_uom_id_async`
  and its call site in `_resolve_record_unit_async`, which `create_item_async`
  calls before the precision gate.
- `backend/migrations/versions_archive/uompcs01_backfill_default_piece_uom.py`
  (removed since: archived with the v0.11.0 baseline, which carries its result).
- `frontend/src/modules/inventory/hooks/useItemForm.ts` — the create form
  starts without a unit (its preselect was removed 2026-09-09).
- Tests: `TestItemsCreate` in `backend/tests/integration/test_items_api.py`
  (default, explicit unit kept, the matched card's unit inherited, fractional
  quantity without a unit refused);
  `frontend/src/modules/inventory/hooks/useItemForm.test.ts` ("starts a new
  item without claiming a unit", "does not put a unit on an item that was
  saved without one").

## References

- ADR-015 (unit weight on the product template) — the same "value travels
  with its unit" principle.
- backend/AGENTS.md §4 (core neutrality).
