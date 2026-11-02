# ADR-020: Cost Layers Lock per Product, Not per Shelf

## Status

Accepted — 2026-09-13. Superseded in part by
[ADR-022](ADR-022-one-number-of-stock.md): the `stock_quants` table, its key
and the quant-side locking described below are gone with it. The decision
this record makes for cost layers — one lock per product — still holds.

## Context

An outflow drains receipt layers: it reads each layer's `remaining_qty`,
subtracts what it takes, writes the remainder back, and posts what the goods
cost. That read-modify-write needs a lock. Without one, two outflows of the
same product each read the same remainder, each finds it sufficient, and the
surviving write drops the other's draw — the layer keeps claiming stock that
has already left, and the books lose less than the shelves did. The damage
read like data rather than like damage: the table had no opinion on a
negative remainder, so the lost update survived as a number.

The obvious lock is the shelf. `StockQuant` is per
`(product, location, lot, package)`, and its write paths lock one location's
rows, so a movement out of Shelf A does not wait on a movement out of Shelf
B. `StockValuationLayer` cannot borrow that. Its columns include
`organization_id`, `product_template_id`, `document_line_id`, `item_id`, the
quantities and values, `currency`, `direction` and `reason` — there is no
`storage_location_id`. A layer says what a product cost, not where the goods
sat, and that is exactly what lets one FIFO queue serve every shelf the
product is on: two deliveries of the same product into two warehouses feed
it together, and whichever goods leave first take the oldest layer off the
books, whichever shelf they stood on.

The quant side asks the same question and answers it per location where it
can: `decrement_quant_async` and `decrement_quant_by_strategy_async` lock
the rows of the location they were given. `consume_across_locations_async`,
the draw a production run makes when it does not care which shelf an
ingredient sits on, locks every quant of the template in the organization,
because the draw does not know which locations it will touch until it has
taken the locks.

## Decision

**The drain locks one product in one organization — every open IN layer of
it — and the grain is stated in the code and the docs rather than left to be
inferred.**

The lock is the narrowest thing the table can honestly name. It is not
narrower, because a filter is only as precise as the columns behind it, and
a lock taken on rows reached through a join still leaves the layer rows
themselves open to the next drain. The price is paid in concurrency, not in
correctness: two outflows of one product from two warehouses serialize on
the same rows although they touch different shelves, and each drain holds
the whole open queue, not just the layers it will consume.

### Alternatives considered

| Option | Why rejected |
|---|---|
| Add `storage_location_id` to the layer, then lock per location | A valuation decision wearing a locking decision's clothes: per-location layers split one product's cost history by warehouse, and every rate, report and reconciliation then has to say which warehouse it quotes. Worth deciding on its own merits, never as a lock optimization |
| Lock the layers through a join to `StockQuant` | The quant says where stock is, not what it cost. The rows being written are still the layers, and a bare lock over an outer join is what made the reservation service's query unrunnable |
| Derive a shelf from `item_id` or `document_line_id` | The item can move after receipt, and the document line describes the original movement. Neither assigns the remaining value to the shelves where goods now sit; either link can also be absent |
| An advisory lock per `(organization, template)` | The same grain as the row lock, moved outside the rows it protects: more machinery for no narrower scope |
| Drop the lock and lean on `CHECK (remaining_qty >= 0)` | The constraint turns a lost update into a failed transaction, not into a correct one: the second outflow is refused instead of drawn, and retries become the caller's problem |
| Lock only the rows the drain will consume | The drain does not know which layers it will consume until it has read them; deciding first and locking second is the race the lock exists to close |

## Consequences

**Positive**

- The grain is as narrow as the table's columns allow: one product in one
  organization — never the organization, never unrelated products.
- A layer's remainder can no longer be read by two drains at once, so
  `remaining_qty` means what it says and every rate and value report built
  on it keeps meaning it.
- Rows are locked in consumption order, the order they are written, so two
  drains cannot deadlock against each other.

**Negative**

- Two outflows of one product from two warehouses wait for each other even
  though they touch different shelves. On a single-warehouse install nobody
  notices; on a busy multi-warehouse one, throughput on that product is
  capped by the duration of a drain.
- The lock holds every open layer of the product, not only the layers this
  outflow will consume: the select locks the whole FIFO queue and the loop
  stops early.

**The condition for revisiting it** is a location on the layer. If
`StockValuationLayer` ever gains a `storage_location_id` — for valuation
reasons of its own — the lock can narrow with it, and this ADR is what
should be reopened.
`backend/tests/unit/test_a_cost_layer_has_no_shelf.py` pins the model fact
the decision rests on, so the premise cannot rot in silence.

## References

- [ADR-004](ADR-004-stockquant-source-of-truth.md) — the quant as the
  authoritative shelf, and the per-location write paths this lock cannot
  borrow.
- `backend/app/services/valuation_service.py` — `_open_layers`, the lock and
  the comment that states its scope, called by `_post_delivery_async` and
  `lock_open_layers_async`.
- `backend/app/services/_stock_quant_ops.py` — `take_from_the_records_async`,
  the draw across shelves that replaced the quant-side sibling with ADR-022;
  it plans under the stock anchors' locks.
- `docs/subsystems/VALUATION.md` — "What a drain locks, and why the shelf
  cannot narrow it".
