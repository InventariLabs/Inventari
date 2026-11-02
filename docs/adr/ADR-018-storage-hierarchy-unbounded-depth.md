# ADR-018: Storage Hierarchy Has Unbounded Depth

## Status

Accepted — 2026-08-30

Supersedes [ADR-014](ADR-014-storage-hierarchy-fixed-levels.md).

## Context

ADR-014 fixed the location tree at three declared levels — SITE → ZONE →
LOCATION — and stored the level in a column so that views would stop guessing
it from tree position. That decision solved a real problem: the same tree
presented two different mental models one click apart. It solved it by choosing
variant A over variant B ("unbounded depth"), on one premise:

> The product horizon is home and small business; variant B only pays for
> itself with a WMS entry decision.

ADR-014 named the condition for reopening itself, and two things have since
met it.

**1. The premise about the product horizon was wrong in the direction that
matters.** Depth is not a warehouse-scale feature. A garage with a shelving
unit whose shelves hold labelled boxes is four levels, and it is the home case,
not the warehouse case. Both comparable products — Homebox, aimed squarely at
households, and InvenTree, aimed at workshops — nest locations without a limit,
and locations are the single area where a feature comparison puts Inventari
behind them. The ceiling was not protecting a small-scale product from
warehouse complexity; it was denying the small-scale case its natural shape.

**2. The fixed level cost more to keep than it bought.** Because the level is
declared rather than derived, it has to be maintained: a create derives it from
the parent, a move rewrites it across the whole moved subtree, the batch
reorganization recomputes it for the final state of the batch and rejects
anything that would need a fourth, and a backfill migration had to guard
against trees that were already deeper. Every one of those is machinery that
exists only because the column exists. It also produced its own class of
defect — a write that reaches the table outside the service layer records
whatever level it guessed, and nothing downstream can tell that the value is
wrong, because the value is the authority.

Meanwhile the unbounded shape never went away: `parent_id` is still a
self-referencing foreign key with no depth constraint, and no `CHECK`
constraint was ever added. The ceiling lives entirely in application code and
in one column that has to be kept honest.

Three further observations decided the shape of the replacement rather than
whether to make it:

- **A fourth named level is not the answer.** Naming levels is what creates the
  ceiling; a fourth name moves it by one and keeps the cost. The choice is
  binary: fixed names, or none.
- **"Leaf" is a state, not a property.** Under a fixed depth, "can hold items"
  and "is at the bottom level" coincide. Under unbounded depth they cannot:
  a shelf that holds items today becomes a parent the moment someone puts a box
  under it, and any UI that filters pickers by leafness would hide the items
  already there.
- **The backend never enforced leafness anyway.** Nothing in the write path for
  items checks the depth or the childlessness of the target location. The
  restriction was a filter in pickers, not a rule in the model.

## Decision

**Unbounded depth. `parent_id` is the only description of structure.**

1. **No level column, and no named levels.** Depth is derived from the parent
   chain wherever it is genuinely needed, and it is needed in fewer places than
   the enforcement machinery suggests. `StorageLocation.level` and the
   `StorageLevel` enum are dropped.
2. **Structural rules are about parents, not depth.** What a move must still
   refuse is unchanged and has nothing to do with levels: a parent in another
   organization, a node as its own parent, a descendant as a parent (a cycle),
   and a sibling name collision. What it stops refusing is "this would be a
   fourth level".
3. **Neutral vocabulary.** One word — *location* — plus the full path
   (`Home › Garage › Shelf A`) wherever a name alone would be ambiguous.
   SITE / ZONE / LOCATION leave the interface in every locale. The path, not
   the level, is what tells two identically named shelves apart.
4. **Items may live in any node.** A location that has sublocations can also
   hold items directly, as it can in Homebox. Counts distinguish "directly
   here" from "in sublocations", and that distinction is computed on the
   server rather than summed in the browser, because at arbitrary depth the
   browser would need the whole tree to do it.

### Migration direction

3 → N is a loosening: every row that was valid under ADR-014 stays valid, and
dropping the column cannot invalidate data. This matters beyond convenience —
it means the change is safe to apply to installations that are not ours, which
a tightening would not be.

### Alternatives considered

