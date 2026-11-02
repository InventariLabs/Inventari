# Core — Inventory

## Job
"Know what I have, how much of it is left, and whether it is still good."

## Whose job
Everyone who touches stock: the person adding a thing with a phone in one hand, the person looking
for one, the person writing it off. No role is excluded — a viewer reads the same lists.

## Inside the boundary
What a thing is (product, category, unit of measure), how much of it there is, and how that changes
over its life — quantity, lots, expiry, condition. The authoritative stock figure per product,
location, lot and owner, and the moves register: every movement of stock with what caused it, so
the question "why is the number what it is" has an answer whichever modules are on. How much of
that figure documents have already promised, and so what is still available. A product's minimum
quantity, and the one rule for "running low" that every screen reads.

## Outside the boundary
- Where a thing physically stands, and what kind of place that is → **Core — Spaces**
- How it arrived or left as a recorded, numbered event → **warehouse**
- What it costs to buy and from whom → **purchase_orders**, **partners** (a record keeps only the
  price it came in at and the partner it came from)
- What it can be turned into → **recipes**, **maker**
- The lifecycle of one identifiable asset — who holds it, when it is serviced → **equipment**

## Own concepts / Borrowed
**Own:** Item, Category, ProductTemplate, UoM, StockLot, expiry date (the stock itself is
the records — ADR-022), stock reservation, minimum quantity.
**Borrowed:** StorageLocation (Spaces). Every other noun on an inventory screen that is not in the
list above comes from a module and has to earn its place.

## Deliberately not done
- **No vertical-specific field.** The Core serves food, equipment and warehouses equally; a column
  only one of them would ever fill belongs in `meta_data` or a module table (`backend/AGENTS.md` §4,
  the 3-Vertical Test). `serial_number` and `expiry_date` are grandfathered exceptions, not a precedent.
- **No reordering.** Inventory says that something is running low; putting it on a list or an
  order is **shopping_lists**' and **purchase_orders**' job.
- **No accounting.** Valuation layers exist for stock correctness, not to be presented as ledgers.
- **No workflow.** Inventory records state; it does not ask anybody for approval.

## Switched off
Cannot be. It is the Core: every module that stores anything depends on it.
