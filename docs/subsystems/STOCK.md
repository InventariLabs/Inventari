# Stock Subsystem (Quants, Movements, Reconciliation)

- **Models**: `Item` (the records), `StockAnchor`, `StockReservation`,
  `StockMove`, `StockLot` (`app/models/`), and the view
  `stock_quants_from_records`
- **Model**: [ADR-022 — one number of stock](../adr/ADR-022-one-number-of-stock.md)
  (supersedes ADR-004, whose quant table is gone, archived `quantdrop01`)
- **Rules**: `backend/AGENTS.md` §"Stock Posting Rules"
- **Reconciliation**: `app.services.analytics.reconciliation` + `app.services.reconciliation_job`

## The records are the stock

The records (`Item`, one per batch per owner) hold the stock, and
`stock_quants_from_records` sums them per
`(organization, product_template, location, lot, owner)` into `quantity`
(physical) and `reserved_quantity` (from the reservation rows); available
(`quantity − reserved_quantity`) is worked out by the readers. "Quant" is
the word for such a group, read from the view; the `stock_quants` table that
used to hold the same numbers beside the records is gone (migration
archived `quantdrop01`). Every change to `Item.quantity` is posted in the same
transaction: a single record's change through `apply_quantity_change_async`,
which writes the change's movement and its cost layer
(`_post_the_change_async`); a door that moves several records as one
movement — document execution, maker production, a draw across shelves —
writes the records with `post_the_change=False` and the movement through
`core_api.stock.post_movement_async` or `take_from_the_records_async`.
Stock-take finalize posts each counted record on its own, one write per
counted record, under the anchor lock of the group it settles. There is no
second number to keep in step, so there is no path map to maintain; the rule
is the one in `backend/AGENTS.md`.

No negative stock at the DB level (`CHECK quantity >= 0` on items) —
stricter than Odoo's default, and deliberate.

### Locking: every group up front, through its anchor

A group of stock is a product on a shelf, and each group has an anchor: a
row in `stock_anchors` with no quantity (`app/models/stock_anchor.py`). A
write locks the anchors of the groups it writes before it reads what is
free, through `core_api.stock.lock_async` (`_stock_quant_ops.lock_stock_async`).
The lock first creates the anchors of the shelves it was given that have
none yet — one statement, in key order — and then locks the anchors with
`FOR NO KEY UPDATE` in `id` order. So two first receipts to an empty shelf
queue on its anchor instead of racing to insert, and two operations that
write several groups — a document's lines, the two ends of a move, a
reservation that may draw on any shelf — wait for each other instead of each
holding what the other needs.
`FOR NO KEY UPDATE` still keeps two writers of a group apart and lets through
the `FOR KEY SHARE` a foreign key check takes on the row.

