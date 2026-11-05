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
| `maker_bom_lines` | BoM line: ingredient units per batch (`qty_per_batch`), `uom_id`, `yield_loss_pct`. Unique `(recipe_id, child_template_id)`. `parent_template_id` denormalises `recipe.output_template_id` (the invariant is enforced on every write). |
| `maker_recipe_cost_lines` | Fixed batch costs (labour, packaging, overhead). |
| `maker_production_orders` | Production order: DRAFT → COMPLETED / CANCELLED, and COMPLETED → REVERSED when a finished run is taken back. Holds a snapshot of the financial result. |
| `maker_production_order_lines` | Per-ingredient consumption audit recorded on completion. |
| `maker_module_settings` | The `*_module_settings` pattern (org_id PK, typed columns). |

## Batch math

```
batches = planned_qty / recipe.batch_yield_qty
effective_qty(line) = batches * qty_per_batch * (1 + yield_loss_pct / 100)
```

- **Leaf** — an ingredient with no default recipe → drawn from the stock
  records across every location (`core_api.stock.take_from_the_records_async`);
  under `availability_check_scope=PER_LOCATION` only from the run's output
  location, the set the availability check judged.
- **Sub-assembly** — an ingredient with a default recipe → exploded recursively
  (virtual, no WIP), depth-limited (`_MAX_DEPTH = 10`).
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
`date.today()`. The run number is the exception: it comes from the document
numbering register (`PR` type, shape `PR/{YEAR}/…` unless the organization
changed it), which reads its year in UTC, not on this clock. `completed_at`
itself stays a UTC instant; the clock decides how it is read, not how it is
stored. See TECHNICAL_DECISIONS.md §19.

## HTTP API (`/api/v1/maker/*` — gated by `require_module('maker')`)

### Recipes and catalogue

