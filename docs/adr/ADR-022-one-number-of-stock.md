# ADR-022: One Number of Stock — the Record Is the Stock, a Quant Is a Sum, the Anchor Is the Lock

## Status

Accepted — 2026-09-30. Supersedes [ADR-004](ADR-004-stockquant-source-of-truth.md).

## Context

ADR-004 kept two numbers of the same stock: the quant table (`stock_quants`,
per product, shelf, batch and owner) as the truth, and `Item.quantity` on each
record as a cache of it. A bridge on every quantity path kept them aligned.
Two numbers needed a machine to keep them one, and the machine had to be
remembered by every new write:

- the bridge itself, and a `sync_stock_quant` flag that every door writing a
  record had to thread correctly ("forget once → drift", ADR-004's own
  negative consequence);
- a self-heal that hydrated a shelf from its records when the table had no row
  for it — which healed legacy data and could equally hide a missing write;
- four reconciliation pairs, two of which existed only to compare the records
  and their sum with the table;
- a drift detector in the test suite, and a ratchet on tests that built shelf
  state behind the records' back.

Whether the record could be the only number was measured before it was
decided:

- **Drift detector over the full suite.** Of 647 observations in 442 tests,
  one class was an application defect (an edit that created a card and posted
  no opening balance, since fixed); everything else came from test fixtures
  that seeded one side only. Run again on the last commit that still wrote the
  table, it found no disagreement that application code made on its own.
- **Grain census.** A record can carry its batch and its owner: on the seeds,
  every ambiguous group could be assigned to batches by rule (10 of 10, 11
  records split in two); a household has no batches and no ambiguity.
- **Reads from the records.** Availability of one group from a view summing the
  records answered at p95 0.6–0.9 ms; the other reads within 2× of the table at
  p95, and dispatch faster (0.65–0.92×), because the quant write and its lock
  go. The stock page was 3.8–4.0× until it was rewritten to walk the anchors.
- **A lock without a quant row.** Concurrent dispatches and reservations on
  real Postgres oversold nothing, went below zero nowhere and did not deadlock
  with a numberless lock row per (organization, product, shelf), in 3/3 runs,
  on the condition that every operation over several groups locks all of them
  first, in one order.
- **Cost and increments.** Five increments, each leaving a consistent system;
  only the one that drops the table cannot be undone by reverting code.

The irreversible step (dropping the table) was taken only once three
conditions held: no test built shelf state behind the records' back, the stock
page read within 2× of the table, and every reconciliation pair was at zero on
fresh seeds.

## Decision

**The record is the stock.** `Item.quantity` on a record is the only number
of stock there is. A record is one batch of one owner on one shelf
(`Item.lot_id`, `Item.owner_id`, `Item.storage_location_id`); two batches on
one shelf are two records.

**A quant is a sum.** `stock_quants_from_records` sums the live records per
(organization, product, shelf, batch, owner), and the reservation rows per
the same grain: on hand, reserved, available. Nothing writes it; availability,
FIFO/FEFO, the stock page, the stock on a date and the reconciliation read it.
"Quant" is kept as the name of that sum (`StockQuantDTO`,
`core_api.stock.list_quants_async`).

**The anchor is the lock.** `stock_anchors` has one row per (organization,
product, shelf) and no numbers. Whoever writes a group's records or holds
locks its anchor first (`core_api.stock.lock_async`); an operation over several
groups locks all of them first, in one order. A record with a product references
the anchor of its group, so it cannot exist outside one; a record without a
product joins no group.

**A reservation is its rows.** `stock_reservations` names the anchor, the
batch, the owner, the document and the quantity. Deferred constraint triggers
refuse, at commit, a grain whose reservation rows promise more than its
records hold — the one database-level net for "reserved ≤ stock" now that the
table's CHECKs are gone.

**The movement ledger explains a change, it does not hold stock.** Every
change to a record's number posts a movement (`StockMove`) and its cost layer
in the same transaction:

- a single record's change posts itself (`apply_quantity_change_async` →
  `_post_the_change_async`): the movement, the layer, and on a decrease the
  refusal when the grain cannot give it without eating a hold;
- a door that moves several records as one movement — a document line, a
  production run, a draw across shelves — writes the records with
  `post_the_change=False` and the movement through one call,
  `core_api.stock.post_movement_async` or
  `core_api.stock.take_from_the_records_async`, one movement per shelf and
  batch. Never a record write and a movement write as two separate steps.