A document locks every shelf of each product it names: the FIFO cost layers
it drains are kept per product, so two documents of the same products from
different shelves would otherwise meet there. Every shelf of a product
(`(product, None)`) locks the anchors that exist and creates none. The
single-record writes (a record's own posting, `post_movement_async`) and the draws
(`take_from_the_records_async`, the reservations; see *What a draw takes*
below) take the same lock first, so the order holds whoever locks first. A
group an operation did not name up front and locks later is taken after the
others; two such operations can close a circle, which the database breaks by
aborting one of them — nothing is written wrong.

Anchors are not deleted: a group that once had stock keeps its row, and only
a cascade from the product, the shelf or the organization removes it.

A record with a product names its group's anchor by a foreign key
(`fk_items_stock_anchor`, `MATCH SIMPLE`, so a record without a product is not
checked). Every door that gives a record a product or a shelf — creating it,
binding it to a card, moving it, the single and the bulk edit — locks the new
group before it writes the column, and the lock creates the anchor. A door
that skipped the lock on a group with no anchor fails with an
`IntegrityError` instead of writing stock no lock covers. The key does not
catch a skipped lock on a group that already has an anchor; the concurrency
probe does. Test fixtures that add an `Item` straight to a session create the
anchor explicitly (`tests/integration/_shelf.py::anchor_pending_records`),
and the demo seeder does the same before its bulk insert.

### A posting asks once and writes its rows together

A document of two hundred lines walks them one by one, and what each line
needs is mostly the same: the organization, the units, the shelf and its type,
the product cards. `core_api.stock.posting_scope_async` is the scope such an
operation runs in — completing a document, undoing one — and it does three
things, none of which changes what is written:

- **Reference data is read once** (`app/core/read_scope.py`). Inside the scope
  a `SELECT` over organizations, units, locations and their types, product
  cards, categories and inventory periods is answered once per statement and
  parameters; later identical ones are served from the first answer. The
  answers are dropped when the session writes one of those tables (an edit
  not yet flushed counts: a read drops them before the session would flush it), when the
  transaction ends or any part of it rolls back, and when the scope ends. A
  `FOR UPDATE` read and a refresh always reach the database.
- **Appended rows are written as sets** (`app/core/posting_batch.py`). The
  movement, the cost layer, the record history row, the journal row and the
  outbox row of each line are handed to the scope's batch and written as one
  multi-row insert per table when the scope ends. Anything in the scope that
  reads or updates one of those tables first writes what is waiting, so no
  reader sees a ledger missing its own posting (the outgoing cost layers are
  the exception: they are added unread, written at the end, and nothing in a
  posting reads them); a savepoint rolled back takes
  back the rows that were added inside it, and gives back to the batch the
  rows it had to write early that were waiting before it began. The scope
  must end before the caller commits.
- **A signed-delta pass asks the shortage question once**
  (`core_api.stock.ask_what_each_grain_has_free_once_async`). A correction or an
  adjustment writes its movements line by line; each movement is checked that
  the grain it left still covers its reservation rows. Run inside this block
  the checks wait and are answered together, in one read, when the block ends
  normally, with the same `StockUnavailableError`, raised from the block's
  end. A grain a later line brought back above zero is not refused for having
  dipped on the way. Inside a posting scope the records and cost layers a line
  changes are written with the next statement that reads them, not after each
  line.
- **A lock is asked for once** (`app/core/txn_memo.py`). A transaction
  remembers the anchors it has locked and the records it has read under
  their row lock, until it ends or any part of it rolls back. A line that
  reaches the same group or record from three layers locks it once. A
  document that knows its lines up front takes them together:
  `core_api.items.lock_records_async` locks all the records in one statement
  (in id order), and `core_api.valuation.lock_open_layers_async` reads and
  locks the open cost layers of the products a removal will draw, which the
  deliveries then drain from memory — a layer written for the product after
  the read, or a rollback, drops that queue so the next delivery reads again.
  A correction, and so an undo, does both before its first line.

Outside the scope every writer behaves as before — one statement and one
flush per row — so a single record's write needs none of this. The shape is
pinned by `test_a_receipt_posts_its_lines_as_sets.py`: the appended tables get
one statement each however many lines the document has, and the statements
per further line stay under a bound.

### What a draw takes: planned from the records

The draws that choose what to take — the outbound document (a dispatch, a
scrap, the WMS picking that completes through them), a production run
(`take_from_the_records_async` with no shelf named), a reservation,
`release_unbacked_async` and the picking suggestion — plan it from the
records (`plan_draw_async` in `app/services/_stock_draw.py`). The
candidates are the product's records at the place, in a batch that may be
used and of the owner asked for. What a
(shelf, batch, owner) has free is its records less its reservation rows, and
each record gives, in order, what it holds, what is still free in its grain
and what is still wanted, whichever is least. The order is one function,
`records_in_removal_order`: FEFO by the batch's earliest date (a record with
no batch is read by its own expiry date) with undated stock last, FIFO by age, both ending on the record's `created_at` and `id`,
so two records written in one instant come out the same way every time. The
plan names each record and how much it gives.

