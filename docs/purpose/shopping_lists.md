# Shopping Lists

## Job
"Know what to buy before I get to the shop — including the things I would have forgotten."

## Whose job
Whoever does the shopping. The list is read on a phone, in a shop, usually one-handed.

## Inside the boundary
The lists themselves and what is on them, added by hand, suggested from what has run low, what is
used up often, or what has expired or is about to, and ticking things off as they are bought.
Recipes and production runs also put entries on the active list. An entry may carry an estimated
price — typed in, or copied from a suggestion — so the shopper knows roughly what a thing costs.

## Outside the boundary
- Ordering from a supplier, with an expected delivery → **purchase_orders** (a list can be turned
  into a draft order there)
- Bringing what was bought into stock → **warehouse**, **Core — Inventory**
- What a recipe would need → **recipes** (which contributes entries; it does not own the list)
- What a production run lacks → **maker** (which adds its shortfall through this module's public
  API; it does not own the list)

## Own concepts / Borrowed
**Own:** ShoppingList, list entry, suggestion.
**Borrowed:** ProductTemplate, Item, Category, UoM and the consumption history (Inventory); StorageLocation
for expiry suggestions (Spaces).

## Deliberately not done
- **No budget and no totals.** An entry's estimated price is a hint for that one entry; a list is
  never summed, compared with a budget or treated as a basket.
- **No shops.** No vendor comparison, no branch stock, no delivery integration.
- **No automatic buying.** A suggestion is offered to a person; nothing leaves this module on its
  own.

## Switched off
Nothing depends on the lists existing. Recipes and production runs reach them only through this
module's public API: recipes keeps working without them, and a production run's add-shortages action
is refused (403) while they are off. What is lost is the prompt — no other screen may keep suggesting
that something is running low as though the list were still there to catch it.
