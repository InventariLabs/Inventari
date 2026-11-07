# Audit Trail Subsystem

- **Org journal**: `AuditLog` (`app/models/audit_log.py`), written by `app.services.audit_service`
- **Item history**: `ItemHistory` (`app/models/item_history.py`)
- **Read side**: `core_api.audit_log` (append-only by construction — it lists entries and its one write adds a row; the HTTP API is read-only)

## Two ledgers, two questions

- **AuditLog** answers "who did what to the organization" — actor,
  timestamp, action, target, `before`/`after` snapshot, reason. API
  read-only, admin-only, org-scoped. Entries with no change (`x → x`)
  are not written.
- **ItemHistory** answers "what happened to this item" — the per-item
  story (created, quantity changed, consumed, discarded) with the
  reason and, where one exists, the document that caused it.

## What earns an entry

The rule lives in the `AuditTargetType` docstring
(`app/core/contracts/_system_dtos.py`), not only here. Four kinds of act,
plus one rule across them:

- **Stock** — what there is and how much.
- **Catalogue** — the definitions everything else is written against:
  products, categories, locations, document templates, product profiles,
  equipment models.
- **Access** — who may do any of it.
- **Custody** — who holds a thing, where it is, whether it is fit to use.

And, whatever the kind, **every irreversible deletion**. What does not
belong: somebody's own working note (a recipe, a meal plan, a shopping
list) — deleting one still logs, under the deletion rule.

A **storage type** earns no entry. It is the vocabulary a location is filed
under, and no door that writes one journals it — the profile seed, a
module's declaration, the settings screen and the location-chain creator's
inline type are all silent. A row on the wizard's path alone would not
cover the type; it would make the journal speak about one door and stay
silent about the same act at another. Where the kind matters to a
location's history, the location's own entry carries the type's name
(`storage_type_name` on an update).

A **sheet of blank labels** earns no entry either: generating or importing
one only reserves codes, as the product barcode counter does, and marking a
sheet printed changes no record. A label becomes a fact when it is bound to
a product, freed from one or deleted — the three acts that change what a
scan of it answers — and those are journaled under `label`.

A batch writes **one row per record**, with `meta_data.bulk` saying it was
a batch. Fifty assets retired at once and fifty retired one at a time
leave the same fifty rows: the journal does not depend on which button was
pressed. The row names what the record took — its columns, its card's
threshold and unit weight, a date it keeps in `meta_data` — and not what
the request said; a record the batch left as it was gets no row, as the
single edit writes none for an edit that changed nothing.

Where two paths reach the same table — document templates, written by
equipment, documents and purchase orders alike; product templates, which
are also what the equipment module calls a model — the entry is written in
the shared service, not in each module, and under one word. A row reached
from two screens that shows up under two target types is a filter that
finds it twice and never whole.

A word the log has stopped writing still has to be readable: the journal
is immutable, so `AuditTargetType` keeps the retired value and the screen
keeps its label (`equipment_model` is the one there is so far). Removing
it would leave rows already written showing a bare key.

## What the numbers look like

Quantity history and audit snapshots carry the **exact Decimals as
strings** — a float there is less precise than the data it describes,
and the trace must not be the least precise copy of the facts.

Two functions in `app/services/audit_service.py`, and the difference
between them is the whole rule:

- `audit_value(v)` — **what a value became**, for the snapshot. A
  `Decimal` becomes its exact digits as a string; UUIDs, dates, enums and
  containers are rendered so the JSONB column and the Detail column can
  both take them.
- `audit_key(v)` — **whether a value moved**, for comparison only, never
  written down. A `Decimal` compares as a number here: `Decimal('1.000')`
  and the `1` a form posts are one quantity, and comparing their digits
  is how the log filled with rows whose every field read `x → x`. A text
  field standing empty and one that was never filled are also one value:
  a form posts its whole state, so `""` beside a NULL column is not a
  change and must not write a line reading `Description: — →`.

Rows written before this was one rule keep the shape they were written
with — the journal is immutable in the database, so there is no migration
to run and none should be attempted. The audit screen formats a number
and prints a string as it stands, so both read correctly side by side.

## A key acts for its owner, and the entry says both

An API key authenticates as the account behind it, so an entry written through
one carried that account's address and no `meta_data` at all — the same row a
person working at the screen leaves. That is the wrong shape for the one
question a revoked key raises: the key leaves the list of keys, and if the
journal never named it, nothing left in the installation says what it did.

Every entry written by a request authenticated with a key therefore carries
`meta_data.actor = {'type': 'api_key', 'key_prefix': 'inv_live_…'}` — the
prefix the API Keys screen shows, never the key itself. An entry written
before that prefix was cut to six characters keeps the eleven it was written
with (the journal is immutable), and still begins with what the screen shows
now. The actor is
request-scoped (`app/core/audit_actor.py`): set where authentication resolves
the key, read once in `log_action_async`, and cleared around every request by
the app-level `audit_actor_scope` dependency. Everything a caller wrote into
`meta_data` itself is kept beside it, and a person's request writes no actor
at all — which is why the read filter (`actor=api_key` / `actor=human`) asks
whether a key is *recorded*, and rows written before this existed read as
people's.

## A reference is written with its name