The plan is read under the anchors. A draw on one shelf locks its anchor
first. A draw on every shelf of a product locks the anchors there are, and
any shelf its plan reaches outside them — one stocked for the first time
while the lock waited — is locked by name and the plan read again. What the
plan names is what is written: the records it named, and nothing beside them.

The outbound door writes what the plan named:
`take_from_the_records_async` plans the draw under those locks and writes
each named record down once — through the items service's own quantity
path, so the period guard and the history log are the record's rules, not a
copy — then writes the movements off the shelf, one per shelf, batch and owner
taken, naming the document. The door writes no movement of its own. The
records lead now; the guessing step
that used to take the drawn batches back off the records
(`_reduce_stock_cache`) is gone. A line that names its batch
draws that batch and no other, and a scrap of the batch the operator
confirmed may still take it after a recall (`require_active_lot=False` is
a named-batch-only lift).

Some doors write the record first and check its grain after: a record's own posting, a
transfer's movement once its record has moved (`post_movement_async`), a
relocation. By then the records already say the new number, so what is asked
is where the grain ended — what its records hold less what its reservation
rows hold must not be below zero (`free_in_grain_async`), or the change is
refused by name and the caller's transaction takes it back. The movement
names the record's own batch; nothing is drawn from another.

### Which card and shelf a hold looks at: the draw's

The hold and the draw answer by the same pair, so a document cannot promise
one thing and take another. The card is the line's, else the record's the
line names; the shelf is the document's source, else the shelf that record
stands on (`_reserve_quants_for_doc`, mirroring `dispatch_item` and
`scrap_item`). Both answer by `line_source_shelf`: the line's own pin, then
the document's source, then the record's shelf. A dispatch from a zone (a
location with shelves under it) pins each line at confirmation to the shelf
its share is drawn from, planned across the zone's subtree
(`plan_draw_async` with `among_shelves`), so the hold and the draw read the
same shelf per line; a transfer from a zone pins its record's own shelf. A write-off names no source, so holding by the product alone
blocked the oldest stock anywhere while the named record was the one that
left; a line naming a record but no card holds the record's card stock all
the same. When the source shelf cannot cover a line whose record stands
elsewhere, confirmation refuses with `document_record_stands_elsewhere` —
both shelves named — instead of a bare shortfall. Pinned by
`test_a_hold_follows_the_record_the_line_names.py`.

### Whose goods a door may take: the owner comes from the line

One rule for every door: **the document line says whose goods move, and
every door answers by it** — the reservation
holds what the line may draw, the draw takes what the line may hold, the
movement says whose goods left, and a document issues exactly what it
promised. A line that names no owner does not restrict: the reservation
holds any owner's goods standing there, and the draw at completion takes
the same scope — the two sides of one promise cannot disagree about it. A
line that names an owner (once lines carry the column) is answered by name
on both sides.

This is why the document door draws with `any_owner=True` while its line
names no owner (`app/modules/warehouse/_stock_executor_outbound.py`), why the reservation plans
with `any_owner=True` (`_stock_reservation.py` — the promise, pinned by
`test_a_reservation_names_its_own_grain.py`), and why `StockMove.owner_id`
exists and is written by `stock_moves.create_async`, the contract every
door's movement writes go through: the ledger says whose goods moved the
way the reservation row and the quant say whose goods stand. No door
creates a consignor's stock yet; when the first one arrives, the owner
arrives with it on the line, and the rule above is already the one both
sides of it answer by. Production (`consume_across_locations` in `app/modules/maker/stock_consumption.py`) and
the transfer paths draw or carry the owner the same way; a history
backfill was deliberately not written — the quants carry no history, and
every movement before the column is the organization's own goods.

### What stops a hold past its grain: a check at commit

