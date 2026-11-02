# Storage Location Tree Integrity

Status: operational runbook. Owner: backend (Core storages).

## Context

`StorageLocation` is an unbounded tree (`parent_id` → self). Before the
`parent_id` validation fix (2026-08-14) the API wrote `parent_id` from the request without any
validation, so a cycle (e.g. `A.parent = B`, `B.parent = A`) passed with
200 OK. `build_tree` then silently dropped cyclic nodes from
`GET /locations/tree` while `GET /locations` still returned them — the affected
locations disappeared from the entire UI (list, wizard, edit sheet all feed
on the tree) while staying in the database together with their items.

Two fixes changed the contract:

- **`parent_id` validation** — `create_storage` / `update_storage` validate `parent_id`:
  the parent must exist in the same organization (404), must not be the
  edited node itself (400) and must not be its descendant (409
  `STORAGE_CYCLE`, recursive CTE). New cycles can no longer be created.
- **Tree visibility** — `build_tree` appends nodes that remain unreachable from the
  roots to the root list (with a warning log) instead of dropping them. If a
  cycle appears anyway (migration, import, bug), the data stays visible and
  repairable from the UI.

## Repairing a cycle that got in anyway

A cycle can still arrive by a path that skips the service — direct SQL, an
import that writes rows itself. `build_tree` then logs the ids of the nodes it
could not reach from a root and lists them as roots, so they stay on screen.

Moving locations repairs it like any other misplaced one: give
one member of the loop a new parent with "Move to…" (or drag it), or make it
a root. The batch goes to `POST /locations/reorg`, which validates the final
tree, so the repair cannot introduce a new cycle. That validation reads the
whole organization's tree, so a batch saved while a loop remains anywhere is
refused: the first batch has to cut every loop. One cut per loop is enough —
a node hanging below the loop becomes reachable again with it.

## Flat structures left by the level backfill

`storagelevel02_backfill_storage_levels` recorded a level for every location
it found, and a location with no parent became a SITE. Rooms created before
ADR-014 were top-level locations, and the migration had no grounds to guess
which house they belong to — it recorded what it found. Everything created
since is a top-level location of its own (a new warehouse is a root, with no
default site), so such an installation ends up with its old rooms and its newer
warehouses as two parallel structures, both made of top-level locations.

The levels are gone (ADR-018; the column was dropped by
`storagelevel03_drop_storage_level`), the two structures are not. They are
ordinary locations, and dropping a column repairs nothing about them.

There is no one-off tool for this, and none is needed: the **Move to…** action
files them. Every row carries it, and the picker offers the other locations as a
searchable tree, shown by full path (the location being moved and everything
inside it are left out); dragging does the same with a mouse. The
batch goes to `POST /locations/reorg`, which validates the final tree — every
parent exists, no cycles, no two siblings sharing a name — and nothing else:
how deep a chain ends up is not a reason to refuse it. Nothing is deleted and
retyped, so codes, contents and history stay.

## Prevention

- Writes of `parent_id` go through `create_storage` / `update_storage`, which
  validate the parent (the hierarchy creator calls `create_storage` too). The
  reorg batch (`POST /locations/reorg`) writes it as well and validates the final
  tree instead. Direct SQL or imports must apply the same checks.
- `build_tree` keeps any future damage visible instead of hiding it;
  its warning log (unreachable node ids) is the early signal to re-run this
  runbook.
