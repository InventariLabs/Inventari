# Units of Measure Subsystem

- **Service**: `app.services.uom_service` (exposed to modules via `core_api.uoms`)
- **Models**: `Uom`, `UomCategory` (`app/models/uom.py`)
- **Seed data**: `app/seed_profiles/_uom_data.py` — one catalogue for every path that seeds it

## The model (Odoo-style)

A unit's `factor` is relative to its **category's reference unit** (the
one with `is_reference=true`): grams for Weight, millilitres for Volume,
pieces for Unit, centimetres for Length. Conversions are a ratio within
one category; cross-category conversion **refuses** rather than guesses
— pieces do not become kilograms until something (what one piece weighs or
holds, on the product card) bridges them.

Bulk packaging (pack/can/bottle/box/bag) sits in its own single-unit
categories, so pack↔pcs refuses too: the packaging-to-contents ratio
belongs to the product, not the unit table.

## The one conversion mechanism

`uom_service.convert_quantity` is the one conversion between two units. (Weight
and volume totals read `factor` directly to reach kilograms and litres, see
`Item.total_weight`.) It
returns `(converted, ok)` and `ok=False` covers: no unit, different
categories, zero target factor. Consumers:

- `to_stock_uom_async` — expresses a quantity in the product's stock
  unit; **raises** (naming both symbols) instead of guessing. A quant
  and a movement carry a number and no unit, so whose unit it is must
  never depend on whichever write got there last.
- `to_canonical_measure_async` — restates a quantity in its category's
  reference unit (`(28.3495, 'g')` for one ounce). This is the one
  doorway for "how many grams is this"; nutrition's private tables (an
  ounce of 28.35 against the catalogue's 28.3495) are gone.
- `convert_qty_for_template` (recipes) — the availability/cost answer
  that bridges count↔mass through what one piece weighs or holds on the
  template, and says
  `None` when the measures don't meet. An impossible conversion is a
  refusal, never the same number back.
- `keep_in_card_unit_async` (`services/items/_unit_choice.py`) — a record
  is kept in its card's unit. See below.

## A record is kept in its card's unit

The quant, the movement, the cost layer and the records' view
(`stock_quants_from_records`) carry a number and no unit, and the view sums
`items.quantity` as it stands. So a record's quantity is always in its
card's unit — the rule Odoo, ERPNext, SAP and Dynamics keep: one stock unit
per product, every entry converted into it on the way in, nothing converted
on the way out.

A record may still be *entered* in another unit, through the confirmation
(`unit_confirmed_over_template`) the create, edit, bulk-edit, scan and
import doors carry. The confirmation guards the entry — a picker left on
grams from the previous product would turn two kilograms into two grams —
and its effect is a restatement, not a relabel: `keep_in_card_unit_async`
converts the quantity into the card's unit (three places, half up), the unit
price the other way so the value holds, and sets the card's unit. The
record's history keeps what was typed (`entered_quantity` beside
`kept_quantity`).

Within a category the ratio is the units' own. Between a piece and a weight
or a volume it is what one piece measures, from the card's `weight_value` /
`volume_value` (ADR-015): three 250 g loaves on a card kept in kilograms are
0.75 kg, a kilo of 250 g apples on a card that counts them is four. A pack is
not a piece — nothing says how many pieces it holds — and anything else that
does not convert is refused by name (`item_unit_not_convertible_to_card`).

### A partly used package is read in the card's measure

A record in pieces that is partly used (0.75 pcs) is stock, and it stays a
number of pieces everywhere the quantities are summed. What the screen says
about it is a display rule, `partialPackage` in the frontend: where the card
records what one piece weighs or holds, the stock list, the record's detail
view, the scan sheet, picking candidates and the dashboard's attention list
read "1.5 kg left of 2 kg" (a
total, "5 kg (2 kg each)", above one piece). A record in a pack or a measured
unit, a whole number of pieces and a card with no weight or volume read as
they always did. Picking candidates and the scan payload carry the card's
measure so the client does not look it up a second time.

### Using a package partially opens one unit

`POST /items/{id}/use-partially` (the scan sheet's "Use partially") answers
what is LEFT of a package, not what was used, so pressing it twice cannot take
the amount off twice. One unit of a record that holds several is split off as a
record of its own — the same split a partial transfer makes, with no movement
because the shelf's stock does not change — and the remainder is restated in the
card's unit through what one piece weighs or holds (1.5 kg left of a 2 kg bag is
0.75 pcs). The opening time goes into the record's `meta_data.opened.at`, an
`OPENED` entry into its history, and the amount used is an ordinary `USED`
movement. A product counted in packs can only be marked opened (`left` absent)
or finished (`left` 0). A piece card that does not say what a piece holds takes
`left` only in pieces; a weight or volume is refused by name. Goods kept in a
measured unit have no package to open.

