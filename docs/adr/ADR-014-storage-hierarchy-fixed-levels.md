# ADR-014: Storage Hierarchy Has Three Fixed Levels

- **Status:** Superseded by [ADR-018](ADR-018-storage-hierarchy-unbounded-depth.md) (2026-08-30)
- **Date:** 2026-08-15
- **Deciders:** product + engineering
- **Supersedes the implicit "unbounded tree, level guessed by views" model.**

## Context

`StorageLocation` is an unbounded tree (`parent_id` → self) without a column
that declares a node's level. The fixed mental model Site → Zone → Location
existed only as an assumption, and each view inferred the level differently:

- the list hides buildings by flattening the tree,
- the reorganization modal assumes exactly three levels,
- the wizard creates only two levels and picks a building automatically,
- the edit sheet treats every node with children as a "zone".

The same tree therefore presented two different mental models one click
apart, a fourth level created via API was invisible on the list, and
`parent_id` was not validated at all (fixed separately — see `docs/subsystems/STORAGE_TREE_INTEGRITY.md`).

Two variants were on the table:

- **A — three fixed levels**: add a `level` column (SITE / ZONE / LOCATION),
  enforce it on create/move, views stop guessing.
- **B — unbounded depth**: recursive rendering everywhere, neutral
  "location" vocabulary, full rewrite of the list and the reorg modal.

## Decision

**Variant A.** The product horizon is home and small business; variant B
only pays for itself with a WMS entry decision. The wizard — the best
designed part of this area — already assumes two levels under an
auto-selected building, which matches A.

## Consequences

### Model

- `StorageLocation.level` (SITE / ZONE / LOCATION), NOT NULL, backfilled
  from the current tree depth.
- The backfill migration aborts loudly if any node sits deeper than the
  third level or has no reachable root (cycles) — repair first (see
  `docs/subsystems/STORAGE_TREE_INTEGRITY.md`), then migrate.

### API

- `create_storage` / `update_storage` derive the level from the parent:
  no parent → SITE, SITE → ZONE, ZONE → LOCATION. Re-parenting under a
  LOCATION is rejected (400) — there is no fourth level.
- Re-parenting a node with a subtree may not push any descendant below
  LOCATION; such moves are rejected.
- The reorg batch validates levels on the final state of the batch.

### UI

- Views read `level` instead of inferring it from tree position (list,
  reorg modal, edit sheet).
- "Building / zone / place" remain the vocabulary of the three levels.

### Sacrificed

- Structures like rack → shelf → container (a fourth+ level) are closed
  off until a WMS entry decision re-opens this ADR. The columns and the
  unbounded `parent_id` stay; only the level is fixed.
