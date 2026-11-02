# ADR-021: Handling Units Are Not Modelled

## Status

Accepted — 2026-09-13. The passages about the quant key and its constraint
are history since [ADR-022](ADR-022-one-number-of-stock.md) dropped the
`stock_quants` table; the decision not to model handling units holds.

## Context

`StockPackage` (table `stock_packages`) had existed since the warehouse modules
were written: a name, an optional parent for nesting, an optional shelf, and
`stock_quants.package_id` carrying it into the quant key. A screen listed the
packages, and the stock screen had a button that opened it.

Nothing ever wrote a row. No service created a package, no endpoint accepted
one, the receiving form had no field naming a handling unit, and the picking
session never asked for one. Every `package_id` outside the model was either a
read filter or a copy of a value that was already NULL — the documents executor
mirrored a consumed quant's package at the destination, and maker consumption
did the same. The only constructors lived in tests.

The screen went first: it could not show a row that an application path could
produce, so the page, its nav button, the `?package=` filter and five locales'
worth of copy were removed, and the read-only endpoint was left with a dated
note in the endpoint-consumers register — the decision being whether receiving
would grow a handling-unit path, or the endpoint would go with its model.

The measured answer to the first branch is "not now". Giving receiving a
handling unit means more than one text field. Quants were keyed
`(organization, product, location, lot, package, owner)`, and every decrement
that names an explicit lot pins `package_id IS NULL` — so palletized stock
would be invisible to dispatch, scrap, corrections and counted reductions
until each of those paths learned about packages, while the FIFO/FEFO strategy
path would happily consume across them. That is a change to the central stock
primitive every module shares, made for a concept no other surface in the
product asks for. The cheapest honest version — a name on the receipt line,
get-or-create, the screen returns — still carries that semantics work and
re-opens a screen that had just been removed for having no writer. It is a
feature to design, not a finding to close.

## Decision

**Handling units leave the product in full: endpoint, DTOs, CoreAPI methods,
service, model, table, the `stock_quants.package_id` column, the stock screen's
PACKAGE column and the last i18n key all go together.**

The quant key keeps its real grain — `(organization_id, product_template_id,
storage_location_id, lot_id, owner_id)` with `NULLS NOT DISTINCT` — and the
unique constraint is renamed to say so (`uq_quant_product_location_lot_owner`),
because a name that mentions a column the table no longer has is the same lie
this decision removes.

If a vertical needs pallets later, they arrive as a designed feature: the
model, a write path in receiving, a screen, and the "what happens to every
other path when goods stand on a unit" semantics decided before the first row
exists. The `pkgremove01` downgrade, which restores the table and the column,
and this record are a starting point, not a promise.

### Alternatives considered

| Option | Why rejected |
|---|---|
| Give receiving a handling-unit field and create packages on the fly | The cheapest honest version of "in". It still requires the quant-key semantics above to be decided and tested in every consuming path, and it re-opens a screen removed weeks earlier for having no writer. Worth doing as a feature, with its own scope, not as the follow-up to a defect report |
| Keep the model and table, delete only the endpoint | The table and the column would keep the name with nothing writing them — the same debt the next architecture review would find, one layer deeper, and with no screen left to make it visible |
| Keep the read-only endpoint | An endpoint that can only ever answer with an empty page is a promise with no product behind it, and the register entry keeping it alive carried its own expiry date |

## Consequences

Positive:

- One less dead dimension: no endpoint, table, column, screen or translation
  promises a concept nothing creates.
- The quant grain and its constraint name tell the truth without reading the
  migration history.
- The endpoint-consumers register loses its only expiry-driven entry, so
  nothing is deferred to a date nobody owns.

Negative:

- If a deployment wrote rows through raw SQL — no application path ever did —
  the drop loses them. The migration is irreversible in data and reversible in
  schema: its `downgrade` recreates table, column and constraint (the
  migration now sits in `versions_archive/`, which nothing runs).
- Handling units are now a feature to fund, not scaffolding to build on.

## Risks

- A vertical that needs pallets finds the model gone from the tree. Mitigated:
  the `pkgremove01` downgrade, this record, and the design questions written
  down here.
- The quant-key change is silent for databases where every `package_id` is
  NULL — the normal case — so the migration only rewrites the constraint.

## Implementation

- Removed: `backend/app/api/stock_packages.py`, `backend/app/services/_stock_package_ops.py`, `backend/app/models/stock_package.py` — the three files this decision deleted, listed here as a record of what was there, not as a map of what is.
- `backend/migrations/versions_archive/pkgremove01_drop_stock_packages.py`
  dropped the column and the table, recreated the renamed constraint and its
  `downgrade` restored all three (removed since: archived with the v0.11.0
  baseline, which builds the schema without them).
- Package plumbing removed from `backend/app/core/public_api/stock.py`,
  `backend/app/core/contracts/_stock_dtos.py`,
  `backend/app/models/stock_quant.py` (removed since),
  `backend/app/services/_stock_quant_ops.py`,
  `backend/app/services/stock_quants_service.py`.
- `frontend/src/modules/inventory/components/stock/` loses the PACKAGE column
  and the card row; five locales drop `stock.columns.package`.

## References

- ADR-004 (StockQuant source of truth), ADR-009 (core neutrality and the
  3-vertical test), `backend/AGENTS.md` §3–4
- `docs/subsystems/MIGRATION_OWNERSHIP.md`, `docs/ERD.md`
