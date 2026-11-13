# Valuation Subsystem (Stock Valuation Layers)

- **Service**: `app.services.valuation_service` (Core-owned; exposed to modules via `core_api.valuation`)
- **Model**: `StockValuationLayer` (`app/models/stock_valuation_layer.py`)

## The shape

Every priced arrival writes an **IN layer**: quantity, `unit_cost`
(`Numeric(12,4)` — a cost per gram keeps its decimals), `total_value`,
currency, and `cost_basis` (see below). Every outflow consumes IN layers
first-in-first-out and writes an **OUT layer** worth exactly what the
layers it consumed cost (`cost_basis = fifo`, or `unknown` where the layers
could not cover it) — never recomputed, so a
report about March says the same thing in December. Outflows carry a
`reason` (`USED` / `DISPOSED` / …) which is what lets the consumption and
waste reports tell a use from a disposal.

## Consumption order: business date, not write order

FIFO consumes in **business-date order**:
`coalesce(document_date, the date of created_at)`, then `created_at`, then `id`.
`document_date` is the receipt's business date (a document's scheduled
date), recorded on the layer at write time — a booking typed late cannot
push the goods it describes to the back of the queue. Layers with no
document behind them fall back to their write time.

**One exception, and it is the standard one.** When goods go back — a
negative correction of a receipt, a return to the supplier — the layer
that receipt wrote is drained first, at its own cost, and the queue
behind it only covers what that layer can no longer cover itself. Odoo
prices a return from the original move and ERPNext from the original
receipt's rate, for the same reason: those goods are identifiable, and
sending back the expensive pallet must not take the cheap one off the
books. The link is `document_lines.corrects_line_id`, set when the
correction or return is created.

**The same rule on the way back in.** When goods come back — a return
from a customer, a dispatch corrected downwards — the receipt layer is
priced at what the outflow it undoes cost (the OUT layer's
`total_value / quantity`, `cost_basis = fifo`), **not** at the price on
the return line. That price is what the customer paid; posting a return
at it put the margin on the shelf, once per return. An outflow the books
could not value (`unknown`) comes back unpriced, at the current rate. A
line that posted no outflow — a receipt corrected upwards — is not a
reversal and keeps its stated price. Both directions pass the reversed
line as `reverses_line_id`; the service decides which kind of layer it
finds behind it.

## What a drain locks, and why the shelf cannot narrow it

A drain reads each layer's remainder, subtracts what it takes and writes
the remainder back, so it holds the rows while it does. **The lock is one
product in one organization: no narrower row exists to name.** A layer
records what a product cost and has no `storage_location_id`, so one FIFO
queue serves every shelf the product sits on, and two outflows from two
different warehouses serialize on it although they touch different
shelves. That grain is a settled choice, not an oversight: narrowing it
means putting a location on the layer — a model change with a valuation
consequence, not a `WHERE`. See
[ADR-020](../adr/ADR-020-cost-layers-lock-per-product-not-per-shelf.md).

The stock side locks at the shelf wherever it can: what it locks is the
anchor of a product on a shelf (`stock_anchors`, see
[STOCK.md](STOCK.md)). A draw on one shelf takes the anchor of the location
it was given; `take_from_the_records_async` with no shelf named — the draw a
production run makes when it does not care which shelf an ingredient sits
on — takes every anchor of the template in the organization, because it
cannot know which locations it will touch until it has taken the locks. It
waits for them rather than use `SKIP LOCKED` (a skipped shelf would leave
the draw short in silence) or `NOWAIT` (contention would become an error on
the movement path).

The two grains do not line up — a cost layer belongs to a product, an
anchor to a shelf — and an outflow is the one move where that mismatch lets
two unrelated warehouses wait for each other.

## The rate: layer average, honestly named

Stock **value** is FIFO — layers leave first-in-first-out. The **rate**
(`get_current_rate_async`, `get_rates_batch_async`) is the average cost
of the layers still on hand: an indicative figure that steps when a
layer empties, **not** a true running average (AVCO). Source fields keep
the historical `avco` label; the arithmetic is what IAS 2 requires
disclosed, and it is disclosed here.

A rate exists only while the layers behind it agree on one currency, and
only while that currency is the organization's own — stock bought in one
foreign currency is refused like a mixed batch, never handed out as a
bare number every reader would take for the house's money.

And a rate averages only the layers that carry a cost. An `unknown` layer
holds 0.00 where nobody named a price; averaged in, it handed the next
priceless receipt a zero to borrow as the organization's own rate.

## Cost basis

### Estimates share one price policy

`core_api.valuation.estimate_unit_cost_async` batches indicative costs for
recipes and production planning. It prefers the organization's priced-layer
average, including a stated zero; without a rate it asks the registered
supplier-price provider, then reports unknown. The result carries `unit_cost`,
`currency` and `source` (`layers`, `supplier`, `unknown`). Existing HTTP source
fields keep `avco` for the layer estimate and `none` for unknown.