| Option | Why rejected |
|---|---|
| Keep three fixed levels (ADR-014) | The premise it rested on does not hold: depth is a home-scale need, and the ceiling is the one place a feature comparison puts us behind comparable products |
| Add a fourth named level | Moves the ceiling by one and keeps every cost that having a ceiling imposes; the next structure that needs five is not hypothetical |
| Keep the column as a derived hint, unenforced | A stored value that nothing enforces is a value that drifts, and the drift is invisible precisely because the column is what views trust |
| Unbounded depth plus a "structural" flag (InvenTree) | Solves a different problem — marking nodes that may not hold stock. Worth revisiting on its own merits; bundling it here would make one change two |

## Consequences

**Positive**

- Machinery is deleted, not added: level derivation, subtree level rewriting on
  move, the batch level planner with its "deep" sentinel, the depth-measuring
  recursive CTE, and two enforcement branches all go.
- A whole class of defect disappears with the column. A write outside the
  service layer can no longer record a wrong level, because there is no level
  to record.
- rack → shelf → bin, and anything deeper, becomes expressible. The comparison
  row that read "three fixed levels" against "unlimited nesting" closes.
- One mental model everywhere: a tree of locations, drilled into and shown as a
  path. The list, the reorganization sheet, the wizard and the edit sheet stop
  each having their own idea of what a node is.

**Negative**

- The reorganization sheet and the list are rewritten around recursion. That is
  the bulk of the work and it touches the most-used screen in the area.
- Vocabulary changes across five locales at once, in the wizard's onboarding
  suggestions as well as in labels.
- Counters move to the server. The list then summed one level of children
  client-side, which was correct only while depth was capped.
- Pickers get longer: with leafness gone as a filter, every location is a
  candidate target, and the full path becomes load-bearing rather than
  decorative.

## Risks

- **A deep tree is harder to navigate than a shallow one.** Mitigation:
  drill-down with a breadcrumb, and counts that say how much is directly in a
  node versus below it, so a parent never looks empty when it is not.
- **Drag-and-drop does not survive arbitrary depth on touch.** The
  reorganization sheet of the time used native HTML5 drag events (the location
  tree that replaced it still does), which do not fire on
  touch devices; recursion makes the drop targets smaller as well. Mitigation:
  an explicit "move to…" action on every row, with dragging kept as a
  mouse-only shortcut rather than the only way.
- **Duplicate names become the normal case rather than a rare one.** Name
  uniqueness is enforced among siblings only, and "Shelf 1" repeats in every
  rack. Wherever a location is resolved by name rather than by id — file
  import, in particular — that resolution needs a path, not a name.
- **Reverting is not free.** The column can be re-added, but its values cannot
  be reconstructed for trees that have since grown deeper than three, and the
  original backfill refuses such trees by design. In practice this decision is
  one-way.

## Implementation

- `backend/app/models/storage_location.py` — `parent_id` as the only structural
  column; `StorageLevel` and `level` removed
- `backend/app/services/storage/_writes.py` — parent validation (foreign
  organization, self-parent, cycle, sibling name) without level derivation or
  subtree level rewriting
- `backend/app/services/storage/_reorg.py` — batch planner validating the final
  state of the batch for cycles and name collisions only
- `backend/app/services/storage_hierarchy_service.py` — creation of a location
  chain of any length, resolving each step by id or by name within its parent
- `backend/app/schemas/storage_location.py` — `full_path` and `is_leaf` as the
  depth-agnostic replacements for a declared level; `subtree_items_count`
  populated rather than defaulted
- `backend/app/core/contracts/_core_dtos.py` — `StorageDTO` without `level`
- `frontend/src/modules/spaces/` — list, drill-down, location tree and
  wizard built from the parent map rather than from a level

## References

- [ADR-014](ADR-014-storage-hierarchy-fixed-levels.md) — superseded by this
  ADR. Its diagnosis of the original problem (views each guessing the level
  differently) stands; its remedy is what changes.
- [ADR-009](ADR-009-core-neutrality-and-3-vertical-test.md),
  [ADR-011](ADR-011-core-neutrality-vocabulary.md) — core neutrality and its
  vocabulary. Naming three levels was a vertical's vocabulary in the core, in
  the same way CONSUMED/DISCARDED was.
- `docs/subsystems/STORAGE_TREE_INTEGRITY.md` — parent and cycle integrity,
  which is what remains of structural validation
- Prior art: [Homebox](https://homebox.software/en/user-guide/locations/) —
  nested locations chosen by parent, with a breadcrumb;
  [InvenTree](https://docs.inventree.org/en/stable/stock/) — cascading stock
  locations of arbitrary depth
