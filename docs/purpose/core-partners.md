# Core — Partners

## Job
"Keep the companies I deal with in one place, so that a document knows who it came from or who it
is for."

## Whose job
Whoever writes documents and purchase orders. Nobody opens this area for its own sake — it is
reached from the record that needs a counterparty.

## Inside the boundary
The identity of a company or person we deal with: name, kind (supplier, customer, both,
service provider, manufacturer, employee), whether it is a private person without a tax identifier,
tax identifier, addresses, contact details. Beside each partner, a summary read off the warehouse
documents written to it: how many (drafts left out), their total when they all share one currency (otherwise the screen says
there are several), and when the last one was. From the purchase orders it also counts how many name
the partner, whatever their status.

## Outside the boundary
- What was ordered from them → **purchase_orders**
- What actually arrived or left, and what it was worth → **warehouse** (the summary above is only
  a reading of it), **Core — Inventory**
- What a supplier offers a product for → **purchase_orders** (its price list)

## Own concepts / Borrowed
**Own:** Partner.
**Borrowed:** nothing. It is Core data presented as its own area, so that two modules do not each
keep their own list of the same companies.

## Deliberately not done
- **Not a CRM.** No opportunities, no pipeline, no contact timeline, nothing logged by hand. The
  last document date is a reading of the paper, not a history of the relationship.
- **No contracts.** Prices live with the order and the supplier's price list, not with the partner.
- **No per-partner permissions.**

## Switched off
Core data, so the records survive. The screens that read it disappear with the modules that need a
counterparty; nothing in Inventory or Spaces should break when they do.
