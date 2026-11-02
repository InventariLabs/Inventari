# Pagination: offset, cursor and keyset

Three ways to page a list exist in this codebase. Which one a list uses is a
question about how it grows, not about taste.

| Shape | Envelope | Use it for |
|---|---|---|
| **Offset** — `limit` + `offset`, a `COUNT(*)` per request | `PaginatedResponse.from_slice` | Lists that stay small: a settings table, a picker, anything an organization will not grow past a few thousand rows. `db_utils.paginate_async` is this. |
| **Cursor** — `limit` + opaque `cursor`, no count | `CursorPaginatedResponse` | Feeds read front to back that never show a total: item history, webhook deliveries, the infinite-scroll item list. |
| **Keyset with a carried count** — `limit` + `cursor`, the total counted once | `KeysetPaginatedResponse` | Lists that grow without bound **and** whose screen says "101–200 of 5,000": the stock movement ledger (`GET /stock-moves`) and the audit journal (`GET /audit-log`). |

## Every list answers with an envelope

A route that returns a collection declares one of the three envelopes above.
`response_model=list[...]` is refused by the architecture lint
(`app/core/architecture_lint/_quality_checks_list_envelopes.py`): FastAPI would
publish a bare JSON array — no page size, no total, no next cursor — and a
screen written against it falls over at the scale the envelope exists for.
The gate has no baseline: a bare-array route is an error the moment it is
written. A route that is **not** a collection of rows — a
bulk-operation result, a fixed vocabulary — carries
`# list-envelope-exception: <reason>` in its registration, next to the route,
so the next reader finds the decision where it was made.

A list that stays small (the offset row above) takes `limit` and `offset` and
answers `PaginatedResponse`. When its service already returns every row,
`PaginatedResponse.from_full_list(items, offset=offset, limit=limit)` slices it
and reports the true total; the usual query parameters are
`limit: int = Query(50, ge=1, le=200)` and `offset: int = Query(0, ge=0)`.
A list that grows pages in the database instead — `paginate_async` for offset,
a keyset read for a feed — because reading it whole is the cost the envelope
is there to avoid. `from_full_list` is for the small lists and says so in its
docstring.

One page shape serves every offset list: `items`, `total`, `limit`, `offset`
and `has_more`. A list does not carry a second name for its rows (`documents`,
`stock_takes`, `lines`), a page counter in place of `offset` (`page`,
`page_size`), or a `total` without the rest. The keyset page adds
`next_cursor` and the cursor page replaces `total`/`offset` with it;
`total_capped` joins either envelope when a count stops at the cap, and
nothing else varies. A screen that needs the whole set of a small list
(a picker, a settings table) reads page after page with `getEveryPage`
(`frontend/src/lib/api/client.ts`) instead of assuming the first page is all
of it.

### Sections of a dashboard

A response that is not one list but a screen's worth of them — the To do
queue's inbound, outbound, backorder, approval and quarantine rows plus its
tasks (`GET /warehouse/todo`) — answers with a section per list, each
`{items, total}`: the rows that fit the card and the server's own count of all
of them. A section is a capped slice, read once with the others, and has no
page to ask for, so it carries no `limit`, `offset` or `has_more`; a client
that needs more than the cap reads the list endpoint behind the card, which
pages. A section is an exception to the envelope and says so on its schema
(`DocumentsTodoSection`, `QuarantineTodoSection`, `WorkItemsSection`), the
same way a bare-list route says it in a `# list-envelope-exception:` comment.
The result of an action that happens to hold rows (a generated shopping list's
lines, the counts of a shortage list) is likewise the action's own shape, not
a collection.

## Why offset stops being acceptable

`OFFSET n` does not seek to row *n*: the database produces the *n* rows above
it and throws them away, and a `COUNT(*)` on every request scans the
organization's slice again. Both costs grow with the table, not with the page.
Measured on a hundred thousand movements (`EXPLAIN (ANALYZE, BUFFERS)`, a page
of 100):

| Page of 100 | Rows read from the table | Buffers touched |
|---|---|---|
| First page | 100 | 17 |
| A page 100 rows from the end, by keyset | 100 | 18 |
| The same page by `OFFSET` | 99,999 | 6,874 |
| By keyset, inside a group of 50,000 movements that share one instant | 100 | 111 |

The tests hold **rows read** and not buffers, because how many buffers the same
rows sit on depends on how the table was filled (the buffer count of one plan
differed by a factor of thirty from run to run). The journal pages the same way
under the same budget, and the list of target types its screen offers reads
over 600 buffers as `SELECT DISTINCT` and under 60 as a loose index scan (the
budget in `test_a_long_journal_stays_quick.py`).

## The recipe

A list moves to keyset in four parts. The ledger is the reference
(`stock_moves_service.list_rows_for_org_async`, `api/stock_moves.py`).

1. **An index that is the sort order.** The list must sort by an index it can
   walk: `(organization_id, <sort key> DESC, id)`. The ledger's key is an
   expression (`coalesce(completed_at, created_at)`), and the index is written
   on that exact expression. If no index carries the order, keyset has nothing
   to seek into — add the index first.
