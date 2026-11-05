# ADR-015: Unit Weight Belongs to the Product Template, Line Weight Is Computed

## Status

Accepted — 2026-08-15

## Context

`Item.weight` was a `Numeric(10, 2)` column with no comment and, more
importantly, **no unit**. Two code paths disagreed about what it held:

- the **write** path treated it as the weight of the whole line
  (`per_piece_kg × quantity`);
- the **read** path treated it as the weight of a single piece (multiplying by
  1000 and putting the result in a "weight per piece" field).

Loading an item and saving it unchanged therefore multiplied the stored value
by the quantity every time. A 500 g product became 250 kg after one save and
125 000 kg after the next.

Three findings decided the direction:

1. **The column was empty.** In the databases examined when this was
   decided, no item had a value in `Item.weight`. The form wrote it; nothing
   read it back for any purpose that mattered.
2. **It drove no logic.** Its only consumers were the CSV export, the scan
   result, and serialisation. No calculation, no report, no alert.
3. **A better model of the same thing already existed and worked.**
   `ProductTemplate.weight_value` + `weight_uom_id` hold a value **together
   with its unit**, and their meaning is unambiguous throughout the code: the
   weight of a single unit or full pack. Recipe nutrition multiplies it by a
   quantity to get grams; opened-pack detection compares against it and checks
   UoM category compatibility before doing so.

## Decision

**The weight of one unit lives on `ProductTemplate` (`weight_value` +
`weight_uom_id`). The weight of a stock line is computed, and the
`Item.weight` column is gone.**

- `app.services.items.weight.total_weight(quantity, weight_value, weight_uom_factor)`
  is the one definition for a line counted in pieces: quantity × unit weight,
  converted through the UoM factor, expressed in kilograms (or litres for
  volume units). A line counted in a weight or volume unit is its own weight
  (`quantity_as_weight`, same module).
- `Item.total_weight` exposes it on the model. The API keeps serving the field
  as `weight` on item responses, so consumers see the same total they saw
  before — it is now read-only.
- Item create/update accept `weight_value` and `weight_uom_id` and write them
  to the item's **org-owned** template. A global template
  (`organization_id IS NULL`) is shared and is never written to.
- The archived migration `itemweight01` drops the column, with a working downgrade that
  restores its shape (not its contents — there were none).

## Rationale

The weight of one piece is an attribute of the **product**, not of a row of
stock: the same 500 g milk in three locations does not have three different
unit weights. Copying it onto every `Item` is a denormalisation that must
eventually drift — and it did, which is exactly the defect above.

A stored total would need syncing on every quantity change, i.e. the problem
[ADR-004](ADR-004-stockquant-source-of-truth.md) describes for `Item.quantity`
versus `StockQuant`, for a value nothing computes with. Computing on read
costs one multiplication.

The unit also stops being guessed. The old column had none, which is why the
form hardcoded a ×1000 on read and a ÷1000 on write; `weight_uom_id` records
it next to the value.

## Consequences

**Good**

- Loading and saving an item cannot change its weight — there is nothing to
  round-trip.
- The unit is recorded rather than assumed, so non-metric units (oz, lb, fl
  oz) work instead of silently falling into a "per piece" branch.
- One product's unit weight is edited in one place and every line of that
  product reflects it.

**Costs**

- `ProductTemplate.weight_uom` is eager-loaded (`lazy='selectin'`), because
  the total is computed during response serialisation, where a lazy load runs
  outside the async greenlet. That is one extra batched SELECT on item
  queries.
- Items on a **global** template cannot record a unit weight; the write is a
  no-op by design. Such an item needs its own org template first.
- Anyone with data in `items.weight` on another environment must capture it
  before upgrading. The downgrade restores the column, not its values.

## Alternatives considered

**Keep the column, fix the two paths to agree.** Cheaper, and it was the first
instinct. Rejected: it keeps a unitless number denormalised onto every row,
so the same class of drift stays possible, and it leaves two places where a
unit weight can be recorded.

**Store the total and sync it.** Rejected for the reason ADR-004 gives — a
cache needs a synchroniser on every write path, and this one has no reader
that would justify the maintenance.
