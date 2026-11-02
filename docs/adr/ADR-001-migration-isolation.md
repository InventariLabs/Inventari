# ADR-001: Per-Module Migration Isolation via Separate Version Tables

## Status

Accepted — 2026-06-10

## Context

All Inventari modules (11 with `models.py`) shared a single Alembic migration chain when this was decided
(`backend/migrations/versions/` with 155 files). Module models are bulk-imported into
`Base.metadata` by `migrations/env.py`. Consequences:

1. **Autogenerate mixes Core + modules** in one revision — hard to maintain.
2. **Module install doesn't create its tables** — `on_install` doesn't touch schema.
3. **Module uninstall doesn't clean up** — orphaned tables remain.
4. **Version collisions** — two modules can generate conflicting revisions on the same branch.

## Decision

**Per-module separate `version_table`** (Option B below).

Each module gets:
- Its own `migrations/` directory inside the module (`app/modules/<m>/migrations/`)
- Its own `env.py` with `version_table = f"alembic_version_{module_name}"`
- Its own `versions/` directory with module-specific revisions
- A `branch_label` on the initial revision for Alembic tracking

Core migrations remain in `backend/migrations/versions/` with the default
`alembic_version` table — completely unchanged.

### Why Option B over Option A (multi-branch)

| Criterion | Option A (multi-branch) | Option B (separate version_table) |
|-----------|------------------------|----------------------------------|
| Complexity | High — `version_locations` in alembic.ini, `depends_on` between branches, undocumented quirks | Low — each module is self-contained |
| Isolation | Shared `alembic_version` table with branch labels | Fully separate tables — zero coupling |
| `alembic upgrade head` | Upgrades ALL branches (core + all modules) | Upgrades ONLY core — module upgrades are explicit |
| Module install/uninstall | Complex — stamp specific branch | Simple — create/drop version_table + run upgrade/downgrade |
| Debugging | Hard — branch labels in one table | Easy — one table per module, clear ownership |
| Risk | Medium — Alembic multi-branch is poorly documented | Low — standard Alembic, just with a custom version_table |

### Why not Option C (metadata.create_all)

No versioning, no downgrade, no migration history. This option was
considered and rejected.

## Consequences

### Positive
- Module install/uninstall is self-contained — no touching core migration chain.
- Autogenerate for a module only sees that module's models.
- Each module can evolve its schema independently.
- Core migrations are unaffected — zero risk to existing data.

### Negative
- Module migrations depend on core tables existing first (FK constraints).
  **Mitigation (actual implementation):** `backend/entrypoint.sh` runs core
  migrations before module migrations under the migration advisory lock;
  `manage.py db upgrade` likewise upgrades core before modules when targeting
  `head`. `run_module_migrations()` itself does **not** check that core is at
  head: it is a per-module runner, also used for `current`, `stamp` and repair
  operations on individual chains. Ordering belongs to the upgrade entry
  points, not to every action on a module chain. Direct callers must establish
  the core prerequisites themselves; a standalone module upgrade is not
  protected by a core-at-head guard.
- 155 legacy migrations remain until the baseline flatten (Implementation
  step 2) (today: flattened — `backend/migrations/versions/` holds one
  baseline and the old chain is archived in `versions_archive/`).
- Each module needs its own `env.py` — small boilerplate per module.

### Risks
- **FK to core tables** — module tables reference `organizations.id`, `users.id`, etc.
  Core must be at head before any module migration runs. This is the natural order
  (core exists before modules).
- **Shared tables** — if two modules ever need the same table, ownership must be
  explicit. Current design: each table belongs to exactly one module or core.

## Implementation

> **Status 2026-10-31:** steps 1–6 are done. `nutrition` is the exception to
> step 6: its models sit on a base of their own in the separate products
> database and have no migration chain of their own.

1. Spike on `api_keys` (done) — proved the mechanism works (6 tests green).
2. Flatten 155 core migrations to 1 baseline.
3. Update `module_generator` to scaffold `migrations/` directory.
4. Wire `on_install`/`on_uninstall` to `run_module_migrations()`.
5. Linter guard — model without migrations directory = error.
6. Backfill 11 existing modules (stamp, not recreate).

## References

- Spike implementation: `backend/app/core/module_migrations.py`
- Spike tests: `test_module_migration_spike.py` in the `api_keys` module (removed since; the round trip is now covered by `backend/tests/integration/test_module_migration_roundtrip.py`, which auto-discovers all modules)
- Module env.py: `backend/app/modules/api_keys/migrations/env.py`
