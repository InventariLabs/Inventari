# ADR-004: StockQuant Source-of-Truth + `Item.quantity` Denormalized Cache

## Status

Superseded by [ADR-022](ADR-022-one-number-of-stock.md) — 2026-09-30: the
record is the only number of stock, a quant is a sum of records, and the
table, the bridge and its flag are gone. What follows is the decision as it
stood; the files and functions it names are history.

Accepted — 2026-07-12. Amended 2026-09-24: the register is
kept for every organization; the conditional gate is gone.

## Context

Inventari serves both **home/individual users** (a single fridge, no lots, no
reservations) and **WMS-grade businesses** (multi-location, lot-tracked,
reserved-for-documents, FIFO/FEFO). These two audiences have opposite needs:

1. **Home users** want simplicity: one `Item` row, one quantity. Introducing a
   per-lot/per-location `StockQuant` table for someone tracking 40 groceries
   would be pure overhead and complexity.
2. **WMS users** need the truth to be **per `(product_template, location, lot,
   package)`**: the same product can exist in two locations, in three lots,
   with a portion reserved for an outbound document. A single scalar
   `Item.quantity` cannot represent this.

The naive "pick one model" approaches both fail:
- **StockQuant-only:** fast inventory page (`SELECT quantity FROM items`)
  becomes a `GROUP BY ... JOIN stock_quants` — slow, and meaningless for home
  orgs that have no quants.
- **Item.quantity-only:** cannot express reservations, lots, or multi-location
  stock. WMS becomes impossible.

## Decision

**`StockQuant` is the authoritative source of truth for stock levels; `Item.quantity` is a denormalized, indexed cache that must stay in sync. A bridge (`_sync_stock_quant`) keeps them aligned in every organization.**

The first version of this decision made the bridge conditional: an
organization with no module that reads the register kept no quants and no
movements, for "zero overhead for home users". That promise was withdrawn
in the 2026-09-24 amendment. The saving was a few rows per change, and the price
was a second model: the move carried stock through a register such an
organization did not have and was refused, and the reconciliation, which runs
for every organization, read its whole stock as drift. What the household
sees did not change: the navigation entry and the ledger tab are still offered
where a module that reads them is enabled, and the value of its stock is still
read off its records.

### The truth model

`StockQuant` (`backend/app/models/stock_quant.py` (removed since)) holds the authoritative
quantity per `(organization_id, product_template_id, storage_location_id,
lot_id, owner_id)`, with `quantity`, `reserved_quantity`, and a
derived `available = quantity - reserved`. Removal strategy (`FIFO`/`FEFO`) is
per-quant (resolvable per-template, see `stock_strategy.py`).

`Item.quantity` (`backend/app/models/item.py:79`) is an **indexed** column read
directly by hot paths — inventory valuation, low-stock alerts, listing filters
(`Item.quantity > 0`), cost analytics. Aggregating these from StockQuant on
every read would be too slow.

The decision holds for every organization, whatever modules it has enabled.
The stock a shelf held before the register knew it — an organization that
kept none so far, a shelf whose records predate it — was posted once by the
archived `openbal01` migration: a batch-less quant, a movement marked
`opening_balance` and the cost layer, valued like any unpriced receipt.
`StockMove` is the journal
next to the state — every change to a quant has a movement explaining it —
and a path that writes quants itself writes both through one call,
`core_api.stock.post_movement_async`.

### The bridge: `_sync_stock_quant`

`backend/app/services/items/_stock_quant.py:129` —
`_sync_stock_quant(db, item, old_quantity, new_quantity, *, sync_valuation=True,
unit_cost=None)`. Behavior:

1. **Early-exit** if `item.storage_location_id` is `None` — a record that names
   no shelf has nowhere to put stock.
2. **No module gate.** The bridge used to be a no-op for an organization
   without a StockQuant-consuming module; since 2026-09-24 it writes for
   every organization.
3. **Cardless record:** a record that predates its card (`template_id` NULL)
   adopts one here — resolved, or minted, from the record's own words and bound
   through the unit gate every other door takes — and the stock it already held
   is posted as an opening: a quant on its own shelf, a movement marked
   `opening_balance` and an unpriced layer — the three writes the archived `openbal01` made
   for every shelf the register did not know, so all three reconciliation pairs
   agree from the adoption on. An edit that writes a card field (the low-stock
   threshold, the unit weight) to such a record through `PUT /items/{id}` adopts
   the card through the same call, `adopt_card_with_opening_async`. The
   opening's three writes are one function, `post_opening_balance_async`; the
   documents executor reaches it through `core_api.items` instead of keeping
   a copy, so a change to what an opening writes reaches every door at once.
   The alternative was the failure this step exists to end: the number on the
   record moved, the shelf it stood on kept the old one, the movement register
   stayed empty, and the location's card read "Nothing has moved through here"
   beside the changed quantity.
   Both directions address the record's own quant: the batch and owner the
   record names (`Item.lot_id`, `Item.owner_id`), a batch-less own quant for
   a record that names neither.