The quant table's `CHECK (reserved_quantity <= quantity)` used to stop a bug
from committing a reservation of more than a batch holds, and it went with the
table. Over the records the same promise is a comparison of two sums — the
reservation rows of a `(product, shelf, batch, owner)` grain against its live
records — so it is
kept by a constraint trigger instead, `ck_stock_holds_within_stock`
(`baseline_002`, from the archived `holdguard01`), `DEFERRABLE INITIALLY DEFERRED`. It fires on a
reservation row inserted, or updated in its quantity or grain, and on a record that could have
taken stock out of its grain: less quantity, another batch, owner, shelf or
product, marked deleted, or purged. The record triggers' `WHEN` lets an
increase through without queueing anything. At commit each firing sums the
grain's rows and, if they hold anything, its records, counted as the
records' view counts them; more held than there is refuses the commit with
`check_violation`, which the API answers with a 409
(code `STOCK_STATE_IMPOSSIBLE`, message `stock_reserved_over_quantity`).

Being deferred is the point: a document that releases its hold and takes the
goods is judged on where the transaction ended, whichever order it wrote in.
It is a net under the anchor lock, not a replacement for it — each
transaction judges the grain on what it can see at its own commit, and the
anchor held to that commit is what makes the next writer see it. Grains
already over-reserved when the migration ran are not examined; the next
write that could make one worse is refused, and `db check-reservations`
reports them. The test databases install the baseline migration's statements
(`GUARD_SQL`, run by `backend/conftest.py`), so the whole suite writes under the guard; a test
that needs such a grain, to exercise the check that reports it, writes it
with `tests/integration/_holds.py::past_the_hold_guard`.

## One unit of measure per product, and it is the template's

A quantity is meaningless without the unit it is counted in, so the unit is
settled once and read everywhere from the same place: **the matched product
template's `uom_id` is the reference**.

- Quantities named in another unit are **converted into it** on the way in.
  The documents executor is the clearest case: the delivery speaks the
  supplier's unit and the shelf speaks the product's, so the line's quantity
  is converted to the template's unit before it lands, and a line unit that
  cannot be read as it is refused with `uom_conversion_unavailable`
  (`app/services/uom_service.py`). A recipe's BoM line in such a unit is refused
  with `bom_line_unit_not_convertible` (`app/modules/maker/recipe_service.py`).
- A record (`Item`) may be entered in a different unit as an
  **explicit, confirmed choice**: `POST /items` and the item update take
  `unit_confirmed_over_template: true` alongside the unit, and without it a
  unit that differs from the matched template's is refused by name
  (`item_unit_differs_from_template_confirmation_required`; the rule's home
  in the code is `app/services/items/_unit_choice.py`). The quantity and unit
  price are restated in the card's unit, and history records the confirmed
  choice and entered quantity. See [UOM.md](UOM.md).
- A unit is never swapped under stock at all: a record holding a quantity is
  refused the change (`item_unit_change_blocked_by_stock`), because the
  number on the shelf did not move and the unit under it must not either.

Two consequences worth knowing. The unit is settled *before* the quantity is
measured, so a precision refusal names the unit the row will land with rather
than the one the request happened to fill in. And the unit travels onto a
template the request itself mints, so a brand-new product's catalogue row is
never born unitless.

## StockMove is an append-only ledger

No UPDATE/DELETE paths; `CHECK quantity > 0`. Every row lands directly
at `state='done'` — there is no draft/confirm workflow above the ledger
and nothing transitions the column. The declared reference types are
exactly the ones production writes (`StockMoveReferenceType` in
`app/core/contracts/_stock_dtos.py`): `document`, `item`, `adjustment`,
`maker_production`, `recipe_picking`, `item_history` (the one-time backfill),
`opening_balance` (what a shelf held before the register knew it, posted
once by the archived `openbal01` migration, and since by every door that adopts a card
for a record that predates one) and `location_relocation`. The ledger's
sort order is `coalesce(completed_at, created_at) DESC, id` — the
**business date** of the movement, served by a dedicated index.

### Where a movement leads, and where its reason lives

`reference_type` names the *kind* of thing a movement came from and
`reference_id` names the thing. The register's SOURCE column shows the
kind and links to the thing, so "why did the yoghurt go down" ends at the
record that answers it rather than at a category:

