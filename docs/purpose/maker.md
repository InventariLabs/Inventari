# Production (maker)

## Job
"Turn components into a finished thing, take the components out of stock, put the result in — and
know what the result cost."

## Whose job
Whoever runs the production, on the floor or in the kitchen. A manager defines the bills of
materials, because a BOM decides what gets consumed.

## Inside the boundary
The bill of materials for a product, a production run against it, the consumption of the components,
the output that lands in stock, and the cost rolled up from what was actually used plus the fixed
costs a bill of materials states per batch — labour, packaging, overhead, other. The production
recipe a bill of materials belongs to, and the day's runs in the warehouse's To do list.

## Outside the boundary
- The instruction a person follows while cooking, and whether it can be cooked today →
  **recipes**; a culinary recipe is read from there once, as a snapshot, when a production recipe is
  made from it
- What a run lacks → **shopping_lists**: the shortage is added to the list being filled, and
  nothing is ordered from here
- Stock itself → **Core — Inventory**; where things stand → **Core — Spaces**
- The record of what a run consumed and produced → the moves register in **Core — Inventory**,
  under the run's own reference; no warehouse document is written

## Own concepts / Borrowed
**Own:** bill of materials, production recipe (a product's variant, with its bill of materials),
component line, fixed cost line, production run, run status, cost rollup.
**Borrowed:** ProductTemplate, Item, StockLot, UoM (Inventory); StorageLocation (Spaces); the
number sequence a run is numbered from (Warehouse); the culinary recipe snapshot (recipes); the
shopping list a shortage is added to (shopping_lists).

## Deliberately not done
- **No scheduling and no capacity planning.** No MRP, no work centres, no routings, no shift
  calendar. A run happens when somebody starts it.
- **No time tracking.** Labour enters as a fixed amount per batch; nobody clocks hours or machine
  time against a run.
- **No quality records.** Passing or failing a batch is not modelled.
- **No forecasting of what to produce.** That question belongs to whoever is reading demand.

## Switched off
Stock stops changing by production; bills of materials become inert data. Recipes must still work
without it — cooking something for dinner does not require a production run.