4. **Positive delta:** increments that quant, records a valuation
   receipt + StockMove for the delta. Where the shelf has no batch-less quant
   yet, the quant is hydrated with what the shelf's records hold beyond its
   quants (summed as the reconciliation's first pair sums them), not with the
   one changed record's quantity — which left a second record of the product
   outside the register and counted a shelf held in batch quants twice.
5. **Negative delta:** decrements that quant — consuming (`USED`) a held or
   recalled batch is refused, disposing of it or correcting the record is
   not. When the record's own quant cannot cover the change, it falls back to
   `decrement_quant_by_strategy_async` (cross-lot FIFO/FEFO), the shape a
   record written without its batch leaves; on "No stock found" for a record
   that names no batch and no owner it hydrates the same shortfall and retries
   (heals legacy/migration data).

The convenience wrapper `apply_quantity_change_async` (line 230) atomically sets
`item.quantity` and calls the bridge when `sync_stock_quant=True` (default).

### Threading `sync_stock_quant` through CoreAPI — the full path map

Most CoreAPI write paths accept an explicit `sync_stock_quant` flag so callers
that handle StockQuant themselves (document executor, maker production) can
opt out and avoid double-counting. A caller that knows which batch a change
belongs to does not need to opt out: `update_quantity_async(..., lot_id=...)` makes
the bridge address that one quant in both directions. Every code path that modifies
`Item.quantity` MUST call `_sync_stock_quant(db, item, old_quantity,
new_quantity)` when the item has both `template_id` and `storage_location_id`:

| Path | Sync location | Notes |
|------|-------------|-------|
| `POST /items` (create) | `_create.create_item_async()` | Built-in (default `sync_stock_quant=True`) |
| `PATCH /items/{id}` (quantity update) | `_update.update_quantity()` | NOT automatic — caller must handle. A record that predates its card is adopted here too (opening posted, then the delta), so a quantity typed by hand leaves a quant and a movement like one changed on a carded record |
| `PATCH /items/{id}/consume` | `move_service._reduce_quantity()` | Built-in |
| A record changing shelves — `PATCH /items/{id}/move`, `PUT /items/{id}`, `PATCH /items/bulk`, `core_api.items.update_async`, a re-imported sheet | `_stock_relocation.carry_record_stock_async()` | Every door that writes `Item.storage_location_id` calls it after writing: the stock goes to the new shelf as the record held it (the record's own batch and owner carried, by strategy when that quant cannot cover it; a reserved source refused, one movement per lot), and a quantity changed in the same request is posted there afterwards |
| `PATCH /items/{id}/discard` | `move_service._reduce_quantity()` | Built-in |
| Barcode/Label Scan | `scan_service.assign_label_or_barcode()` | Built-in |
| Recipe Picking | `scan_item_in_picking()` (`_picking_scan.py`) | Built-in |
| Document Stock Execution | `modules/warehouse/document_stock_executor.py` | **Handled separately** — executor resolves lots from document lines and writes StockQuant directly (`core_api.items.transfer_async(...)` with `sync_stock_quant=False`); the generic bridge cannot express lot-aware changes. Records keep the batch the quants hold: a receipt opens or tops up the record of the line's batch (a second batch on one shelf is a second record), a dispatch or scrap takes the quants first and the records of the batches they gave up after them, a transfer carries the record's own batch and owner (the remainder of a partial line keeps them), and a correction or adjustment naming no batch changes the record's own. **Every door that adopts a card a record that predates one never had posts the stock such a record already holds as an opening balance at its own location** — a quant, a movement marked `opening_balance` and an unpriced layer, the same answer a quantity raised by hand gets, written by the Core's one rule (`core_api.items.post_opening_balance_async`) — the executor picks the shelf and the holding, the Core writes; at the receipt the opening is what stood before the delivery, which lands on top as an ordinary priced-or-unpriced receipt — so the pair `(card, location)` reads one number from the first movement on. At the time of writing those doors are the receipt — on both of its paths, the line that names a product and the one typed by hand — the three outbound ones (dispatch, scrap, transfer) and the two correcting ones (correction, adjustment), in `_stock_executor_receipt.py`, `_stock_executor_outbound.py`, `_stock_executor_transfer.py` and `_stock_executor_deltas.py`. How many call sites that is, `git grep -c 'await _post_opening_balance_async('` over `modules/warehouse/` answers, and that answer is the one to trust: no count is written here, because a door added tomorrow would falsify it without anyone touching this file. The rule is what this row is for, and the code is the list: a door that adopts a card posts the opening, and no sentence here is maintained against the count |
| Stock Take Finalize | `stock_take_service.finalize_stock_take()` | Uses the bridge — each counted record is written with `sync_stock_quant=True`, `reference_type='adjustment'` and the count as the reference, so the record, its quant, the movement and the cost layer move as one write under `core_api.stock.lock_async` on the groups the count settles, taken before the first write. The difference is measured on the records — no row of the quant table is read to find it — so a mismatch the table was already carrying travels with the count instead of being cured or hidden. A record that names no batch takes the one its row named. A counted row whose item left the counted shelf since the snapshot goes through the same bridge, which lands it where the item stands now |
| Maker Production | `modules/maker/production_service.py` (`_sync_item_quantities_for_consumption`) | **Handled separately** — `consume_across_locations` decrements StockQuant across locations/lots directly; the matching `Item` rows are decremented via `core_api.items.update_quantity_async(..., sync_stock_quant=False)` per part of the draw — the records of the batch and owner that part came off first, then those that name neither, then any other — so the records mirror the ledger batch by batch (no double decrement). Output side: `core_api.items.create_async(..., sync_stock_quant=False)` + `stock.post_movement_async` keep the produced item, its quant and its movement aligned; the output takes no batch, on the quant or on the record |
| Recipe picking — consume | `modules/recipes/_picking_consume.py` | Uses the bridge (`core_api.items.update_quantity_async(..., sync_stock_quant=True)`); valuation is handled separately (`sync_valuation=False`) because the picking session prices the whole cook once |
| Recipe picking — undo | `modules/recipes/_picking_undo.py` | The same bridge in reverse, so putting a picked ingredient back moves the quant too |
| Equipment bulk create | `modules/equipment/_bulk_service.py` | Built-in (`core_api.items.create_async` with the default), so a bulk-created asset gets a quant |
| Equipment spreadsheet import | `modules/equipment/import_service.py` | Built-in (`core_api.items.create_async` with the default), so an imported asset gets a quant exactly like the same asset created in bulk or through `POST /items`. This was decided deliberately: the earlier explicit `sync_stock_quant=False` was an undocumented drift, and an asset whose quant is missing reads as a permanent reconciliation mismatch |

### Reconciliation — the safety net

`GET /api/v1/stats/reconciliation` (`backend/app/modules/stats/router.py:181`,
service `app/services/analytics/reconciliation.py:31`) compares `SUM(Item.quantity)` against
`SUM(StockQuant.quantity)` per `(template, location)`, paginated. Drift
threshold `0.001` absorbs decimal→float noise. This endpoint is how we detect
out-of-sync data after migrations, bug fixes, or a misbehaving code path that
forgot to call the bridge. **Any new code that mutates `Item.quantity` MUST be
added to the sync-rules table above** or it will produce drift.

The scheduled job (`services/reconciliation_job.py`) runs the same comparison
for every organization: it warns the admins when the figures change, and
again once a week while a non-zero drift stands unchanged.

The report also compares the quant table with `stock_quants_from_records`, a
view summing the records per product, shelf, batch and owner. Availability
(`core_api.stock.list_quants_async`), the recipe catalog's stock totals, the
stock on a date and the reconciliation's shelf pairs read stock from that
view; every write still goes where this ADR says, and the comparison is the
measurement the change of model is carried out on (`docs/subsystems/STOCK.md`,
*The records' view of the quants*).

## Consequences

### Positive

- **Both audiences served.** Home users read one number per record and see
  no WMS screens; WMS users get full per-lot/per-location truth. Both keep the
  same register underneath (amended 2026-09-24 — the home side used to keep
  none).
- **Hot reads stay fast.** Listing/valuation read the indexed cache; no joins.
- **Auditable.** Reconciliation endpoint makes drift detectable and debuggable.

### Negative

- **Dual-write complexity.** Every `Item.quantity` mutation must thread
  `sync_stock_quant` correctly. Forget once → drift. Mitigated by the
  reconciliation endpoint and the sync-rules table above.
- **Auto-hydration can mask bugs.** The "No stock found → hydrate from
  old_quantity" retry heals legacy data but can also hide a genuinely missing
  quant. Mitigated by the gate that only hydrates for the specific "No stock
  found" message.

## Alternatives considered

| Approach | Home DX | WMS capability | Verdict |
|----------|---------|----------------|---------|
| **StockQuant-only** (drop cache) | Poor (JOIN on every read) | Full | Rejected — kills home-vertical performance. |
| **Item.quantity-only** (drop quants) | Simple | None (no lots/reservations) | Rejected — kills WMS vertical. |
| **Cache + bridge (chosen)** | Simple (cache read) | Full (quant truth) | **Chosen.** Best of both, with reconciliation as the drift detector. |
| **Materialized view** refreshing quants → items | Read-fast | Full | Rejected — refresh lag creates a consistency window; Postgres MV refresh is heavyweight. |

## Implementation

- Truth: `backend/app/models/stock_quant.py` (removed since).
- Cache column: `backend/app/models/item.py:79` (`quantity`, indexed).
- Bridge: `backend/app/services/items/_stock_quant.py` (`_sync_stock_quant`,
  `apply_quantity_change_async`).
- Strategy resolution: `backend/app/services/stock_strategy.py`
  (`resolve_removal_strategy`).
- Reconciliation: `backend/app/services/analytics/reconciliation.py`,
  `GET /api/v1/stats/reconciliation`.

## References

- `backend/AGENTS.md` §"Data Model (Core)" — today describes the one-number model of
  ADR-022; the sync-rules table lived only in this ADR.
- [ADR-003](ADR-003-coreapi-facade-and-ast-sandbox.md) — the facade whose
  `sync_stock_quant` flag threaded this invariant until ADR-022 removed it.
- `docs/subsystems/STOCK.md` — the stock subsystem as it is since ADR-022.
