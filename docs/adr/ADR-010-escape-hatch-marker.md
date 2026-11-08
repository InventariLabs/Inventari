# ADR-010: Escape-Hatch Marker for Read-Only Core DB Access

## Status

Accepted — 2026-07-12

## Context

[ADR-003](ADR-003-coreapi-facade-and-ast-sandbox.md) established that modules
must access Core data **only** through the `CoreAPI` facade, enforced by an AST
linter that bans `from app.models` / `from app.database` in module code. This is
correct for the vast majority of cases.

But a real gap exists: **complex analytics**. Some queries cannot be expressed
through the facade because they need SQL features CoreAPI does not expose —
`GROUP BY`, window functions, multi-join subqueries, CTEs. Examples in the
codebase: rotation analysis, expiry forecasting, aging buckets, reconciliation
(see `backend/app/services/analytics/`). Forcing these through a facade method
per query would bloat `core_api` with one-off analytics methods that no other
module will ever call.

The options at the extremes both fail:
- **No escape hatch:** analytics either get reimplemented N times across modules
  (drift, bugs) or CoreAPI balloons with bespoke methods (god-object).
- **Unconditional direct DB access:** the boundary from ADR-003 collapses.
  Everyone reaches for `app.models` "just this once" and the lint becomes
  meaningless.

We needed a **narrow, auditable, read-only** channel for legitimate analytics.

## Decision

**A module may bypass the facade for read-only analytics only, in a dedicated `*_service.py` file marked with an escape-hatch header. The marker requires a reason; the linter verifies the file is read-only; valid bypasses emit a GitHub `::notice` annotation in the PR review tab.**

### The marker

At the very top of the file:

```python
# architecture: allow_direct_db_access
# reason: <at least 5 words explaining why CoreAPI is insufficient>
```

Example (the form; a real one heads
`backend/app/modules/maker/stock_consumption.py`):
```python
# architecture: allow_direct_db_access
# reason: rotation analysis needs GROUP BY over multi-join stock_lot aggregates
```

### The five conditions the linter enforces

Implemented in `backend/app/core/architecture_lint/_violations.py`
(`_check_escape_hatch`), constants in `_constants.py`:

1. **Marker present** — `# architecture: allow_direct_db_access`. Without it,
   any `app.models` import in the file is a violation (per the module boundary
   guard in ADR-003).
2. **Reason comment present** — `# reason: ...`. Missing → `::error` + exit 1.
3. **Reason ≥ 5 words** — `REASON_MIN_WORDS = 5`. Too short → `::error` + exit 1.
   The word count forces the author to articulate a real justification, not
   `# reason: needed`.
4. **No forbidden writes** — the file is scanned (substring match, skipping
   comment lines) for `db.commit()`, `db.add(`, `db.delete(`, `db.merge(` (and
   `session.commit()`, `session.add(`, `session.delete(`). Any hit → `::error` + exit 1. **Escape-hatch files are
   read-only with respect to Core tables.**
5. **i18n in 5 locales** (separate per-module check, `validate_i18n` in `app/cli/module_validator.py`) —
   `en.json` always required; `pl/de/fr/es` required for `core`/`official`
   module types.

### Valid escape-hatch files: `::notice`, not error

When all conditions pass, the linter emits a non-blocking GitHub
`::notice` annotation (`_print_escape_hatch_notices` in `_main.py`):

> *This file has direct DB read access to Core tables. Reason: '...'.
> Auto-verified: db.commit/add/delete/merge are absent (read-only confirmed).*

This makes the bypass **visible in the PR review tab** without blocking it —
reviewers see exactly which files read Core directly and why.

### Module-local writes are allowed without a marker

Writing to **module-local tables** (models defined in the module's own
`models.py`) does **not** require an escape-hatch marker — the linter only
guards writes to **Core** tables (`app.models`). This is documented in
`backend/AGENTS.md` §3: "Writing to tables defined in your own module's
`models.py` needs no marker".

A subtlety: the write check is **substring-based, not table-aware** — it cannot
statically distinguish `db.add(MyModuleModel())` from `db.add(CoreModel())`. An
escape-hatch file that both reads Core AND writes its own module tables must
also declare `# module_writes: <tables>` on a comment line of its own to suppress
the write error (in `_check_escape_hatch`). This signals intent ("I read Core, I
write only my own tables"), and the declaration is checked: every name on the
line must be a model class (or table name) the module's own package declares,
or the lint fails — the line cannot lift the ban for a Core model.

### All writes to Core go through CoreAPI

This is the non-negotiable half. Even in an escape-hatch file, you may not call
`db.add(Item(...))` or `db.commit()` to mutate Core tables. If an analytics
flow needs to persist a result, it writes to its own module table; if it must
mutate Core, it calls `core_api.items.update_quantity_async(...)` etc.

## Consequences

### Positive

- **Analytics are possible without bloating the facade.** `GROUP BY`/window
  functions live where they belong — in the module's analytics service.
- **Auditable.** Every bypass is a `::notice` in the PR; reviewers can challenge
  any that looks like it should have been a facade method.
- **Read-only enforced.** The substring scan guarantees no Core mutation sneaks
  through the hatch.
- **Friction is calibrated.** Writing the marker + a 5-word reason is ~10
  seconds; it is not a review-board or a meeting.

### Negative

- **Ceremony.** Legitimate analytics authors must know the marker syntax. This
  is a real (if small) entry barrier — raised during release-readiness review.
- **Substring scan is coarse.** A `db.add(` inside a string literal or a
  comment-stripped line could in theory false-positive; conversely a sneaky
  `getattr(db, 'add')(...)` would evade it. In practice neither has been a
  problem. The `# module_writes:` opt-out exists for the common false-positive
  case (module-local writes).
- **Reason text can be gamed.** `# reason: because we really need to` (5 words)
  passes the length check. Mitigated by PR review — the `::notice` surfaces it.

## Alternatives considered

| Approach | Analytics possible | Boundary integrity | Verdict |
|----------|--------------------|--------------------|---------|
| **No escape hatch** | Only via facade methods | Strong | Rejected — CoreAPI balloons or analytics drift. |
| **Escape hatch, no checks** | Yes | Collapsed | Rejected — the boundary dies. |
| **Review-board approval per hatch** | Yes | Strong | Rejected — does not scale; bottleneck. |
| **Marker + lint checks (chosen)** | Yes | Strong (read-only enforced) | **Chosen.** Narrow, auditable, fast. |
| **Add every analytics query to CoreAPI** | Yes (as methods) | Strong | Rejected — god-object facade; one-off methods. |

## Implementation

- Linter: `backend/app/core/architecture_lint/_violations.py`
  (`_check_escape_hatch`), `_constants.py`.
- Notice emission: `_print_escape_hatch_notices` in `_main.py`.
- Module-local write opt-out: `# module_writes:`, read in `_check_escape_hatch`
  and held to the module's own tables by `_declared_module_writes`.
- Rule text: `backend/AGENTS.md` §3 "THE ESCAPE HATCH".

## References

- `backend/AGENTS.md` §3 "THE ESCAPE HATCH" — the rule.
- [ADR-003](ADR-003-coreapi-facade-and-ast-sandbox.md) — the facade boundary
  this hatch narrows.
