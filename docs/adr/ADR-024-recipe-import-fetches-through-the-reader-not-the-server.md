# ADR-024: Recipe Import Fetches Through the Reader, Not From the Server

## Status

Accepted — 2026-10-02

## Context

Importing a recipe from a URL costs at least one AI request out of the organization's
monthly budget (`ai_requests_monthly`): the page is read by an external reader
(Jina) and its markdown is parsed by the model bound to the `recipes.text_parse`
purpose (a page with ingredient lines spends a second request, in which the
same model parses them). Most recipe sites publish the same data as schema.org JSON-LD, which
could be parsed without a model and without spending the budget, so the
question comes back: why does the import not look at the page's structured data
first?

The module once did. A community scraper and a JSON-LD scraper ran before the
reader, and both were removed. Each fetched the page **by hostname** after a
validate-then-fetch check (`app/core/ssrf_guard.py` resolves the name, checks
the address, and the HTTP client then resolves it again). Between the two
resolutions a hostile name can answer with a public address for the check and a
private one for the fetch — the DNS-rebinding window that the cover fetcher had
to stop having. With several organizations on one installation, an organization
admin choosing the URL would be aiming the server at its own network.

## Decision

**The import does not fetch the page from the server. The page is fetched by
the reader, and the model reads what the reader returned.** Structured data is
not tried first, because trying it means the server connects to a host the
user typed.

### Alternatives considered

| Option | Why not (now) |
|---|---|
| Direct fetch by hostname, JSON-LD first | The rebinding window above; this is what was removed. |
| Direct fetch that connects to the address the guard verified, JSON-LD first | Closes the window and would save a model call on most sites. Not built: it needs its own pinned-address fetcher with redirect handling, size and time limits, and a schema.org parser that copes with the real variety of markup, for a saving that is a quota convenience, not a defect. Reopen when the budget proves tight in use. |
| JSON-LD from the reader's own output | The reader returns cleaned markdown, not the page's script tags. |

## Consequences

- Every URL import spends at least one AI request, including pages with perfect
  structured data. The limit refuses *before* the reader is called, so an
  organization out of budget spends nothing on the way to the answer.
- The server never opens a connection to the page the user typed; the cover
  image, adopted afterwards, goes through its own pinned fetcher, and the
  surface the SSRF guard has to defend stays at outbound calls the server
  makes itself — webhooks, an AI connection's base URL, that fetch — plus the
  address check on a typed import URL, which is a name lookup, not a
  connection.
- The cost is quota, not correctness: an import and a typed recipe end the same.

## Risks

- A site that blocks the reader cannot be imported at all; there is no second
  route. The refusal reaches the person as an import failure, and typing the
  recipe stays possible.

## Implementation

- `backend/app/modules/recipes/_import_url_pipeline.py` — the limit check
  precedes `_scrape_recipe`, which has one route.
- `backend/app/modules/recipes/scrapers/jina_llm.py` — the only scraper.
- `backend/app/modules/recipes/scrapers/base.py` — records that the other tiers
  were removed and why.

## References

- `backend/app/core/ssrf_guard.py` — the validate-then-fetch guard and its
  rebinding caveat.
