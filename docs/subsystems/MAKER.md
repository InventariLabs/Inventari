# Maker Module — universal "own production" engine

**Status:** Official module (`module_type: official` in its manifest).
**Dependency direction:** `maker` consumes other modules' public APIs (`recipes_api`), never the reverse.

The module describes **making**: the moment ingredients become a new product.
One model covers three user profiles — the home producer ("how much did I
save?"), the DTC craftsperson ("what is the margin?"), the micro-business ("do
I have the ingredients?").

> **Terminology** — a maker recipe (`maker:`) is not a culinary recipe
> (`recipes:`). A maker recipe describes a production batch (composition +
> yield + costs + steps); a culinary recipe has servings and picking. The
> module's i18n namespace is `maker:`.

## Tables

| Table | Role |
|---|---|
| `maker_recipes` | Production recipe for a product template. Several variants per product, **at most 1 default** (partial unique index). `source_recipe_id` = bare UUID with no FK — a soft stamp from a culinary recipe. |
| `maker_bom_lines` | BoM line: ingredient units per batch (`qty_per_batch`), `uom_id`, `yield_loss_pct`, `make_fresh` (an ingredient with a recipe is made through it every time instead of taken from stock first). The line's unit is its `uom_id`, or the catalogue unit its free text names (a line written before units kept its symbol): a save refuses a line whose unit cannot be converted to the ingredient's stock unit, naming both, and a run refuses a line stored before that check — the composition tab marks it as a unit mismatch until one is set. Unique `(recipe_id, child_template_id)`. `parent_template_id` denormalises `recipe.output_template_id` (the invariant is enforced on every write). |
| `maker_recipe_cost_lines` | Fixed batch costs (labour, packaging, overhead). |
| `maker_ingredient_prices` | A price typed once on a product, org-scoped: the last answer a cost estimate asks, after the layers and supplier quotes. One row per product, shared by every formula that uses it. |
| `maker_production_orders` | Production order: DRAFT → COMPLETED / CANCELLED, DRAFT → IN_PROGRESS → COMPLETED / CANCELLED for a run started and finished apart, and COMPLETED → REVERSED when a finished run is taken back. Holds a snapshot of the financial result; for a started run also `started_on` / `started_at`, `material_cost` (what the start took — the run's work in progress) and `steps` (the formula's process steps copied at the start, each with `done_on`). |
| `maker_production_portions` | One portion of an in-progress run's output: quantity, day, batch, the record it opened and the unit cost it was booked at. The closing quantity of `finish` is a portion too. |
| `maker_production_order_lines` | Per-ingredient consumption audit recorded on completion. |
| `maker_module_settings` | The `*_module_settings` pattern (org_id PK, typed columns), including `labor_hourly_rate` — what an hour of the organization's own work costs. |
| `maker_shelf_lives` | How many days a product keeps once made, one row per organization and product (a product can be a catalogue row shared by every organization, so the fact lives here, as a typed price does). |
| `maker_label_facts` | What a product's label says of it, one row per organization and product: `label_name` (the name it goes under in an ingredient list), `allergens` (the EU keys a person confirmed; NULL until someone checked, which is not the same as an empty list) and `may_contain`. A made product's list is computed from these facts on its ingredients. |
| `maker_production_attachments` | Photos and files filed under a run; the files live under the organization's `maker/` storage folder and `/uploads/` serves them through `ProductionAttachmentResolver`. |

## Batch math

```
batches = planned_qty / recipe.batch_yield_qty
effective_qty(line) = batches * qty_per_batch * (1 + yield_loss_pct / 100)
```

- **Leaf** — an ingredient with no default recipe → drawn from the stock
  records across every location (`core_api.stock.take_from_the_records_async`);
  under `availability_check_scope=PER_LOCATION` only from the run's output
  location, the set the availability check judged.
- **Sub-assembly** — an ingredient with a default recipe → what its own stock
  covers is taken from the shelf first and only the rest is exploded
  recursively, depth-limited (`_MAX_DEPTH = 10`). `stock_first.StockPool` is
  the one answer to "how much of this intermediate can a run take": the
  explosion asks it line by line, and availability (`max_batches` is searched
  for, since the need is no longer proportional to the batches), the preview
  and cost breakdown, the shortage list and purchase/shopping-list needs, the
  recipe tree (`stock_on_hand` per sub-assembly line) and completion all
  explode through it, under the scope the availability check resolves. The pool
  is spent as it is asked, so two lines naming one intermediate do not count the
  same stock twice. A line with `make_fresh` never asks it. The catalogue's
  per-batch formula cost (`cost_rollup`) still explodes whole: it prices the
  formula, not the shelf.
- `complete` requires `actual_qty > 0`; consumption is against **planned**,
  output against **actual**; `actual > planned` is possible only with
  `allow_overproduction=true` (sets the `overproduced` flag); `actual < planned`
  produces `scrap_qty` and raises the unit cost — and still consumes the full
  planned ingredients (a recorded decision: the completion dialog says so
  before the click).
- Consumption is exploded **at completion**, not frozen when the order is
  created — editing a formula while an order is open changes what that order
  will take (the recipe journal records every such edit). The draft screen
  says the same: its planned-consumption section notes the quantities are
  read from the formula when the run closes.
- Cycles are detected by `template_id` (ValueError, 400).

## Which calendar the figures are cut on

`monthly_result` buckets a completed run by the organization's month, and its
window (six months by default) opens at local midnight on the first day of its
earliest month —
`core_api.organizations.today_async` / `.timezone_async`, never the server's
`date.today()`. So does a run's own day: completing a run with no production
date asks the period guard about the organization's today and stamps the run
with that same day. The run number comes from the document numbering
register (`PR` type, shape `PR/{YEAR}/…` unless the organization changed it),
which takes the year of an undated document — a run is one — from the same
clock. `completed_at` itself stays a UTC instant; the clock decides how it is
read, not how it is stored. See TECHNICAL_DECISIONS.md §19.

## HTTP API (`/api/v1/maker/*` — gated by `require_module('maker')`)

### Recipes and catalogue

| Endpoint | Description |
|---|---|
| `GET /recipes` | Card catalogue (search/sort/pagination; `output_template_id=` narrows to one product's recipes). `unit_cost` = total cost / quantity of the most recent COMPLETED order of that recipe (one batched query, no N+1), with `uncosted_ingredients`; a recipe never run carries `estimated_unit_cost` instead; also `stock_qty`, `last_produced_at`, `ingredient_count`, `result`. |
| `GET /recipes/{id}` | Detail: lines (each carrying its product's `typed_unit_price`, and `typed_unit_price_in_use` — whether the estimate actually reached that fallback, since the layers and a supplier quote answer first) + fixed costs + `labour_cost` (the steps' time at the hourly rate) + `estimated_unit_cost` (materials from the shared Core estimate — layer-average rate, then a supplier offer, then the typed price — plus fixed costs and labour, per unit) + `source_recipe_id`/`source_snapshot_at`. |
| `POST /recipes` | Create (a template's first recipe becomes the default automatically). `source_recipe_id` stamps `source_snapshot_at`. |
| `POST /recipes/from-recipe` | **The recipes→maker bridge**: snapshots a culinary recipe into a maker recipe plus BoM lines built from ingredients that carry a `template_id` (free-text ingredients are skipped). Idempotent per (output_template_id, source_recipe_id). A culinary recipe that does not exist in the organization returns a plain 404. |
| `PATCH/DELETE /recipes/{id}` | Update / delete (deleting the default promotes the oldest remaining recipe; a recipe that a production order references cannot be deleted, 409). |
| `POST /recipes/{id}/bom-lines` | Add an ingredient to that recipe (the parent comes from the recipe; a duplicate returns 409, a self-reference 400). |
| `PATCH/DELETE /recipes/{id}/bom-lines[/{line_id}]` | Edit a line in place (qty/uom/yield_loss/notes) / remove it. |
| `POST/PATCH/DELETE /recipes/{id}/cost-lines[/{line_id}]` | Fixed costs. |
| `PUT /recipes/ingredient-prices/{template_id}` | Type (or clear, with `unit_price: null`) a product's per-unit price. `maker:manage`: it is an input to the formula's costing, like the formula itself. |
| `POST /recipes/{id}/shortages/purchase-order` | Raise a draft purchase order for one batch's missing ingredients, one line per short ingredient at its typed price. What an open order (DRAFT, PENDING_APPROVAL, CONFIRMED) already expects comes off the shortfall, so a second click does not order the same shortage twice; `already_ordered_count` says how many ingredients it covered. `purchase_orders` must be on; needs `purchase_orders:write`; returns no order when the batch is covered or already on order. |
| `GET /recipes/{id}/availability?batches=&location_id=` | Per-ingredient {needed, available, shortage, uom, convertible} plus `max_batches`. Honours `availability_check_scope` (GLOBAL/PER_LOCATION); `location_id` overrides it. |

### BoM (legacy adapters and reverse lookup)

| Endpoint | Description |
|---|---|
| `GET /bom/summary?template_ids=` | Batched: has-BoM + line_count + `default_recipe_id` (badges on product lists). |
| `GET /bom/template-ids` | Every template in the organization that has at least one BoM line — feeds the "BOM" filter on the virtualised product list, which cannot decide row by row from data it has not fetched. |
| `GET /bom/where-used?template_id=` | The reverse edge — recipes that use a template (JOIN lines→recipes, direct use only, org-scoped, cycles have no effect). |
| `GET /bom/{template_id}` | Lines of one recipe of the product: `recipe_id=`, else the default recipe (adapter). |
| `GET /bom/{template_id}/cost-estimate` | Cost of one unit by the default recipe (shared Core estimated stock-unit costs); `qty=` and `recipe_id=` ask for a batch or a variant. |
| `GET /bom/tree/{template_id}` | Recursive tree (BomTreeEditor): the root is `recipe_id=` (a variant's page passes its own), else the default recipe; each sub-assembly below is its default recipe, as a run explodes it. |
| `POST /bom/{line_id}/move` / `DELETE /bom/{line_id}` | Move a line under a different parent / delete a line. |

`POST /bom` and `DELETE /bom/parent/{template_id}` were removed: they addressed
a *product* and always landed on its default recipe, so with two recipes per
product the write went somewhere other than where the operator was looking.
Line writes go through `POST /recipes/{id}/bom-lines`, and the `/maker/bom`
screen is gone (the route redirects to the catalogue).

### What a new formula costs on day one

A product made an hour ago has no cost layer and no supplier quote, so every
ingredient of a new formula used to price at zero and the formula's margin
said nothing. Three inputs now close that gap, and the estimate policy keeps
one order: **cost layers** (what the stock actually cost), then a **supplier
quote** (a live offer, registered by the purchase-orders module through
`register_supplier_price_provider`), then the **typed price** — one per
product per organization in `maker_ingredient_prices`, written from the
formula's ingredient card or bought through the shortage notice. A typed
price is a fallback, never an override: a product with stock or a quote is
costed by what the records say.

Labour is the formula's own: each process step carries an optional duration,
and the batch's labour is the sum of those minutes at
`maker_module_settings.labor_hourly_rate`. The recipe detail, the catalogue,
the production preview and a completed run all use the same helper, so the
computed labour line on the cost tab and the run's actual cost agree.

A formula's `process_steps` are objects (`{text, minutes}`). Steps saved
before the duration existed are migrated when the module upgrades — a bare
sentence becomes `{text, minutes: null}`, and blank sentences are dropped as
the write path drops them — while the reader also normalises an old-shaped
row, so a process still writing the old shape during a deploy cannot make a
formula unreadable.

### Estimate against actual

Completion reads the formula's answer before anything leaves the shelf — the
shared estimate over the same exploded list, at the standard quantity for
the output that actually came out (`formula qty × actual / planned`) — and
keeps it on the order (`estimated_total_cost`) and per line
(`estimated_qty`, `estimated_unit_cost_snapshot`). The page shows the two
totals side by side, and splits each ingredient's difference into a **price**
component (`(actual rate − estimated rate) × consumed qty`) and a
**quantity** component (`(consumed qty − standard qty) × estimated rate`).
The identity is exact: estimated material + price effect + quantity effect
equals the actual material cost.

### Production orders

| Endpoint | Description |
|---|---|
| `GET /production/orders` | List (status/output/date-range filters, sort, pagination). Each DRAFT row carries `shortage_count`: how many ingredients the planned consumption cannot cover, counted the way completion refuses — the shared `_shortages_from_needs` verdict at the order's own output location, unmeasurable ingredients included. `null` past the draft, and `null` for a draft without a recipe (nothing to forecast from) — null is "no answer", not a clean zero. Deliberately **not** a filter dimension: the count is computed after the page is cut, so filtering on it would break skip/total semantics; moving it into the query layer is a separate, conscious decision. |
| `POST /production/orders` | DRAFT. Takes a `recipe_id`, or looks up the default by `output_template_id` (no recipe → 400). Honours `create_on_shortage_strategy`: ALLOW / WARN (422 plus the shortage list; re-POST with `confirm_shortage=true`) / BLOCK (422, no DRAFT created — `confirm_shortage` does not lift it). |
| `POST /production/orders/made` | Record a run that already happened: created and completed in one step (`planned_qty` is what came out). Needs `items:write`. An ingredient the records hold too little of does not refuse the run: what they hold is consumed, the rest becomes the line's `shortfall_qty`, and the ingredient shows up as a count in To do (with `stock_takes` enabled). The shortage strategy is not asked. 422 `insufficient_stock` only for a line whose unit cannot be compared with its stock, 422 `empty_bom` for a recipe with no ingredients. |
| `POST /production/orders/preview` | Cost dry-run, no stock mutation. |
| `POST /production/orders/shortages/shopping-list` | Puts what a planned run lacks on the active shopping list (needs `shopping_lists:write`); an ingredient already on the list is not added twice. |
| `GET/PATCH /production/orders/{id}` | Detail (with the result snapshot) / update a DRAFT. Every door that answers with a single order — create, update, duplicate and the read — builds it through one constructor, so a draft carries the same `shortage_count` and `shortage_items` whichever way it came. A draft also carries `shortage_items` — the refusal's own list, the rows behind `shortage_count` — so the page marks every ingredient completion would refuse on instead of recomputing a forecast that could disagree. |
| `POST /production/orders/{id}/complete` | Consumes planned (drawn from the stock records), outputs actual, values the batch, writes `unit_cost_snapshot`/`reference_price_snapshot`/`result_per_unit`/`result_per_batch`, and keeps the formula's own answer beside it: `estimated_total_cost` on the order and `estimated_qty`/`estimated_unit_cost_snapshot` per line. Shortages → 422 with an actionable list (`insufficient_stock`); a recipe with no ingredients → 422 `empty_bom`. Needs `items:write`. |
| `POST /production/orders/{id}/start` | Start a DRAFT: the same draw, lines and stock-first split as `complete`, at the start. The run becomes `IN_PROGRESS` with `started_on` (optional body, default today), `started_at`, `material_cost` and its `steps`. Valued as work in progress until it closes: Core adds the registered providers' value (`app.core.work_in_progress`, this module's reader is `work_in_progress.py`) to the stock value and to `GET /stock-as-of` (`work_in_progress_value`, left out under a location or search filter). Same refusals as `complete`. Needs `items:write`. |
| `POST /production/orders/{id}/portions` | Put a portion of an IN_PROGRESS run's output on the shelf: `qty`, `made_on`, `output_lot_name`. Booked at `material_cost / planned_qty`; the portion carries its share of the work in progress into the cost layers. The portions together cannot go above `planned_qty` (400); output above the plan comes out with `finish`. A portion whose ingredients carried no price is posted as not yet known (`unknown`, `unpriced_stays_unknown` on `core_api.valuation.record_receipt_async`), never at the rate of the product's older stock: until the finish its stock reads no value, and the finish puts the run's cost (fixed costs, labour) on it. A run that has no cost at all leaves such portions `unknown`. Needs `items:write`. |
| `POST /production/orders/{id}/finish` | Close an IN_PROGRESS run. `actual_qty` is what the whole run made, portions included (default: the plan, or the portions if more); the difference is put on the shelf as the closing portion at the rest of the run's cost (material + fixed costs + labour) — when the portions already carry all of it (output above the plan, or a rounding hair booked too much) that share is a stated zero, never "no price", which Core would value at the rate of the product's older stock. `unit_cost` = total / actual. Refused when `actual_qty` is below the portions. When the portions already hold the whole output, the part of the cost they were not booked at (yield shortfall, fixed costs, labour, a rounding cent) is added to the cost layers the portions opened (`core_api.valuation.add_value_to_layer_async`), spread by quantity in whole cents that add up to the rest (the cent a division leaves over lands on the last portion) and only for the units still on the shelf; the value is dated from the finish — a report about an instant before it reads what it did then (`docs/subsystems/VALUATION.md`, *A cost added after the receipt*). What belongs to units that were sold or used before the close is kept on the run as `unshelved_cost` and never refuses the finish. Needs `items:write`. |
| `PUT /production/orders/{id}/steps/{index}` | Tick a step of an IN_PROGRESS run with `done_on`, or clear it with null. Journalled. |
| `POST /production/orders/{id}/cancel` | Cancel a DRAFT or an IN_PROGRESS run (optional `reason`, stored as `cancel_reason`). An in-progress run gives its ingredients back through the same way back `reverse` uses (`production_reversal.put_ingredients_back`); refused once it has portions. Needs `maker:manage`, and `items:write` for a run in progress. |
| `POST /production/orders/{id}/reverse` | Take a COMPLETED run back: the ingredients return to the records and batches they were taken from, the output leaves its location (every portion of a run filled in portions, each off its own record; every record is checked before any comes off, because portions share the batch they were filed under), and the run is marked REVERSED (it stays on record; the movements of the way back name it). Refused (400) for a run that is not completed or whose output has since left its shelf. Needs `maker:manage` and `items:write`. |
| `POST /production/orders/{id}/duplicate` | Duplicate as DRAFT (copies `recipe_id`). A copy is a new plan: under BLOCK a copy the stock cannot cover is refused like a creation (422 `shortage_blocked`); under WARN it is created and its page names the shortage. |
| `GET /production/orders/{id}/stock-moves` | The order's stock moves. |
| `GET /production/monthly-result?months=` | Aggregates `result_per_unit × actual_qty` per month (dashboard widget). |

### One shortage signal

The list's count, the detail page's banner and rows, and the 422 refusal are
one verdict: `availability_service._shortages_from_needs`. Completion refuses
through `compute_shortage_list`; the page batch reads
`shortage_signals_for_orders`, which explodes the page's recipes in one round
(`explode_by_recipes_with_uom` — recipes and lines in one select, every
child's default recipe resolved transitively, one query per depth level for
the whole set), reads stock once per distinct location scope, templates and
units once per page, and decides scope through the same `_resolve_scope` rule
the single-order check uses — the settings read unlocked (`for_update=False`),
so a GET never queues behind a maker write. No screen recomputes the forecast
client-side; the detail page reads `shortage_items` from the order payload.

### Planning across runs

Each draft read its availability alone, so two drafts that each needed six of
ten flour both read as covered. `planning_service` reads the drafts as one queue
(`queued_drafts`: planned day, then creation, a run with no day behind every
dated one) and walks it once (`walk_plan`); the coverage of each run and the
combined needs list both read that walk, so the plan cannot call a run covered
while the list under it says its dough is missing. The walk is per availability
scope (`_resolve_scope`): each scope has its own shelf, read once.

A run asks for its formula one level deep (`bom_service.plan_needs`): "dough",
not the dough's flour. A line marked make-fresh is the exception — the run makes
that sub-assembly itself and never takes it from the shelf, so the
sub-assembly's own ingredients stand in its place. The walk goes one planned day
at a time: what that day's draft runs make goes on the scope of the run that
makes it, so it serves the runs of that day (whatever was created first) and of
the days after, never a run planned before it. Each run then takes an ingredient
from the shelf first and from what planned runs made after that. What neither
covers is short: a sub-assembly nobody makes in time is a run to plan
(`plan-intermediates`), and the plan does not count on the flour the run could
take to make the dough itself. Completion still does that — it judges the shelf
as it stands and makes a missing sub-assembly inside the run (*Stock first*) —
so a draft can read `short` in the plan and still complete.

What is on its way is spent the same way. The runs before a period take the
shelf, then what planned runs make, and what they still lack from the open
purchase order lines (earliest delivery first), so the period reads only what
they left: a delivery ordered for one week, or a dough run planned for it, is
not counted again by the week after it.

| Endpoint | Description |
|---|---|
| `GET /production/orders`, `GET /production/orders/{id}` | `planned_from` / `planned_to` bound the planned day (`production_date`; a run with no day is in no such period) where `date_from` / `date_to` bound the creation date — the plan screen asks for the former. A draft also carries `coverage` (`covered`, `partial` — some of what it needs is there — or `short` — none of it) and `coverage_items`, the ingredients that fall short of what is left for it. `shortage_count` / `shortage_items` stay completion's verdict on the shelf as it stands; the two answer different questions, and a draft behind another in the queue can be `partial` while completion would still let it through. |
| `GET /production/needs?date_from&date_to` or `?order_id` | The combined needs of the draft runs planned in a period (or of one run), one level deep (`bom_service.plan_needs`): per ingredient `needed`, `in_stock` (what is left after the runs queued before the period took theirs), `on_order` with `expected` (open purchase order lines and their dates) and `planned` (what draft runs of the ingredient itself make in time for it, beyond the shelf) and `missing`, all in the ingredient's stock unit. With purchasing off `on_order` is `null` and `expected` empty — the column does not exist, which is not "nothing on order". An ingredient that has a recipe of its own is `action: make`, otherwise `buy`; a sub-assembly on a make-fresh line is listed as its own ingredients, since the run makes it itself. Ingredients whose unit cannot be compared with stock come back in `unmeasured`, not in the figures. |
| `POST /production/needs/order` | Needs `purchase_orders:write` and the module on. One DRAFT purchase order per supplier and currency (the organization's own currency first; a supplier quoting in two gets two orders), each missing `buy` ingredient from its cheapest current price (compared per stock unit, within one currency) in the supplier's own unit, rounded up to a whole step and to the supplier's minimum; a volume price the shortage does not reach is passed over unless the order it forces costs less in total; those nobody offers go to the shopping list (`put_missing_on_shopping_list`, the one door the run's own shortage uses too), or come back as `unplaced` when that module is off. A `make` ingredient is never bought: it comes back in `to_make`. Open orders count as on order, so ordering twice orders once. |
| `POST /production/needs/plan-intermediates` | A DRAFT run of each missing `make` ingredient, on the day it is first needed, for the missing quantity. The shortage strategy is not asked: the shortfall is the point. |

Purchasing is reached only through `purchase_orders_api`
(`list_open_order_lines_async`, `list_supplier_prices_for_template_async`,
`create_purchase_order_async`); the other way round, purchasing asks
`maker_api.list_template_ids_with_bom_async` which products have a recipe: a
reorder alert for such a product carries `make_instead`, proposes no supplier,
and To do gets a `produce` task (`source_kind: production_proposal`) opening
`/maker/production?plan=<product>&quantity=<n>`. With either module off the
other keeps working: no on-order column and no ordering without purchasing, a
purchase proposal as before without production.

### The output batch, its dates and the ingredients' batches

Every completed run files its output under a batch (`output_lot_name`,
`output_lot_id`). A run filled in portions files each portion under the batch
its person named (a portion nobody named a batch for goes into the run's own),
so its output may be several batches: `output_lot_*` is the run's own — the
first one its output went into, named as that batch is — and `output_batches`
lists them all, the run's own first. A run nobody named a batch for names its own from its day and
a counter, unique among the product's batches in the organization
(`20261115-1`, `20261115-2`, …) — computed under the output card's lock the
run takes from the top, so two runs of one product closing at once count on
from each other. The batch is opened with the run's day as `production_date`
and a best-before (`expiry_date`) of that day plus the product's shelf life
(`maker_shelf_lives`), unless the person closing the run names another
(`best_before` on completion and on `/orders/made`); a date before the run's
day is refused. The output record carries the same `expiry_date`, as a receipt
writes it, so FEFO, the expiry views and To do read made goods like received
ones. A batch that already existed keeps the dates it was opened with.

Before closing, `GET /production/ingredient-batches` answers per leaf
ingredient what the run needs (stock unit), the draw it makes when nobody
chooses (`plan_draw_async`, the product's removal order, at the scope the run
draws under) and every batch with stock free to take. Held, recalled and
expired batches are in neither. A completion or a run recorded as made may send
`ingredient_lots` — `(template_id, lot_id, quantity)` — and the run then takes
exactly those batches: the choices of one ingredient must add up to its need
(compared at four places), a batch must belong to the ingredient, and on a
completion a batch that cannot give its part is refused before anything is
drawn (`production_batch_short`). A run recorded as made takes what a chosen
batch has and records the rest as the line's shortfall. The screen sends the
default plan back when every part of it names a batch, so the run takes what
the person saw.

The shelf life is the maker's own fact about a product. A module that dates
its output another way opens its batch with its own dates through
`core_api.stock.get_or_create_lot_async` and never reads this table; the
dates belong to the batch, not to the product card.

| Endpoint | Description |
|---|---|
| `GET/PUT /production/shelf-lives/{template_id}` | A product's shelf life in days (`null` clears it). The write needs `maker:manage` and is journalled on the product. |
| `GET /production/ingredient-batches?output_template_id=&planned_qty=&output_location_id=&recipe_id=` | The batch plan above, read-only. |
| `POST /production/orders/{id}/hold` / `…/release` | Hold every batch of the run's output (`reason` required) or release those on hold — Core's quarantine and release, journalled on each batch; the answer lists them all in `batches`. A batch that is not on hold keeps its state on a release. Needs `maker:manage`; refused for a run that filed no batch. |
| `GET /production/orders/{id}/record` | The batch record of a completed run: formula, quantities, every ingredient with the batches taken (read from the run's movements), costs, who and when, notes and files. 400 for a run that never completed. |
| `GET/POST /production/orders/{id}/attachments`, `DELETE …/{attachment_id}` | A run's photos and files, at a product attachment's limits (10 MB, the attachment types, the bytes checked against the declared type); each file filed or removed is a journal entry on the run. Writing needs `items:write`. |

The detail read of an order carries `output_lot_id`, `output_lot_status` (the
run's own batch's state now — a hold shows), `best_before`, `output_batches`
(every batch the output was filed under, each with its state and best-before;
the batch record carries the same list) and the output product's
`shelf_life_days`; the preview carries `shelf_life_days` too. Batch labels
print through the printing module's batch target (`lot_ids`,
`POST /printing/lot-labels/png`): the product, the batch code in bars, the
production date and the best-before, up to two hundred copies.

### A made product's label

`labelling.py` computes a made product's label from a recipe and its
ingredients' label facts, the way EU Regulation 1169/2011 asks a food
producer to write it:

- **Ingredient list** — each line weighed as used: `qty_per_batch × (1 +
  yield_loss_pct / 100)` in grams, converted through the line's unit (a
  weight directly; a count or a volume through the card's `weight_value`,
  what one stock unit weighs). Heaviest first; equal weights by name, so two
  reads print the same list; a line nothing says the weight of is named in
  `unweighed` and listed last. An ingredient with a default recipe is a
  compound ingredient: its own list follows it in brackets, ordered by its
  own weights, every level down (the same depth limit and cycle refusal as an
  explosion). An ingredient goes under its `label_name`, else its product
  name, and is emphasised when its card names an allergen.
- **Allergens** — every allergen any ingredient's card (at any level,
  intermediates included) confirms, each with the ingredients that bring it;
  one declared on the made product itself is kept (`declared_on_product`).
  A leaf nobody has checked is named in `unchecked` with what its name
  suggests (`recipes_api.infer_allergens`) — a suggestion is never counted.
  **May contain** collects the ingredients' and the product's own, minus what
  the product already contains.
- **Nutrition per 100 g** — from the figures on the ingredients' cards
  (`meta_data['nutrition']`: `calories_kcal`, `fat_g`, `saturated_fat_g`,
  `carbs_g`, `sugar_g`, `protein_g`, `salt_g`, per 100 g). A made ingredient
  is read through its recipe: what its lines put in, divided by what its
  batch weighs (`batch_yield_qty` in grams). The top level divides by what
  the batch yields, so the water a bake loses concentrates the figures as it
  does in the product. A figure an ingredient lacks makes that figure unknown
  and names the ingredient (`missing`); it is never counted as zero. kJ is
  kcal × 4.184; energy is rounded to a whole number, salt to a hundredth,
  the rest to a tenth. With no figure on any ingredient there is no
  declaration (`nutrition: null`).
- **Label text** — `label_text` writes "Ingredients: …" with the allergens in
  capitals (a one-colour label keeps them where bold may not survive), a
  "Contains: …" sentence only for an allergen declared on the product that no
  ingredient brings, and "May contain: …".

Where another rule set plugs in: the label name is free text, so an INCI
name goes in it; the allergens and the composing are the food regulation's.
A module with its own labelling rules (cosmetics, wine) has no seam here
yet — it would read the same facts and recipe tree through `maker_api` and
compose its own text.

| Endpoint | Description |
|---|---|
| `GET /labelling/products/{template_id}` | A product's `label_name`, `allergens` (null: not checked), `may_contain`, `suggested_allergens` (from its name), and for a made product its default recipe's `recipe_id` and `recipe_name`, `derived_allergens` and `derived_may_contain`, each with its sources. |
| `PUT /labelling/products/{template_id}` | Keep them (`maker:manage`); an unknown allergen key is a 422, everything empty clears the row. Journalled on the product with both sides. |
| `GET /labelling/recipes/{recipe_id}` | The label that recipe computes: `ingredients` (tree, `weight_g` per batch, `emphasised`), `text`, `allergens`, `may_contain`, `unchecked`, `unweighed`, `yield_weight_g`, `nutrition`. |

### Other

| Endpoint | Description |
|---|---|
| `GET /settings` / `PATCH /settings` | `maker_module_settings` (reference, overproduction, availability scope, shortage strategy, hourly labour rate). |
| `GET /breakdown/{template_id}?qty=` | Per-ingredient cost breakdown (optional `recipe_id=`). |
| `POST /pricing/compute`, `GET/PUT /pricing/margin/{template_id}` | Price calculator / reference margin. |

## `maker_api` — the cross-module public API (`app/modules/maker/maker_api.py`)

The only entry point other modules may use (the pattern in AGENTS.md
§Cross-Module). The methods also work when the maker module is disabled (empty
data / domain exceptions — a consumer does not have to guard every call):

| Method | Returns |
|---|---|
| `list_bom_lines_async(db, org_id, template_id)` | `list[BoMLine]` — the ingredients of the template's default recipe. |
| `list_template_ids_with_bom_async(db, org_id)` | `list[UUID]` — templates that have at least one BoM line. |
| `explode_bom_async(db, org_id, template_id, qty)` | `list[(child_template_id, effective_qty, unit)]` — a flat multi-level explosion. |
| `compute_total_cost_async(db, org_id, template_id, qty)` | Sum of shared estimated stock-unit cost × effective_qty. |
| `compute_unit_cost_async(db, org_id, template_id, planned_qty)` | Unit cost (0 with no ingredients). |
| `get_breakdown_async(db, org_id, template_id, qty)` | `CostBreakdownResponse` (read-only). |
| `complete_production_async(db, org_id, order_id, user, actual_qty=None)` | Executes a DRAFT (consumption → production → valuation). |
| `label_text_async(db, org_id, template_id, lang, lot_id=None)` | `str \| None` — a made product's ingredient list and allergens as a label prints them. A batch (`lot_id`) is read from the recipe of the runs that filed their output under it (`recipe_id`, through `output_lot_id` or a portion's `lot_name`), which need not be the default; a batch no run filled, or no batch, from the default recipe. None for a product nobody makes, for a batch runs of two recipes filled (no single list is its own), and while the module is off. The printing module's product and batch labels print it. |
| `list_work_items_async(db, org_id, query)` | `(list[WorkItemDTO], total)` — To do's provider for this module, registered with the warehouse module: draft runs planned for the day or earlier, and the counts owed for runs recorded after the fact. |

**What it uses from `recipes_api`:** `recipes_api.get_recipe_snapshot_async(db,
org_id, recipe_id)` returns a `RecipeSnapshot` (ingredients with `template_id`,
`quantity`, `uom_id`, `uom_symbol`), consumed by `POST /recipes/from-recipe`.
Org-scoped; `None` for a missing recipe, so the bridge degrades to a 404.
`recipes_api.infer_allergens(name)` and `recipes_api.ALLERGEN_KEYS` give the
label facts their suggestions and their closed list of keys; pure, so they
answer whether the recipes module is on.

## Module settings (`maker_module_settings`)

| Column | Default | Meaning |
|---|---|---|
| `reference_direction` | `MARGIN` | How `reference_price − unit_cost` reads (savings / margin) — a UI label. |
| `allow_overproduction` | `true` | Whether `actual > planned` is allowed on complete. |
| `availability_check_scope` | `GLOBAL` | `GLOBAL`/`PER_LOCATION` — the default context for availability checks. |
| `create_on_shortage_strategy` | `WARN` | `ALLOW`/`WARN`/`BLOCK` — what happens when a DRAFT is created despite shortages. |
| `labor_hourly_rate` | `0` | What an hour of the organization's own work costs; a batch's labour is its steps' minutes at this rate. `0` means an untimed or unpriced formula costs no labour. |

## Stock

The records are the stock (ADR-022): a run takes its ingredients off them
through `core_api.stock.take_from_the_records_async` — across every shelf (only
the run's output location under `PER_LOCATION`), in removal order
(`stock_consumption.py`) — which writes the records and one
movement per shelf and batch taken; the output is created with
`post_the_change=False` and posted through `core_api.stock.post_movement_async`.
The maker writes no movement of its own. `GET /api/v1/stats/reconciliation`
measures the records against the movement ledger and the cost layers.

## The recipes → maker bridge

1. On the culinary recipe screen: "Cook a batch for stock"
   (`CookForStockButton` + `CookForStockModal`) — shown only when the `maker`
   module is enabled (`isModuleEnabled`).
2. The modal asks for the output product (search), the scale (× recipe) and the
   output location; `planned_qty = servings × scale`.
3. `POST /maker/recipes/from-recipe` takes the snapshot (idempotent), then
   `POST /maker/production/orders` uses the snapshot's `recipe_id`.
4. The snapshot is **frozen**: changes to the culinary recipe never propagate.
   The recipe card shows "Based on a recipe (snapshot from {{date}})".

## Where-used

`GET /maker/bom/where-used?template_id=` plus the `WhereUsedSlot` component in
the `item_edit_extra` slot (the product/ingredient card in ItemEditModal) — the
recipes that use an ingredient, linked to their cards. Direct use only (one
JOIN, no recursion).
