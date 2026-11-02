# Stock posting mutation report

The campaign behind this record is `make mutate-stock`. The run is on
demand, not part of the pre-push gate or CI: a stock posting mutant costs a
database fixture and a handful of integration tests, and the full campaign
is about three hours on one worker.

The same file records the result of the last full run. Re-run the target
after changing the posting code or the tests it names; `mutmut` keeps its
work in a `mutants` directory beside `backend/pyproject.toml` (ignored by
git, created by the first run), where `mutmut results` and `mutmut show
<name>` read what the last run left.

## Scope

Mutated functions — the writes a stock operation passes through:

| Module | Function | Why it is in scope |
|---|---|---|
| `app/services/_stock_draw.py` | `plan_draw_async` | which records a draw may take, in what order, and how much is free of the holds |
| `app/services/_stock_quant_ops.py` | `take_from_the_records_async` | the draw writes each record and publishes one movement per shelf and batch |
| `app/services/_stock_quant_ops.py` | `post_movement_async` | a one-step receive, issue or move writes the records and the movement as one pass |
| `app/services/_stock_quant_ops.py` | `_plan_under_the_anchors_async` | a draw re-plans under every anchor it actually took from |
| `app/services/_stock_reservation.py` | `reserve_for_document_async` | a document's promise never exceeds what the grain has free |
| `app/services/items/_stock_quant.py` | `apply_quantity_change_async` | a record's own change: the ceiling, the anchor lock, the shortage refusal |
| `app/services/items/_stock_quant.py` | `_post_the_change_async` | the movement and the cost layer a record's change leaves behind |

The read paths and pure helpers in the same files (`records_by_grain_async`,
`held_quantity_async`, `_refuse`, …) are not mutated: a mutant there says
something about a query or a sentence, not about whether a write is safe,
and the existing suite pins those reads from both sides.

Writers outside these four files are not mutated either. Most of them reach
the movement through a function above (`relocate_stock_async` and
`carry_record_stock_async` in `app/services/items/_stock_relocation.py` post
through `post_movement_async`), but a few write on their own and the campaign
does not cover them: `post_opening_balance_async` and
`adopt_card_with_opening_async` (`app/services/items/_stock_quant.py`, the
opening balance of a record that joins the register),
`release_for_document_async` and `release_unbacked_async`
(`app/services/_stock_reservation.py`, the release side of a hold) and the
movement writers in `app/services/stock_moves_service.py`.