**The reconciliation keeps two pairs:** the shelf (the records' sum) against
the net of the movement ledger, and the cost layers against the shelf. The
pairs that compared the records and their sum with the table ended with the
table, and so did their fields on the contract and on the screen.

### How it got there

| step | what changed | migrations (the core ones are archived, their result is `baseline_002`) |
|------|--------------|------------|
| 1 | records carry their batch and owner; every stock write keeps them | `lotrec01`, `lotrec02` |
| 2 | the records' view stands beside the table and is compared with it | `quantview01` |
| 3 | readers move to the view, family by family; the stock page walks the anchors | `stockpage01` |
| 4 | anchors, reservation rows with their own grain, the hold guard; the table goes | `anchors01`–`03`, `resgrain01`, `holdguard01`, `quantdrop01`, documents `doc_pick_quant_gone01` |
| 5 | the bridge is the record's own posting, the table's reconciliation pairs go, this ADR | — |

The archived `quantdrop01` is the only step that is not undone by reverting code. Its
downgrade rebuilds the table from the view — every constraint it had, each
reservation pointed back at the quant of its grain — which is a rebuild, not
a restore.

### Alternatives considered

| Approach | Verdict |
|----------|---------|
| **Keep ADR-004** (two numbers, a bridge) | Rejected — the bridge, the flag, the self-heal, four pairs and the detector have to be kept forever and remembered on every new write; and the number of tests that built shelf state behind the records' back kept growing. |
| **The quant table as the only number** (drop the record's quantity) | Rejected — a record is what a person sees and labels: its expiry, price, photo and label are per record; the household vertical reads one number per record. |
| **A materialized view** for the quants | Rejected — for the reason ADR-004 gave: a refresh lag is a consistency window, and a refresh is heavyweight. |
| **A lock per full grain** (product, shelf, batch, owner) | Rejected — FEFO picks the batch inside a shelf, so a lock finer than the draw cannot serialize the choice. |
| **Records, a view of them, and a numberless anchor** | **Chosen.** |

## Consequences

### Positive

- **Nothing to keep in sync.** A new write path cannot drift from a copy that
  does not exist; the bridge, the flag, the self-heal, the table's pairs and
  the drift detector are gone.
- **Reads held or improved.** The stock page at 0.22–0.58× of the table read,
  one place at 1.21× (about 1 ms more).
- **Writes held.** Throughput of the stock doors without the table within
  noise of the table (hot group 1.03×, spread 0.98×), 0 deadlocks in 18 runs;
  the many-hands probe left the stock whole in 3 runs of 3.

### Negative

- **Every stock read is a sum.** It is bounded by the records' group index,
  but a read that sums a whole organization many times over pays for it.
- **Locking is a discipline.** A writer must take the anchor before it writes,
  and an operation over several groups must take them all first. The posting
  and the doors do; a new door that does not can race.

## Risks

- **The hold guard is the only database net for "reserved ≤ stock".** A path
  that writes reservation rows past the records gets an error at commit
  instead of oversold stock — the intended failure, but a failure at commit
  rather than at the line that caused it.
- **A database with a past** may carry a gap between the shelf and the ledger
  from the days the first quant of a shelf was hydrated with its full
  quantity while its movement recorded only the delta. The reconciliation
  measures it rather than presuming it; the figure to watch is one that grows.

## Implementation

- Records: `backend/app/models/item.py` (`quantity`, `lot_id`, `owner_id`).
- The sum: `backend/app/models/stock_quants_from_records.py`.
- The lock: `backend/app/models/stock_anchor.py`, `core_api.stock.lock_async`.
- Reservations: `backend/app/models/stock_reservation.py`, `baseline_002` (from the archived `holdguard01`).
- A record's own posting: `backend/app/services/items/_stock_quant.py`
  (`apply_quantity_change_async`, `_post_the_change_async`,
  `lock_record_stock_async`).
- The doors that move several records as one movement:
  `backend/app/services/_stock_quant_ops.py` (`post_movement_async`,
  `take_from_the_records_async`), through `core_api.stock`.
- Reconciliation: `backend/app/services/analytics/reconciliation.py`,
  `backend/app/services/reconciliation_job.py`,
  `GET /api/v1/stats/reconciliation`.

## References

- [ADR-004](ADR-004-stockquant-source-of-truth.md) — the two-number model this
  one replaces.
- [ADR-020](ADR-020-cost-layers-lock-per-product-not-per-shelf.md) — the cost
  layers lock per product; `lock_async` with no shelf takes every shelf of it.
- [ADR-021](ADR-021-handling-units-are-not-modelled.md) — why the grain has no
  package.
- `backend/AGENTS.md` §"Stock Posting Rules"; `docs/subsystems/STOCK.md`.