| reference_type | leads to | needs the module |
|---|---|---|
| `document` | `/warehouse/documents/{id}` | `warehouse` |
| `item` | `/inventory/items/{id}` | — |
| `adjustment` | `/inventory/stock-takes/{id}/report` | — |
| `maker_production` | `/maker/production/{id}` | `maker` |
| `recipe_picking` | nowhere — no screen opens an individual picking session | — |
| `item_history` | nowhere — the backfill's own rows have no screen | — |
| `opening_balance` | nowhere — it says what stood on the shelf before the register knew it, and nobody's instruction moved that | — |
| `location_relocation` | nowhere — the ledger row names the relocation's paths | — |

The map lives in `frontend/src/modules/inventory/moveSourceLink.ts` and is
exhaustive over `StockMoveReferenceType`; a new kind fails
`moveSourceVocabulary.test.ts` until it is decided one way or the other.

**A correction's reason lives on the stock-take line, and nowhere else is
authoritative.** It exists in three places today — the `StockTakeItem`
row, a copy of its reason code in the organization journal's `meta_data`, and the ledger,
which carries none — and that is the intended shape: the journal's copy is
a snapshot for the audit trail, and the ledger points at the count instead
of restating it. So the path to a reason is: ledger row → stock-take
report → the line, which shows the reason code and the free text beside
the two numbers.

## Aging says what is still on the shelf

Aging entries are receipts (in-moves), aged from the movement's
**business date**, consumed by issues oldest-business-date-first — so
the buckets' sum ties back to the stock a reader can count. Ten
received and four dispatched do not age all ten.

## A count is taken against the record

`StockTakeItem.system_quantity` snapshots `Item.quantity` — the record's own
number. The count operates in record space from end to end: the
staleness guard re-reads `Item.quantity` and refuses the finalization when it
moved, and the posting writes `Item.quantity`, the number the variance is
stated against. A snapshot from a different source than the posting target
would ask a counter to explain a variance the correction does not close. A
quant is also a sum per `(template, location)` and several item rows can sit
behind one, so the view holds no per-row figure to snapshot.

What the posting writes is settled per row, not per shelf. Every row the
counter corrected writes its record through the record's own posting, which
posts that record's own delta — what the counter saw minus what the
record said — as its movement and its cost layer, in the same transaction
and under the anchor lock of the group. The records of the rows nobody
counted are not written. A shelf no row of which was counted is not touched
at all.

Consequence worth knowing: the delta is measured on the records, so a shelf
whose records and movement ledger had already drifted apart keeps that
drift — the count's movement carries the record's own delta, not the gap.
Closing that gap is not the count's job; the reconciliation's
shelf-versus-ledger pair is the measure of what it carried instead.

## Reconciliation: two pairs, measured on a cycle

| Pair | What a gap means |
|---|---|
| Shelf ↔ Movement ledger | May be non-zero on a database with a past: the first quant of a product used to be hydrated with its full quantity while the movement recorded only the delta (ADR-004, superseded by ADR-022). **Measured, not presumed** — the number to watch is one that grows. |
| Cost layers ↔ Shelf | A quantity gap between the layers and the shelf. Unpriced arrivals carry an `unknown` layer when there is no average rate to fall back on, and an `average` one when there is. |

"The shelf" is the records' view below. The report compared two more pairs
while there was a quant table — `Item.quantity` against it, and it against
the records' view — and they ended with it (archived `quantdrop01`): there is one
number of stock now. Their fields left the answer, the stored pass and the
screen with them.

`GET /api/v1/stats/reconciliation` answers with the two measured pairs, with
`items_scanned` (the live records on a product card the shelf is summed
from) and with `previous`, what the last scheduled pass measured;
**Inventory → Statistics → Reconciliation** is the screen, and the one the
scheduled warning links to. The endpoint only reads.
The drift figures are `Decimal` on the wire (decision 18) — they are stock
quantities, and this read-model already spent a fix getting its comparisons
off float.