Test selection (in `[tool.mutmut]` of `backend/pyproject.toml`): the property
tests in `tests/integration/test_the_stock_posting_invariants_hold.py` plus
the focused draw, movement, reservation, quantity and opening-balance tests.
`make mutate-stock` runs the property tests with three generated examples
each (`STOCK_PROPERTY_EXAMPLES=3`; the gate's own run uses twenty): a mutant
is killed by the first test that notices it.
Within that selection a mutant is charged to every test that calls its
function, at any depth: `max_stack_depth` is left at mutmut's default of no
limit, so a test that reaches the posting through a document flow counts as
well as one that calls it directly.

## Result

A mutant name below is the whole dotted name `mutmut show` takes:
`<module>.x_<function>__mutmut_<n>`.

The numbers below were last recorded on 2026-10-22 (`4150764ce`), against
the posting code as it stood then. Mutant numbers (`__mutmut_<n>`) count mutation
sites in a function's source in order, so they name the same change only for
that source: later commits changed `plan_draw_async`,
`take_from_the_records_async`, `post_movement_async`,
`reserve_for_document_async` and `_post_the_change_async` (set-based posting
of a document's lines, a reservation by batch name, a business refusal with
its own code), and the table needs a fresh run, and the mutant names a fresh
`mutmut results`, before it is read as the record of today's code.

The full campaign ran at the head before the audit. Two audits then read
every survivor against the code, including what is reached past the mutated
line, and moved five out of the equivalent class (listed under *Killed after
the audit*); each was re-run by name (`mutmut run <mutant>`) at a head with
the posting code unchanged since the campaign, and each reports killed. The
counts below include those five kills. The other survivors stay equivalent
for the reasons recorded with them.

| | |
|---|---|
| Mutants generated in scope | 690 |
| Killed | 671 |
| Survived (all equivalent, reasons below) | 15 |
| No tests | 0 |
| Timed out | 4 |

Per-file result:

| File | Mutants | Killed | Survived | Timed out |
|---|---|---|---|---|
| `app/services/_stock_draw.py` | 167 | 163 | 3 | 1 |
| `app/services/_stock_quant_ops.py` | 230 | 226 | 1 | 3 |
| `app/services/_stock_reservation.py` | 100 | 93 | 7 | 0 |
| `app/services/items/_stock_quant.py` | 193 | 189 | 4 | 0 |
| **Total** | **690** | **671** | **15** | **4** |

## Surviving mutants

Each survivor is recorded as equivalent — the mutation changes nothing a
caller can observe, for the reason given. The reason follows the mutated
value to every place it is read: what the function returns, what it writes,
and every validation, lookup and lock reached after the mutated line. The
four timeouts are listed after them: a mutant whose tests block cannot pass,
and the runner records the stop instead of a kill.

| Mutant | Change | Verdict |
|---|---|---|
| `plan_draw_async__mutmut_84` | the holds query is asked for every shelf instead of the named one | equivalent: the holds are read into a map keyed by the whole grain, shelf included, and the only reader is `left`, built from the candidate records, which are already filtered to the shelf. Another shelf's hold sits under a key nothing looks up. The query takes no lock and raises nothing; it reads more rows, which is cost, not behaviour. |
| `plan_draw_async__mutmut_119` | `sum(left.values(), Decimal('0'))` → `sum(left.values())` | equivalent: the line is reached only when `records` is non-empty, so `left` has at least one `Decimal` and `0 + Decimal` is that `Decimal`, exactly; no float enters and the type of `free` does not change. |
| `plan_draw_async__mutmut_127` | `if wanted <= 0: break` → `if wanted < 0: break` | equivalent: past the line, a zero `wanted` gives `take = min(..., 0) = 0` for each remaining record and `take <= 0: continue` skips it. The loop body calls nothing before that `continue`, so no draw, query or lock differs; the plan is the same list. |
| `_plan_under_the_anchors_async__mutmut_1` | default `any_owner: bool = False` → `True` | equivalent: the default is never read — both callers (`take_from_the_records_async`, `reserve_for_document_async`) pass `any_owner` by keyword. |
| `reserve_for_document_async__mutmut_1` | default strategy `'FIFO'` → `'XXFIFOXX'` | equivalent: the default is read (the document workflow's reservation names no strategy), and it travels to `plan_draw_async` as `strategy`. A strategy that is not `None` skips the template lookup, and its one reader, `records_in_removal_order`, compares it with `'FEFO'` only; any other string is the FIFO order. Nothing logs, stores or validates it. |
| `reserve_for_document_async__mutmut_2` | default strategy `'FIFO'` → `'fifo'` | equivalent: same reason — the one comparison is with `'FEFO'`, so both spellings give the FIFO order. |
| `reserve_for_document_async__mutmut_12` | zero-quantity result drops `success=True` | equivalent: `ReservationResultDTO.success` defaults to `True`, the removed value. The DTO differs only in pydantic's `model_fields_set`, which no caller reads (the two in the tree read `success` and `unreserved_quantity`) and the contract does not promise; nothing serialises it with `exclude_unset`. |
| `reserve_for_document_async__mutmut_49` | shortfall result drops `reserved=[]` | equivalent: `reserved` defaults to an empty list; same note on `model_fields_set`. |
| `reserve_for_document_async__mutmut_86` | success result drops `unreserved_quantity=Decimal('0')` | equivalent: the field defaults to `Decimal('0')`; same note. |
| `reserve_for_document_async__mutmut_87` | success result drops `success=True` | equivalent: `success` defaults to `True`; same note. |
| `reserve_for_document_async__mutmut_88` | success result drops `message=''` | equivalent: `message` defaults to `''`; same note. |
| `_post_the_change_async__mutmut_1` | default `sync_valuation: bool = True` → `False` | equivalent: the default is never read — the only caller, `apply_quantity_change_async`, passes `sync_valuation` by keyword. |
| `_post_the_change_async__mutmut_2` | default `move_reference_type` `'item'` → `'XXitemXX'` | equivalent: the default is never read — the only caller passes `move_reference_type` by keyword. |
| `_post_the_change_async__mutmut_3` | default `move_reference_type` `'item'` → `'ITEM'` | equivalent: same reason. |
| `_post_the_change_async__mutmut_39` | `if delta > 0` → `if delta >= 0` | equivalent: `if delta == 0: return` comes first, with only the shelf check before it, so the branch never sees a zero. A `NaN` delta is not `== 0` and raises `InvalidOperation` on either comparison. |

## Killed after the audit

The first run recorded these five as equivalent. The audits found that each
changes what a caller observes; all five are counted as killed above, and the
named test kills it.

| Mutant | Change | Why it is not equivalent | Test that kills it |
|---|---|---|---|
| `_plan_under_the_anchors_async__mutmut_35` | `held \|= await lock_stock_async(...)` → `held = ...` | When a first receipt on another shelf commits while the every-shelf lock waits, the plan draws that shelf too. The union keeps the anchors locked before the plan in the set the re-plan is checked against; replacing it forgets them, so each re-plan finds one of the two shelves missing from the held set, locks it, forgets the other, and never settles. | `test_an_every_shelf_draw_keeps_the_anchors_it_locked_before_the_plan` in `tests/integration/test_a_group_of_stock_is_locked_through_its_anchor.py` pins the shelf's anchor while the receipt commits on a second shelf, then asks for both shelves' stock; the unmodified draw settles and takes two, the mutant never returns. |
| `take_from_the_records_async__mutmut_4` | the empty-draw guard asks `storage_location_id is not None` instead of `is None` | The guard is the every-shelf zero-quantity early return only. A named shelf goes through the plan, and a shelf holding stock that gives nothing raises `StockUnavailableError(ALL_HELD)`; the mutant answers `[]` without planning. | `test_a_named_shelf_plans_a_zero_draw_instead_of_short_circuiting_it` in `tests/integration/test_the_draw_honours_the_grain_it_names.py` asks for zero on a named shelf that holds three and expects the held refusal. |
| `take_from_the_records_async__mutmut_5` | the every-shelf zero guard `quantity <= 0` → `quantity < 0` | The early return comes before the named batch's consumable check and the every-shelf lock. A zero draw past the guard still plans nothing, but naming a held batch it is refused with `ValueError` (the batch is held and cannot be consumed) where the guard answers `[]`. The first audit judged it by the movements alone. | `test_a_draw_of_nothing_asks_nothing_of_the_batch_it_names` in `tests/integration/test_the_draw_honours_the_grain_it_names.py` asks every shelf for zero of a held batch holding three and expects `[]` and the three still there. |
| `_post_the_change_async__mutmut_92` | the consumable-batch check of the record's own batch is scoped to no organization | The first audit called it equivalent because the id is the record's own `lot_id`. But nothing in the schema ties a record's `lot_id` to a batch of its own organization (a plain foreign key to `stock_lots.id`), so a record can point at another tenant's batch. The scoped lookup answers as for a batch that does not exist; unscoped, a consuming decrease is refused with the other organization's batch name and status in the sentence. | `test_the_batch_check_never_names_another_organizations_batch` in `tests/integration/test_a_record_change_leaves_its_move_and_its_cost.py` points a record at another organization's held batch and consumes from it; the scoped check lets it through, the mutant raises naming the foreign batch. |
| `_post_the_change_async__mutmut_95` | the consumable-batch check drops its organization argument | Same as `_mutmut_92`: the argument defaults to `None`, the unscoped lookup. | The same test. |

Timed out:

| Mutant | Change | Verdict |
|---|---|---|
| `plan_draw_async__mutmut_147` | `RecordDraw.storage_location_id=record.storage_location_id` → `None` | timed out: the write-side property hangs on a movement with no shelf. `test_a_plan_names_the_shelf_every_record_stands_on` fails the mutant too, so it cannot pass; the runner meets the hang first. |
| `_plan_under_the_anchors_async__mutmut_34` | `if not unheld:` → `if unheld:` | timed out: the plan returns before locking a shelf it drew on, and the concurrent lock tests block on it. |
| `_plan_under_the_anchors_async__mutmut_36` | `held \|= await lock_stock_async(...)` → `held &= ...` | timed out: the loop forgets every anchor it held and re-plans forever; the lock tests block. |
| `_plan_under_the_anchors_async__mutmut_42` | the re-plan's `lock_stock_async` call drops `keys=sorted(unheld)` | timed out: nothing is locked, the loop never settles, and the lock tests block. |

## How to reproduce

```bash
make mutate-stock
```

The command prints every survivor or timeout (`mutmut results`, filtered);
`mutmut export-cicd-stats` writes the totals this report records. `mutmut show <mutant>`
prints the diff of one mutant; `mutmut run <mutant>` re-tests one by name;
`mutmut browse` opens the interactive view.
