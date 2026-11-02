# ADR-017: Fiscal Features Are Country Packs, Not Core

## Status

Accepted — 2026-08-30; amended 2026-10-31: the synchronous document seam
decision 2 counted on does not exist yet (see the update there).

## Context

Warehouse documents carry value. A goods receipt has a price, that price feeds
AVCO valuation (`StockValuationLayer`), and valuation is one step away from a
balance sheet. Every system that issues valued documents receives the same
sequence of requests afterwards: supplier invoices, VAT, cost of goods sold,
period closing. This is how inventory tools become ERPs — rarely by deciding
to, usually one customer request at a time.

Two constraints make that drift more expensive than it first appears.

**1. Fiscal features are per-country.** Each country runs its own mandatory
e-invoicing system on its own schedule — KSeF in Poland, Factur-X/PDP in
France, EN 16931 in Germany, Veri\*factu and Crea y Crece in Spain — with the
EU's ViDA programme converging them only towards the end of the decade.
Chart-of-accounts conventions, VAT rules and statutory reporting differ per
country and change as legislation changes. Work here is never done once; it is
done per country and maintained indefinitely.

**2. Some regimes require certified, tamper-evident software, which a
self-hosted AGPL build cannot be.** Spain's Veri\*factu mandates certified
invoicing software reporting in real time to the tax authority; Portugal, Italy
and Hungary certify the software itself, not only the document format. A
program its operator can recompile cannot carry such a certification. This is a
categorical obstacle, not a budget one.

Against that, documents deliver most of their value with no fiscal dimension at
all. A dispatch note the warehouse signs, a receipt checked against a purchase
order, a transfer between sites — these involve no tax authority and behave
identically in every country.

## Decision

**The core stays country-neutral. Anything touching taxes, invoices or
statutory reporting lives outside it.**

1. **Internal warehouse documents are core product.** Receipt, dispatch,
   transfer, correction and write-off keep neutral type codes (`IN`, `OUT`,
   `INT`, …); numbering defaults to each type's short code (`IN`, `OUT`, `IR`, …); country flavour is a
   selectable print layout plus organization-level type labels.
2. **Fiscal features are modules**, written by whoever knows that country's
   rules, using the extension points from ADR-007. A synchronous interceptor
   can register a document with a national system at confirmation time and
   refuse the document if registration fails; `DocumentCompletedPayload` and
   `DocumentCancelledPayload` cover after-the-fact needs.

   > **Update 2026-10-31:** that synchronous document seam was assumed, not
   > built. Core interceptors cover items, storage locations and categories
   > only (ADR-007); a confirmed document publishes `document.confirmed`
   > after its status changes, and no subscriber can refuse it. A fiscal
   > module that must refuse a document at confirmation needs that hook added
   > to the warehouse module first — the case the second risk below
   > describes.
3. **Where a regime requires certified software, that capability belongs to a
   commercially supported edition.** Statutory certification requires a vendor
   that assumes liability for the certified build; a modifiable self-hosted
   build cannot legally carry the certification. The feature is not withheld —
   the certification cannot exist without the vendor.
4. **A general ledger stays out of scope.** Its real cost is not the
   double-entry mechanics — those are small, and `StockValuationLayer` already
   produces half of a journal entry — but the country packs, the statutory
   reporting, and earning the trust of an accountant who already has a system
   they rely on.

### The multiplier rule

> **Country-specific work multiplies by the number of countries. Neutral work
> costs once.**

Apply this before adding anything that names a country, a tax, or a legally
defined document type. It is why the warehouse module is a neutral engine with
a thin per-country layer on top, and that pattern is the rule rather than an
accident of how it was built.

### Alternatives considered

| Option                                                           | Why rejected                                                                                                                               |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Build accounting into the core                                   | Multiplies per jurisdiction, requires permanent legislative maintenance, and competes with the system the user's accountant already trusts |
| Ship one country's fiscal support (the maintainer's own)         | Makes a country-neutral product look regional, and sets a precedent other countries will expect                                            |
| Refuse fiscal integration entirely                               | Users do need invoices; refusing the seam blocks a legitimate need instead of routing it to a module                                       |
| Take the valuable parts and stop before the ledger, case by case | This is precisely the drift this ADR exists to prevent — "stop somewhere" without a stated rule stops nowhere                              |

## Consequences

**Positive**

- The core ships with no compliance work and no per-country maintenance
  burden.
- Fiscal modules become an invitation to contributors who know a country's
  rules better than the maintainer does — and the extension points they need
  exist for after-the-fact work (the document events); a refusing hook at
  confirmation is still to be added (see the update above).
- The boundary between the self-hosted build and commercially supported
  editions follows a legal reality rather than withheld functionality.
- Internal documents deliver value immediately, in every country, with no
  regulatory dependency.

**Negative**

- No invoicing today. There is no invoice document in the codebase (a supplier
  invoice appears only as an extra cost spread over receipt lines), and
  users in countries with mandatory e-invoicing will ask for one.
- A country where nobody writes the module stays unserved for fiscal purposes.

## Risks

- **Steady user pressure towards accounting.** Mitigation: this ADR states the
  scope boundary, so each request is measured against it instead of reopening
  the question.
- **A fiscal module needs a seam the core does not expose.** Mitigation:
  when a real module hits a genuinely missing seam, adding it is core work —
  and that request is evidence rather than speculation.
- **Fragmentation across community fiscal modules.** Mitigation: neutral
  document codes mean every such module intercepts the same operations and
  reads the same events, whatever country it serves.

## Implementation

- `backend/app/modules/warehouse/models/document.py` — neutral `DocumentType`
- `backend/app/modules/warehouse/models/profile.py` — `type_labels`,
  per-organization document labels
- `backend/app/modules/warehouse/_pdf_labels.py` — label resolution order:
  organization labels → language default → internal code
- Selectable print layouts: a standard layout ships alongside localized ones
  such as `PL_PZ`, and either can be copied to write your own
- `backend/app/core/interceptors.py` — the synchronous item, storage and
  category seams; none for documents yet (see the update under Decision)
- `backend/app/modules/warehouse/country_tax_rules.py` — per-country tax
  rates, tax-id requirement and document preset (PL, DE, GB, FR, ES): data,
  not fiscal features
- `backend/app/core/contracts/events/_payloads.py` —
  `DocumentCompletedPayload`, `DocumentCancelledPayload`
- `backend/app/models/stock_valuation_layer.py` — valuation, the input a ledger
  would consume if one is ever built

## References

- [ADR-002](ADR-002-agpl-v3-and-dual-licensing.md) — AGPL v3 and dual
  licensing
- [ADR-007](ADR-007-interceptors-and-eventbus.md) — interceptors and EventBus;
  the extension points a fiscal module uses
- [ADR-009](ADR-009-core-neutrality-and-3-vertical-test.md),
  [ADR-011](ADR-011-core-neutrality-vocabulary.md) — core neutrality and its
  vocabulary. This ADR extends the same principle from domain vocabulary to
  jurisdiction.
- `AGENTS.md` / `backend/AGENTS.md` §4 — Core Neutrality