A snapshot that points at another record writes that record's name beside its
id — `storage_location_id` with `storage_location_name`, `parent_id` with
`parent_name` — read in the same transaction as the write. The journal is the
record of what the record was called when the act was done: a shelf renamed
next week must not rewrite last month's entry. In a `before`/`after` pair the
name belongs to the side it describes; in a flat snapshot (a create, a delete)
it is a flat sibling. The Detail column prints the name and falls back to the
shortened id only when the snapshot carries none — it cannot resolve an id per
row, and a settings screen may not reach into the inventory modules for their
dictionaries.

Where the app reads a reference by **code**, the code is written beside the
name (`category_id`, `category_name`, `category_code`). A seeded category
carries its seed's English name (`Dairy`) while every screen shows the label
its code translates to (`Nabiał`) — one category, one name — so the reader
resolves the code through the catalogue the rest of the app uses and keeps the
recorded name as its fallback. This is the same rule a batch obeys: a bulk
item edit names its references on both sides exactly as the single edit does,
and the reading side judges each row alone.

## Period guard

Closing a period blocks every path that mutates stock (documents, scan,
import, `update_quantity`, move, consume and discard, bulk, stock take,
recipe picking, production runs and their reversal) for dates inside the
closed month. Which day "today" is decides whether an edit
passes at all, so the guard asks the **organization's** day, not the
server's.

## GDPR vs accounting

Anonymization leaves the UUID behind, so audit cross-references survive
the person. Purging an item copies its full history into the audit
entry (action `PURGE`) before the CASCADE takes the rows — the trail
outlives the record.

## Integrity

The journal is immutable **in the database**, not only in the API: a
trigger (`audit_log_immutable`, created by the baseline migration) rejects
UPDATE and DELETE on `audit_log` in every environment the migrations build.
The read API is admin-only and org-scoped.

## Reading the journal at scale

The journal is append-only and nothing prunes it, so every read of it is judged
against a table that only grows. How it is read:

- **Pages by the last entry seen**, not by offset: `GET /audit-log` hands back a
  `next_cursor`, and the next page starts below that entry. Entries written by
  one batch share an instant, so the order is `created_at DESC, id` and the
  rows below the one last seen are read as two index seeks (the rest of its
  batch in id order, then older entries), so a page costs its own rows even
  when it starts inside a batch of fifty thousand entries written at one
  instant. The pattern and its reasons are in `PAGINATION.md`.
- **Does the screen have to count every entry on every page? No — once per
  question.** The screen says how many entries match, and that figure is worth
  having, but it is the same figure on every page of one question. The first
  page counts; the cursor carries the figure and the number of entries served so
  far; no later page counts again, and the figure does not move while the reader
  pages. A change of filter is a new question and counts afresh. The count under
  a filter reads the index below instead of the table (a parallel sequential
  scan of 4,362 buffers at 240,000 entries before; an index-only scan now).
- **The kinds of thing the log holds** (`GET /audit-log/target-types`) are read
  as a loose index scan, one index entry per type: 16 buffers where
  `SELECT DISTINCT` read 1,539 on a hundred thousand entries, and the gap grows
  with the journal.

Each is held by a plan-shape test (`test_a_long_journal_stays_quick.py`), which
counts buffers and rows walked, not milliseconds.

## The journal's indexes

`audit_log` is written on every meaningful action, so every index is paid for on
each write. This is what each one is for, and what is known about whether it
earns its place:

| Index | Columns | What reads it |
|---|---|---|
| primary key | `id` | Row identity; the tiebreak of every page. |
| `ix_audit_log_org_created_at_id` | `organization_id, created_at DESC, id` | The page: one organization, newest first, with or without a user, actor or date filter. Keyset pages seek into it, and the id is last so a page that starts inside a batch written at one instant reads the rest of the batch in id order. (It replaced `ix_audit_log_org_created_at`, which was its prefix.) |
| `ix_audit_log_org_type_created_at` | `organization_id, target_type, created_at DESC, id` | The journal narrowed to one kind of thing: its page, its count (index-only), and the list of types (loose scan). Without it a rare type means walking the organization's timeline, and the count is a sequential scan. |
| `ix_audit_log_target` | `target_type, target_id` | The history of one record (`list_for_target_async`): the card of a product, a location, a document. |
| `ix_audit_log_user_id` | `user_id` | The user filter, and the foreign key's own lookups. |
| ~~`ix_audit_log_organization_id`~~ | `organization_id` | **Dropped** (`auditidx03`, CONCURRENTLY). It was the leading column of both composites above, which serve the same lookups, and every write paid for it. Read from `pg_stat_user_indexes` on a running stack holding 600,000 entries over ten organizations, the planner still chose it for the count of one organization and for filtered counts; without it the same heap is read through the composite: 8,518 buffers of heap either way, about 400 more of index (4%). The foreign key's own lookups lead with the composites too. |
| ~~`ix_audit_log_created_at`~~ | `created_at` | **Dropped.** Nothing reads the journal by date without an organization, and it was a planner trap: the older-entries seek (`organization_id = ? AND created_at < ?`, newest first) could be planned on it backward with the organization as a filter, reading the other tenants' entries (52,000 rows for a page of 100). The organization is a constant of the query, so it cannot be put in the `ORDER BY` to rule the index out; removing the index is what does. |

Both candidates are gone. A drop on a table this size is irreversible without a rebuild, so the
evidence for the second came from a running stack's `pg_stat_user_indexes`, not from a test database.
