# Purchase Orders

## Job
"Order what we need from a supplier, and know at a glance what is still on its way."

## Whose job
Whoever buys raises, confirms and receives against an order; cancelling one is a manager's by
default; a viewer reads.

## Inside the boundary
An order placed with a supplier: its lines, what was agreed, when it is expected, and how much of
each line is still outstanding as deliveries arrive against it. What each supplier offers a product
for — a price, a minimum quantity, the dates it holds — so the cheapest current offer can be
compared and proposed. When a location runs low: per-location reorder rules (minimum, maximum,
safety stock, preferred supplier), the alerts they raise, and turning those alerts into draft
orders grouped by supplier. An order can be sent to its supplier by mail with the order as a PDF, and
the supplier offers also price other modules' cost estimates (recipes).

## Outside the boundary
- Goods physically arriving, and the stock that follows → **warehouse**
- The supplier's identity → **partners**
- Writing down a one-off need for later → **shopping_lists**; trends and forecasts → **stats**
- Consent before an order goes out → **approvals**

## Own concepts / Borrowed
**Own:** PurchaseOrder, order line, order status, expected date, outstanding quantity, supplier
price list entry, reorder rule, replenishment alert.
**Borrowed:** Partner (Partners); ProductTemplate, UoM (Inventory); the receipt that closes a line
(Warehouse).

## Deliberately not done
- **No invoice matching and no payment.** Whether the supplier has been paid is not this module's
  question.
- **No quotations or tenders.** A supplier's price is entered, not requested and negotiated
  here; the price on a line is what was agreed for that order.
- **No supplier performance scoring.** Judging a partner is a relationship, and partners are
  addressees here, not relationships.

## Switched off
Receiving goods still works — a receipt does not need an order behind it. What is lost is knowing
what is on its way, so nothing elsewhere may present "expected" quantities as if they were still
being tracked.