| Endpoint | Description |
|---|---|
| `GET /recipes` | Card catalogue (search/sort/pagination; `output_template_id=` narrows to one product's recipes). `unit_cost` = total cost / quantity of the most recent COMPLETED order of that recipe (one batched query, no N+1), with `uncosted_ingredients`; a recipe never run carries `estimated_unit_cost` instead; also `stock_qty`, `last_produced_at`, `ingredient_count`, `result`. |
| `GET /recipes/{id}` | Detail: lines + fixed costs + `estimated_unit_cost` (shared Core estimate: layer-average rate, then a usable supplier offer) + `source_recipe_id`/`source_snapshot_at`. |
| `POST /recipes` | Create (a template's first recipe becomes the default automatically). `source_recipe_id` stamps `source_snapshot_at`. |
| `POST /recipes/from-recipe` | **The recipes→maker bridge**: snapshots a culinary recipe into a maker recipe plus BoM lines built from ingredients that carry a `template_id` (free-text ingredients are skipped). Idempotent per (output_template_id, source_recipe_id). A culinary recipe that does not exist in the organization returns a plain 404. |
| `PATCH/DELETE /recipes/{id}` | Update / delete (deleting the default promotes the oldest remaining recipe; a recipe that a production order references cannot be deleted, 409). |
| `POST /recipes/{id}/bom-lines` | Add an ingredient to that recipe (the parent comes from the recipe; a duplicate returns 409, a self-reference 400). |
| `PATCH/DELETE /recipes/{id}/bom-lines[/{line_id}]` | Edit a line in place (qty/uom/yield_loss/notes) / remove it. |
| `POST/PATCH/DELETE /recipes/{id}/cost-lines[/{line_id}]` | Fixed costs. |
| `GET /recipes/{id}/availability?batches=&location_id=` | Per-ingredient {needed, available, shortage, uom, convertible} plus `max_batches`. Honours `availability_check_scope` (GLOBAL/PER_LOCATION); `location_id` overrides it. |

### BoM (legacy adapters and reverse lookup)

| Endpoint | Description |
|---|---|
| `GET /bom/parents` | Every template that has BoM lines (parent + line_count). |
| `GET /bom/summary?template_ids=` | Batched: has-BoM + line_count + `default_recipe_id` (badges on product lists). |
| `GET /bom/template-ids` | Every template in the organization that has at least one BoM line — feeds the "BOM" filter on the virtualised product list, which cannot decide row by row from data it has not fetched. |
| `GET /bom/where-used?template_id=` | The reverse edge — recipes that use a template (JOIN lines→recipes, direct use only, org-scoped, cycles have no effect). |
| `GET /bom/{template_id}` | Lines of every recipe of the product, not only the default one (adapter; the same lines feed `GET /bom/tree/{template_id}`). |
| `GET /bom/{template_id}/cost-estimate` | Cost of one unit by the default recipe (shared Core estimated stock-unit costs); `qty=` and `recipe_id=` ask for a batch or a variant. |
| `GET /bom/tree/{template_id}` | Recursive tree (BomTreeEditor). |
| `POST /bom/{line_id}/move` / `DELETE /bom/{line_id}` | Move a line under a different parent / delete a line. |

`POST /bom` and `DELETE /bom/parent/{template_id}` were removed: they addressed
a *product* and always landed on its default recipe, so with two recipes per
product the write went somewhere other than where the operator was looking.
Line writes go through `POST /recipes/{id}/bom-lines`, and the `/maker/bom`
screen is gone (the route redirects to the catalogue).

### Production orders

| Endpoint | Description |
|---|---|
| `GET /production/orders` | List (status/output/date-range filters, sort, pagination). Each DRAFT row carries `shortage_count`: how many ingredients the planned consumption cannot cover, counted the way completion refuses — the shared `_shortages_from_needs` verdict at the order's own output location, unmeasurable ingredients included. `null` past the draft, and `null` for a draft without a recipe (nothing to forecast from) — null is "no answer", not a clean zero. Deliberately **not** a filter dimension: the count is computed after the page is cut, so filtering on it would break skip/total semantics; moving it into the query layer is a separate, conscious decision. |
| `POST /production/orders` | DRAFT. Takes a `recipe_id`, or looks up the default by `output_template_id` (no recipe → 400). Honours `create_on_shortage_strategy`: ALLOW / WARN (422 plus the shortage list; re-POST with `confirm_shortage=true`) / BLOCK (422, no DRAFT created). |
| `POST /production/orders/made` | Record a run that already happened: created and completed in one step (`planned_qty` is what came out). Needs `items:write`. An ingredient the records hold too little of does not refuse the run: what they hold is consumed, the rest becomes the line's `shortfall_qty`, and the ingredient shows up as a count in To do (with `stock_takes` enabled). The shortage strategy is not asked. 422 `insufficient_stock` only for a line whose unit cannot be compared with its stock, 422 `empty_bom` for a recipe with no ingredients. |
| `POST /production/orders/preview` | Cost dry-run, no stock mutation. |
| `POST /production/orders/shortages/shopping-list` | Puts what a planned run lacks on the active shopping list (needs `shopping_lists:write`); an ingredient already on the list is not added twice. |
| `GET/PATCH /production/orders/{id}` | Detail (with the result snapshot) / update a DRAFT. Every door that answers with a single order — create, update, duplicate and the read — builds it through one constructor, so a draft carries the same `shortage_count` and `shortage_items` whichever way it came. A draft also carries `shortage_items` — the refusal's own list, the rows behind `shortage_count` — so the page marks every ingredient completion would refuse on instead of recomputing a forecast that could disagree. |
| `POST /production/orders/{id}/complete` | Consumes planned (drawn from the stock records), outputs actual, values the batch, writes `unit_cost_snapshot`/`reference_price_snapshot`/`result_per_unit`/`result_per_batch`. Shortages → 422 with an actionable list (`insufficient_stock`); a recipe with no ingredients → 422 `empty_bom`. Needs `items:write`. |
| `POST /production/orders/{id}/cancel` | Cancel a DRAFT (optional `reason`, stored as `cancel_reason`). Needs `maker:manage`. |
| `POST /production/orders/{id}/reverse` | Take a COMPLETED run back: the ingredients return to the records and batches they were taken from, the output leaves its location, and the run is marked REVERSED (it stays on record; the movements of the way back name it). Refused (400) for a run that is not completed or whose output has since left its shelf. Needs `maker:manage` and `items:write`. |
| `POST /production/orders/{id}/duplicate` | Duplicate as DRAFT (copies `recipe_id`). |
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

### Other

| Endpoint | Description |
|---|---|
| `GET /settings` / `PATCH /settings` | `maker_module_settings` (reference, overproduction, availability scope, shortage strategy). |
| `GET /breakdown/{template_id}?qty=` | Per-ingredient cost breakdown (optional `recipe_id=`). |
| `POST /pricing/compute`, `GET/PUT /pricing/margin/{template_id}` | Price calculator / reference margin. |

## `maker_api` — the cross-module public API (`app/modules/maker/maker_api.py`)

The only entry point other modules may use (the pattern in AGENTS.md
§Cross-Module). The methods also work when the maker module is disabled (empty
data / domain exceptions — a consumer does not have to guard every call):

| Method | Returns |
|---|---|
| `list_bom_lines_async(db, org_id, template_id)` | `list[BoMLine]` (ingredients). |
| `list_template_ids_with_bom_async(db, org_id)` | `list[UUID]` — templates that have at least one BoM line. |
| `explode_bom_async(db, org_id, template_id, qty)` | `list[(child_template_id, effective_qty, unit)]` — a flat multi-level explosion. |
| `compute_total_cost_async(db, org_id, template_id, qty)` | Sum of shared estimated stock-unit cost × effective_qty. |
| `compute_unit_cost_async(db, org_id, template_id, planned_qty)` | Unit cost (0 with no ingredients). |
| `get_breakdown_async(db, org_id, template_id, qty)` | `CostBreakdownResponse` (read-only). |
| `complete_production_async(db, org_id, order_id, user, actual_qty=None)` | Executes a DRAFT (consumption → production → valuation). |
| `list_work_items_async(db, org_id, query)` | `(list[WorkItemDTO], total)` — To do's provider for this module, registered with the warehouse module: draft runs planned for the day or earlier, and the counts owed for runs recorded after the fact. |

**What it uses from `recipes_api`:** `recipes_api.get_recipe_snapshot_async(db,
org_id, recipe_id)` returns a `RecipeSnapshot` (ingredients with `template_id`,
`quantity`, `uom_id`, `uom_symbol`), consumed by `POST /recipes/from-recipe`.
Org-scoped; `None` for a missing recipe, so the bridge degrades to a 404.

## Module settings (`maker_module_settings`)

| Column | Default | Meaning |
|---|---|---|
| `reference_direction` | `MARGIN` | How `reference_price − unit_cost` reads (savings / margin) — a UI label. |
| `allow_overproduction` | `true` | Whether `actual > planned` is allowed on complete. |
| `availability_check_scope` | `GLOBAL` | `GLOBAL`/`PER_LOCATION` — the default context for availability checks. |
| `create_on_shortage_strategy` | `WARN` | `ALLOW`/`WARN`/`BLOCK` — what happens when a DRAFT is created despite shortages. |

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
