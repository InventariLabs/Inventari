# Warehouse

## Job
"Record what actually came in, went out or moved between places as a numbered event — so that months
later somebody can be shown the paper behind those movements."

## Whose job
Whoever handles goods writes, confirms and posts documents; cancelling or deleting one, closing or
reopening a period, changing how documents are set up (the profile, each type's settings, tax rates)
and adding or removing freight or duty on a receipt is a manager's by default. Accepting more than an
order allows past its tolerance is a separate permission, receive over tolerance, a manager's by
default and granted apart from write. A viewer reads them. The person writing one is usually standing
next to the goods, not at a desk.

## Inside the boundary
A numbered, registered event: a goods receipt, a dispatch, a transfer, a correction. Its lines, the
lots and quantities on them, the moment it is executed against stock, and its own printed form.
Whether an event needs somebody's consent before it takes effect is decided here.

The work on the floor that leads up to that moment is inside too: receiving and picking a document
line by line with a scanner, one picking session walking several dispatches in the order the
locations are numbered, the packages a picked dispatch is packed into with their slips and labels,
and the shipment its completion records — the carrier, the tracking number and when it left.

Also inside: putaway in a two-step receipt (the goods wait in a receiving area until one putaway task
per line moves them to a shelf; putaway rules rank shelves by the operator's rules, their capacity and
whether they hold one product only, and a product can have a home shelf that putaways teach it); the
stock a confirmed document reserves; backorders for what a dispatch could not ship; corrections,
reversals and returns, each a new document; freight, duty and insurance spread over an unposted
receipt's lines; imports from a spreadsheet, and opening stock as one draft receipt; tax rates and the
value columns of a document profile; the month-end period, which stops changes to documents dated in a
closed month; and the To do queue, read from the documents' own state, with the work other modules
register in it (such as counts due in stock takes).

## Outside the boundary
- What was *ordered*, and what is still outstanding → **purchase_orders** (a receipt is checked against
  its order line while that module is on)
- Who the counterparty is → **partners**
- What the goods are and how much there is now → **Core — Inventory**
- Where the places are → **Core — Spaces**
- *How* consent is obtained — stages, approvers, queue → **approvals**
- Every movement of stock, whatever caused it — a hand correction, cooking, production, a stock
  take → **Core — Inventory**, the moves register (Inventory → Stock movements). A document is one
  source among several there, and in most workspaces not the largest one.

## Own concepts / Borrowed
**Own:** Document, document line, document type, numbering series, document status, putaway rule,
picking and receiving session, package, shipment, inventory period, extra cost, tax rate, document
profile, and the To do work item.
**Borrowed:** Item, ProductTemplate, StockLot, UoM, Category, the stock reservation and cost layers
(Inventory); StorageLocation (Spaces); Partner (Partners); the approval workflow a document waits in
(approvals).

## Deliberately not done
- **Not an invoice.** A document records goods, not money owed: prices, tax and a value may sit on it
  when value tracking is on, but nothing turns it into a bill. No payment terms, no dunning, no
  balance with a partner.
- **No editing of an executed document.** A mistake is corrected by a new document, because the
  point of the module is that history can be shown.
- **No ad-hoc document types.** The set is closed; a new kind of event needs a decision, not a text
  field.
- **No screen for adjustments.** No screen writes an `ADJUSTMENT`: a closed stock take files its
  differences as one completed adjustment — signed deltas, the register's copy of a change the
  count already made, moving nothing itself. The API does accept one: `POST /documents` takes the
  type from anybody who may write documents, which is how an integration posts one. A hand correction moves stock through **Core — Inventory** and writes no document;
  a second screen for the same job would be a second answer to disagree with. An adjustment is not
  corrected: its lines are already differences, so a mistake in one is a new adjustment.
- **Not a carrier integration.** A shipment records what the carrier was handed and the number to
  follow it by; a tracking link is a web address with the number put in. Nothing here buys a
  carrier's label, compares rates, books a collection or reads the parcel's status back — that is
  work for a module that speaks one carrier's API.
- **No waves.** The dispatches a session picks together are the ones somebody ticked; nothing groups
  them by route, carrier or cut-off time, or releases them on a schedule.
- **No returns process.** A return is a document written against the one it reverses; there is no
  return authorisation for a customer and no inspection step that decides, product by product,
  whether the goods go back into stock.
- **No replenishment planning beyond one move.** The purchase orders module decides that a pick face
  is short and what a reserve shelf of the same warehouse can cover; this module posts that one
  transfer. What the reserve cannot cover is left to a purchase order (**purchase_orders**). Nothing
  balances stock between warehouses, groups the moves into a route, or schedules them.
- **No approval policy of its own.** It says *when* consent is needed; it never grows its own
  stages.

## Switched off
Stock still moves — Inventory does not depend on documents. While approvals is switched off, the
threshold and type rule that would hold a document for consent does not hold it: the approvals module
stands down and the operation proceeds. While another module that moves stock is on (maker,
purchase_orders or stock_takes — the household profile carries stock_takes), the moves register
still shows every movement and names what caused it (by hand, cooking, production, stock take);
with none of them on, it is not offered, and the product list is the whole record. What is lost is the numbered paper: no receipt
or dispatch to print, register or correct, and no counterparty on the movement. The household profile
runs this way on purpose.