2. **A total order.** The sort key plus `id` as tiebreak. Entries written by one
   batch share an instant, so ties are the ordinary case. `ORDER BY key DESC`
   alone makes a page boundary lose or repeat rows.
3. **Two seeks for "below the last row seen".** For `key DESC, id ASC`, the
   rows below the one the reader saw are the rest of its tie group (same key,
   larger id) and then everything older. `app.core.keyset.read_page_after`
   reads them as two statements, each one a range on the index:

   ```python
   key == seen_key and id > seen_id      # order by id          — the tail of the group
   key <  seen_key                       # order by key DESC, id — only if the page is not full
   ```

   Do not write it as one condition. `key <= seen_key and (key < seen_key or
   id > seen_id)` is correct, but the `OR` is not an index condition: the
   database seeks to the key and then reads the whole group that shares it to
   throw away the ids already shown. Groups are not bounded by the page — a bulk
   import or a stocktake closed in one go writes thousands of rows at one
   instant — and a page that started inside one cost the size of the group
   (measured: 50,100 rows read for a page of 100). A row comparison would be one
   seek, but it cannot mix `DESC` and `ASC` columns. The index must therefore
   end in `id`, so that the first range is ordered by it.
4. **One row more than asked.** Fetch `limit + 1`; the extra row existing is
   what `has_more` and `next_cursor` mean. No count has to be right for that.

## The count, and why it rides in the cursor

A screen that says "of 5,000" needs a total, and a total that is recounted per
page both costs a scan and moves under the reader. The first page counts once;
`encode_keyset_cursor` carries `total` and `offset` (rows served before the
next page) in the cursor, and every later page passes them back as
`known_total`. So:

- no later page runs a `COUNT`;
- the figure does not change while the reader pages — new rows landing above the
  reader's position do not change the figure on their screen;
- a new first page (any change of filter) counts afresh.

A cursor holds no authority. The query that reads it is still scoped to the
caller's organization and filters; the worst a forged cursor does is show its
sender a wrong figure. A malformed one answers 400.

## A count that grows with the organization stops at ten thousand

Counting once is still counting everything: at a hundred thousand products
the count of the product list, the stock list or a month of stock movements was
most of the first page, and it grows with the warehouse. Those lists count
only so far — `db_utils.LIST_COUNT_CAP`, ten thousand rows, two hundred pages
of fifty — and say where they stopped:

- `paginate_async(..., count_cap=LIST_COUNT_CAP)` stops the count one row past
  `count_window(offset, limit, cap)`: the cap, or as far as the page reaches,
  so a page past the cap still knows whether another follows.
- `from_slice(..., count_cap=LIST_COUNT_CAP)` reports a count past the window
  as the window, with `total_capped: true` and `has_more: true`. A keyset list
  carries `total_capped` in its cursor beside the count.
- The screen says "of more than 10 000" (`Pagination`'s `totalCapped`, the
  `ListControlBar`'s `resultCountCapped`), offers the counted pages for a jump,
  and keeps "next" open past them. Beyond ten thousand rows a reader searches
  or filters.

Where a screen names the exact number, it takes it from a report that counts
anyway: the product list's footer (`GET /items/aggregates`) carries its count.
A list that stays small does not pass a cap and keeps its exact total.

## `offset` stays, deprecated

The endpoints still accept `offset` without a cursor, so a client written
against them keeps working. It costs what it always cost. New callers page with
`cursor`; the screens in the app already do.

## The screen

Keyset has no "page 40": a page is reached from the one before it. The hook
`useKeysetPaging(question)` keeps the cursors of the pages already seen, so the
reader can go forward and back to any page they have visited, and it starts
again from the first page when the question (the filters) changes. The
`Pagination` bar is used without a page-jump field for exactly this reason.
While the next page loads, the previous rows stay on screen
(`keepPreviousData`); their cursor must not be taken for the new page's, so
the screens ignore "next" while `isPlaceholderData`.

## Migrating the next list

For each list still on offset (the archived items in `api/_items_queries.py`,
the `paginate_async` callers whose tables grow):

1. Write down the sort order and check an index serves it — `EXPLAIN` the page
   on a table a hundred thousand rows long, not on the dev stack.
2. Add `after_*` and `known_total` parameters to the service, additively
   (modules read services through `core_api`, so only add, never rename).
3. Return `KeysetPaginatedResponse.from_keyset` from the endpoint, with the
   cursor from `app.core.cursor`.
4. On the screen, replace the page state with `useKeysetPaging`.
5. Add the tests every keyset list has: a walk that sees every row once across
   ties (`test_the_ledger_pages_by_the_last_row.py`), and a plan-shape test that
   compares the rows a deep page reads from the table with the first page's,
   holds the offset page up as the contrast, and checks the page against the
   exact ids the plain definition of the order gives — a fast page of the wrong
   rows must not pass. Include a group of tied rows far larger than the page,
   with pages starting before it, inside it and where it ends
   (`test_a_deep_ledger_page_costs_what_the_first_costs.py`). Measure rows read,
   not a clock and not buffers: a clock measures the machine, and how many
   buffers the same rows sit on depends on how the table was filled.