### Cooking prefers the open pack and opens the sealed one it takes from

The mark above (`meta_data.opened.at`, read through `app/core/open_package.py`) is
what picking calls an opened pack. A record without the mark is judged the way it
was before the mark existed: its quantity below the card's full-pack weight, in
the same unit. Recipe picking orders stock by date first and, on the same date,
puts an open pack before a sealed one and only then the larger quantity. When a
sealed pack expires EARLIER than the open one, the scan does not pick for the
cook: the candidates list carries `opened` and `opened_at` beside their dates, the
earlier date is the recommended one, and the cook chooses. Taking part of one unit
from a sealed record (`core_api.items.open_to_take_part_async`) opens it the same
way Use partially does before the amount leaves, so the opening time is recorded
and the sealed packs beside it stay sealed; a pick of only whole units opens
nothing.

### A use-by date after opening shortens the shelf life

Opening may carry a use-by date (`use_by` on `POST /items/{id}/use-partially`,
edited or cleared later with `PUT /items/{id}/use-by`, opened records only). It
is stored in `meta_data.opened.use_by`, beside the opening time and never over
`expiry_date`, which stays the batch's date. The date a record is judged by is
the **effective expiry**, the earlier of the two: `Item.effective_expiry_date`
(a hybrid property, `least(expiry_date, use_by)` in SQL, `effective_expiry` in
`app/core/open_package.py` for code that holds a DTO). The expired and
expiring-soon predicates (`services/items/expiry.py`), the overview and
dashboard counts, the smart alerts, the shopping suggestions, the storage and
FEFO listings, the scan sheet and cooking's FEFO order all read it. A record
with no use-by is judged by its batch date alone, as before. The item response
carries `use_by_date` and `effective_expiry_date`.

## Precision

- Quantity columns are `Numeric(12,3)` (items and quants agree).
- Incoming quantities are quantized at schema entry to 3 dp, HALF_UP —
  Postgres would otherwise round silently.
- Each unit carries its own `rounding` step (whole numbers for counted
  units, 0.01/0.001 for measured ones), enforced by
  `validate_quantity_precision_async`. The refusal is a catalogue sentence
  (`uom_quantity_requires_whole_number`,
  `uom_quantity_too_many_decimal_places`), so it answers in the request's
  language and calls the unit by the label the reader picked — "szt." in a
  Polish session, not the bare symbol — and states the quantity at its own
  scale, the same on every door. Picking may legitimately consume
  a fraction of a counted unit (an opened package is stock too), so the
  rounding rule gates what a person types into the quantity, consume and
  discard doors, not the picking paths that take part of a package.

### A computed quantity takes the step of its unit

Everything above is about a number a person types. A number the app
*computes* — a recipe scaled to other servings, a shopping line
aggregated across two plans, a checklist row — used to be rounded to a
hard three decimal places, in nine places across the recipe module. That
step is not a constant: it is `Uom.rounding`, and a unit counted in ones
was accepting 0.333 of itself.

Ask through the facade; the answer is floored at the quantity columns'
own scale, because a finer step is rounded away by Postgres anyway:

- `core_api.uoms.quantity_step(uom)` — the step, `Decimal('0.001')` when
  no unit is named.
- `core_api.uoms.quantize(qty, uom)` — the **nearest** step. What was
  scanned, moved or already picked is a reading, and a reading rounds
  both ways.
- `core_api.uoms.round_up(qty, uom)` — the **next** step at or above.
  What must be bought, picked or had is a requirement, and a requirement
  rounded to the nearest step can round to nothing: a third of an egg
  told the shopping list to buy none.

One deliberate exception, and it is the rule above restated: the amount
picking takes off a shelf (`_picking_uom_bridge`) is **not** put on the
item unit's step. An opened package holds a fraction of a piece, so 500 g
taken from a piece weighing a kilogram is half of it, and rounding that
up would take twice what the recipe asked. It passes `uom=None`, which
asks only for the column scale.

### Only what shares a measure is added up

Two quantities may be summed when they answer the same
`to_canonical_measure_async` symbol — `kg` and `g` both answer `g`, so a
product asked for in both buys once. A unit alone in its family
(a piece, a pack, a bottle) answers only for itself: a pack is not a
share of a piece. The meal-plan shopping list keys its aggregation on
that answer, so an unconvertible pair becomes two lines rather than one
number in no unit at all — it used to add 500 g and 2 pcs into "502".

## Time

Storage timestamps are UTC and timezone-aware; the frontend renders
locally through `Intl`.
