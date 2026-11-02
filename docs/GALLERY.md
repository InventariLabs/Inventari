# Gallery

Screens of the running application at twice the usual pixel density, from the
same two places as the [README's](../README.md#what-it-looks-like):

- **The warehouse** — Larkspur Trading Co., a fine-food wholesaler in
  Melbourne, set up through the onboarding wizard and its Saturday morning
  entered through the application's own API. The application stamps each
  entry with the moment it was made; the morning was entered in one sitting,
  so the stamps were afterwards moved, in order, onto the hours between 07:44
  and 10:35. Nothing else was changed outside the application.
- **Equipment, the kitchen, production and stock takes** — the demo seed,
  rebuilt with `make demo-reset` (see [DEMO.md](DEMO.md)) and shown as the
  [public demo](https://demo.inventari.app) shows it to every visitor, signed
  in as its administrator, with nothing edited.

The README shows the warehouse at work — the Start screen with its to-do list, picking, a shipped
delivery, occupancy, labels, statistics and the phone — and one screen each
of equipment, a recipe and a production run; this page shows the rest, module
by module.

These screens belong to applications built as Inventari modules. Kitchen,
equipment and production show different workflows using the shared core.
The warehouse shows the depth a module can reach, from receiving goods to
picking, packing and shipping them.

[Build your own application on Inventari](../README.md#build-on-inventari).

## Getting started

![The launcher: "Welcome, Olivia", the profile Equipment & Warehouse, and the wholesaler's modules grouped into essentials — inventory with one product running low — and business: equipment tracking, approvals, purchase orders, the warehouse with five things to do today and partners, above settings and the module store](images/launcher.webp)

**The launcher** — where signing in opens, unless the organization has
narrowed itself to a single module or you were sent to the sign-in page from
another address: the modules this organization has switched on, and what is
waiting in each.

## Warehouse

The Warehouse module owns the documents, sessions and packages shown here.
It uses Core for shared inventory operations and exposes public extension
points for a module with rules of its own, such as
[Lot certificates](../examples/lot_certificates/README.md).

![The documents list: two receipts from Highland Roasters and Olivar Groves and five deliveries to cafés, delis and grocers, each with its number, status, date, partner, location, the customer's order or the supplier's delivery note, its value and its lines; the two orders Priya Nair is picking show her name and their progress](images/documents.webp)

**Documents** — every receipt and delivery as a numbered document, with where
each one stands.

![Goods receipt IN/2026/001 from Highland Roasters into Goods In, completed: created at 07:45 and completed at 08:01 by Sam Okafor against invoice HR-20931; its three coffees, each with its quantity, price, batch and best-before date and the shelf it was put away on](images/receipt.webp)

**A receipt** — who received what, into which batch and onto which shelf.

![The Packing step of delivery OUT/2026/001 to Harbour Street Deli: everything picked is packed — the tomatoes and the spaghetti in package P1 weighing 25.8 kg, the olive oil in P2 weighing 5.1 kg — each with its packing slip and label, and below them the Shipping fields filled in with DHL and a tracking number above Complete dispatch](images/packing.webp)

**Packing** — the picked goods go into numbered packages, each with a slip and
a label carrying its code; the carrier and tracking number ride the
completion. The README shows the picking session before it and the same
delivery shipped after it, and the
[user guide](USER_GUIDE.md#1010-from-pick-to-parcel) walks the whole path.

## Inventory

![The product list of the wholesaler: balsamic vinegar, olive oils, coffees, mineral water and chocolate, each with its brand, barcode, code and category, the shelf it is on, its quantity and its best-before date](images/products.webp)

**Products** — what is in stock, where and until when.

## Purchase orders

![Purchase order PO/2026/001 to Ortolana Imports, confirmed: the order details and its notes, the status so far, and four lines of pasta, passata, rice and chocolate with their net, 10% tax and total in Australian dollars, none received yet](images/purchase-order.webp)

**A purchase order** — the order line by line, and how much of it has
arrived.

## Equipment

![The asset register sorted by warranty, soonest first: 77 assets, each with its serial number, location, who holds it, its warranty — expired, expiring or active, with the date — and its status](images/equipment-assets.webp)

**Assets** — serials, locations, warranties and who signed for what.

![The maintenance log of a UPS: a battery self-test and runtime check by Northgate IT Distribution, its cost of $120.00 and the next inspection due a year later](images/equipment-maintenance.webp)

**Maintenance** — every inspection and repair, its cost and the date of the next one.

![An attestation campaign, "Autumn equipment check": four people asked to confirm the equipment they hold — one confirmed, one disputed with the note "The hinge on the lid is cracked and the screen flickers", two still to answer](images/equipment-attestation.webp)

**Attestation** — ask everyone who holds equipment to confirm they still have
it, and hear back about what is broken.

## Kitchen

![The recipe list, nine recipes: the first three with their photographs, servings, cooking time and how many of their ingredients are on the shelf](images/recipes.webp)

**Recipes** — "I can cook" means every ingredient is on the shelf; the near
misses say what they are short of.

![This week's meal plan: breakfast and dinner over seven days, the meals still to cook marked Cook Now, and under the week each day's carbohydrates, protein, fat and calories for all the servings planned that day](images/meal-plan.webp)

**Meal planner** — a week of meals cooked from stock, with what each day adds
up to.

## Production

![The list of production runs: a completed batch of plum butter planned at 12 kg, with its cost of $95.36 and a margin of $109.90](images/production-runs.webp)

**Production runs** — what was made, what it cost and what it was worth.

![The cost of a plum butter BOM: $7.95 a unit against a reference price of $18.00, a margin of $10.05, and each ingredient's share of the cost](images/production-recipe-cost.webp)

**BOM cost** — the cost of a unit from the prices of its ingredients,
against a reference price.

The README shows the finished run in dark mode: what went in at its FIFO
cost, what came out, and every shelf it touched.

## Stock takes

![The report of the stock take "Dry Goods count": five items matched, one over and two under, each difference with its reason — damaged, an earlier count was wrong, found in another place](images/stock-take-report.webp)

**Stock take report** — the shelf against the system, and why each difference
happened.

## On a phone

![The wholesaler's documents on a phone: each with its number, status, date, partner, location and value, the orders being picked with their progress, above the warehouse's bottom bar of Start, Scan, History and More](images/mobile-documents.webp)

**Warehouse** — the same list, laid out for a phone.