The scheduled job (`stock_reconciliation`, every 6h, and once on a backend
start for an organization whose last pass is older than that) measures the
two pairs, logs the figures and **stores the pass** — its figures, when it
was measured and when the admins last heard of it — under the core setting
`reconciliation_drift_signature`. That one record has two readers: the
screen shows it as the previous measurement beside today's, with a trend,
and the next pass compares against it to decide whether to warn. The pass
is stored every time, a clean one included, so "previous" is always the
measurement before this one. The admins are warned when a drift appears or
its figures **change** — a growing drift is news the pass it happens. A
non-zero drift that stands unchanged is not repeated every pass, but it
comes back once a week, as "still standing", so a warning nobody acted on
does not go silent for good. A value of another shape under the key (only
a hand-made write puts one there) reads as never measured, and the next
pass writes over it.

The ledger side is not added up from the movements. `stock_ledger_totals`
holds the net of every done movement per `(organization, product, shelf)`
— arrivals minus departures — and triggers on `stock_moves`
(`ledgertotals01`) move it in the statement that writes, corrects or
removes a movement. The pass used to sum the organization's whole ledger
every six hours; the ledger is append-only, so that cost grew with the
history and never came down. Reading the totals costs one row per product
and shelf however long the history behind them (at 20 000 products: 67 292
rows read where the scan read 197 405 movements, and the same 67 292 after
300 000 more). The triggers are statement-level with transition tables, so
a posting written in one statement moves each total once, about 70 µs per
single-row write and 5% on a bulk insert; the insert path takes the totals' rows in key
order; the removal path does not sort them. A removed movement only subtracts from a row that is still there: a
cascade from the product, the shelf or the organization removes the totals
together with the movements. No code writes the table — a change to how a
movement counts belongs in the trigger function, which the test databases
run verbatim.

## The records' view of the quants

`stock_quants_from_records` (`baseline_002`, from the archived `quantview01`) is the stock as the
records tell it: the live records of each `(organization, product, shelf,
batch, owner)` summed into `quantity`, and the `stock_reservations` rows of the
same group into `reserved_quantity`, with the columns the quant table had. A
reservation row carries its own group — the anchor of its product on its
shelf, its batch and its owner (`baseline_002`, from the archived `resgrain01`); the quant it used
to name went with the table.
`removal_strategy` is the constant the table's column always held; `id` is
derived from the group's key.

These readers take stock from it: availability, the
`core_api.stock.list_quants_async` every module asks what stands on a shelf
and what of it is free (`app/services/_stock_quant_query.py`); the recipe
catalog's stock totals (`get_stock_totals` in
`app/modules/maker/stock_consumption.py`); the stock on a date
(`app/services/stock_as_of_service.py`), which counts back from today's
records; the reconciliation's two pairs; a batch's
numbers, on its own screen and in the batch list's on-hand column
(`app/services/_stock_lot_ops.py`), which therefore always agree; the shelf
occupancy that guards a location delete (`app/services/storage/_queries.py`);
the reservation guard inside deleting a record
(`app/services/items/_lifecycle.py`); the CLI's reservation check
(`app/cli/commands_db.py`); and the reservation check of a record carried
to another shelf (`app/services/items/_stock_relocation.py`). The table the
view was once compared with is gone (archived migration `quantdrop01`, step 4 of the
stock-model decision that makes the record's quantity the only stock
number): what the view says is the stock.

Two consequences for whoever changes the schema:

- The test databases are built by `create_all`, which builds tables only, so
  `backend/conftest.py` runs the `VIEW_SQL` of the baseline migration
  (`baseline_002`, which carries the view as the archived `resgrain01` left it) on every
  worker database. The suite
  reads the view that ships, not a copy; a migration that redefines the view
  points `conftest.py` at itself.
- A migration that drops, or changes the type of, a column the view reads
  (on `items`, `stock_reservations` or `stock_anchors`) has to drop the view
  first and create it again after; PostgreSQL refuses the change otherwise.