The `purchase_orders` module registers the provider at import. Its batch query
uses current offers in the organization's currency and converts them to the
product's stock unit before comparing prices. Incompatible units and foreign
currency are not bare rates. With the module absent or disabled, no supplier
fallback applies. Core imports no feature module to do this.

A record's `purchase_price` does not supply a second valuation mechanism:
prices belong to receipt layers. A manually entered recipe ingredient price
remains that module's final fallback, outside the shared product policy.
Two reports are estimates from it, and say so: the stock value per category on
the dashboard (`get_stats_by_category_async`, `app/services/analytics/dashboard.py`)
and the spend per category in the cost report (`_compute_category_costs_async`,
`app/services/analytics/cost.py`). Both multiply each record's purchase price by
its quantity, mark their rows `value_source: purchase_price` and count the
records that carry none (`unpriced_count`). A category belongs to the record, while a layer knows
only the product, so the layers have no figure per category to give; neither
report is read back into the cost history.
Completed production still costs its consumed FIFO layers; estimates never
write accounting cost history.

| `cost_basis` | Meaning |
|---|---|
| `stated` | Somebody named the price (invoice, priced document line). |
| `average` | Nobody named it; the organization's current rate was used. |
| `unknown` | Nobody named it and there was no rate. The quantity is real; the value is not known and must not be read as zero. An outflow the layers could not fully cover, one whose layers disagree on a currency, or one that drained `unknown` layers, is marked this way too. |
| `fifo` | An outflow, valued at what the layers it actually consumed cost. Outflows written before this column existed were posted at the average of the layers on hand, and are marked `stated` with the rest of the older history (the migration that added the column did not tell them apart). |

An unpriced inflow is **posted, not skipped** — a receipt is a receipt
whether or not somebody typed a price. Posting it at zero diluted the
average; posting nothing broke the equality between the shelf and the
sum of the layers.

**Whether a layer carries a cost is one question with one answer:**
`StockValuationLayer.carries_a_cost`, a hybrid that reads the same in a
`WHERE` and on a loaded row. Every rate, the list footer, the drain and
the reports asking whether an outflow was priced ask it there. Readers
used to decide it one by one, and the one that did not ask — the rate a
priceless receipt borrows — turned stock nobody priced into stock that
cost 0.00.

## Value per product, quantity per lot

Quantities go down to the lot: a count, a pick and a dispatch all know
which batch they touched. **Value does not.** `StockValuationLayer` has
no `lot_id`, so a correction on batch B can take cost off the layer batch
A arrived on.

This is deliberate, and it is the default in the systems our users arrive
from — Odoo and ERPNext both track quantity per lot and value per
product; batch-specific valuation is an SAP-class option. IAS 2 requires
specific identification only for inventories that are **not** ordinarily
interchangeable, and batches of one product usually are. Splitting the
layers per lot would multiply them, and every rate query, every report
and every reconciliation with them, for an answer almost nobody needs.

**The condition for revisiting it**: a real user for whom the gap is
felt — stock rotated FEFO by quantity while its value leaves FIFO, on
batches whose costs genuinely differ enough to matter. Until then the
rule stands, and this paragraph is the answer to "why does the batch
column not reach the cost history".

## Accounting requirements arrive with the module that owns them

A rule the Core enforces globally is a rule every installation pays for,
including the ones that never asked for accounting. So an accounting
requirement lives with the module that owns it and switches on with it.

The worked example is the **inventory period lock**. The model, the table
and the close/reopen workflow belong to the `warehouse` module; Core's
stock-mutating paths still have to honour it, but Core must never import a
feature module. The module therefore *registers* its guard at startup
(`app/core/period_guard.py`) and Core calls it through that registry. With
the module absent, the check is a no-op — there is no period to be closed,
so nothing is being skipped. Once the module has loaded, its guard applies to
every organization, whether or not that organization still has the module
enabled: a period already closed stays closed.

The same shape applies to anything else an accountant would recognise:
the requirement is a module's, the hook is the Core's, and the default
without the module is "this does not apply here" rather than "this passed".

**The consequence worth stating.** A module can move stock without ever
naming a price — nothing forces one. Those arrivals post `unknown` layers
(see above), and a report covering them has to say it does not know rather
than print a total that is short by an amount nobody can name. That is what
`window_is_valued_async` (`app/services/analytics/_outflow_value.py`) is for
and why the consumption and waste values are nullable in the API. A zero
where the honest answer is "no idea" is the failure this whole subsystem is
shaped to avoid.

## Reconciliation and coverage

The scheduled reconciliation (`app.services.reconciliation_job`, every
6h) measures two pairs, among them **cost layers vs the shelf** — a gap
means the quantities in the layers and on the shelf differ. An unpriced
arrival still has an `unknown` layer, so this comparison does not measure
how much stock has a known price. See [STOCK.md](STOCK.md).
