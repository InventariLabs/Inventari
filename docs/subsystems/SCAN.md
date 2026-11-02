# Scanning

Status: reference. Owner: backend (Core scan chain).

## What a scan answers

One question reaches the application from the floor — *what is this code?* —
through `GET /api/v1/labels/scan/{short_code}`, and through `POST /vision/extract`
for a barcode read off a photograph. The registry runs the code past the
registered scan providers in priority order and returns the first answer
that comes back; a provider that returns `None` has passed.

## The provider order

Lower priority runs first.

| Priority | Provider | Answers |
|---|---|---|
| 10 | `StorageScanProvider` (Core) | a shelf's own short code — the storage context |
| 20 | `LabelPoolScanProvider` (Core) | a printed label's short code |
| 30 | `DocumentScanProvider` (warehouse) | a document number printed on a PDF |
| 50 | `OFFScanProvider` (nutrition) | a package code the Open Food Facts table knows |
| 100 | `BarcodeScanProvider` (Core) | everything left: the organization's catalogue and stock |

The order is the point of the last two rows. `BarcodeScanProvider` is the
fallback: it is what a scan of anything *else* resolves to, including the
new-product form for a code of 8 to 14 digits nobody has (any other text
nobody has stays unrecognized and the endpoint answers 404). `OFFScanProvider` runs before it so
that a package code the organization has never seen is enriched from the
products database before that blank form appears — and never for a code the
organization does know (see below). A module that registers a provider of
its own picks its priority against this table and says in its own docs what
it answers.

## Identity: the catalogue row owns the code

A product's code belongs to its `ProductTemplate` — that is where a receipt
writes it, and a record created through the application stays bare whenever
its card holds the code. The record's own `barcode` column answers only for
records that have no card (or carry a unit's own tag): the precedence
`find_stock_row_async` applies to a delivery naming a product, which
`BarcodeScanProvider` follows too. Asking the item column "is this code
ours?" meant asking a column that is empty in practice — a product already
on the shelf scanned as "new product".

## Enrichment skips what the organization already has

A provider that answers from data *outside* the organization — the products
database is one — skips when the organization already has the product: a
catalogue row naming the code, or a record wearing it. Stock and the
organization's own product sheet are the answer to a scan of what is already
here; the outside data exists to fill in a *new* product's form. Scoping the
question to the caller's organization is part of the same rule: what a
stranger keeps on their shelf must not change what a scan tells you.

The products database is also never asked about a GS1
restricted-circulation number — prefixes 02, 04 and 20–29 on a GTIN-13,
and a GTIN-8 beginning with 0 or 2. Those numbers are assigned by the
company that prints them, not by GS1, so the same digits stand for
different goods at every shop and a shared catalogue has no answer for
one. `app.core.barcode.is_restricted_circulation` owns the rule, and
`OpenFoodFactsService.fetch_product` refuses such a code for every caller:
the scan chain, the product form's barcode lookup and a document line's
scan. The rule is read through the padding a scan is stored with, so it is
the mark that matters, not the representation: an EAN-8 `20000004` reaches
the lookup as `0000020000004`, and a GTIN-14 carries the same marks one
place to the right behind its indicator digit — `00000020000004` and
`00200000000219` stay restricted too. A scan of one the organization does
not hold falls through to `BarcodeScanProvider` and gets the plain
new-product form; one it does hold answers from its own stock and catalogue
like any other code.
