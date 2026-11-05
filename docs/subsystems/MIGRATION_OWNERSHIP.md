# Module Migration Ownership

## Architecture

Inventari uses a **dual-track Alembic migration system**:

| Track | Version table | Scope |
|-------|---------------|-------|
| **Core** | `alembic_version` | Domain-neutral tables (items, users, organizations, stock, etc.) |
| **Per-module** | `alembic_version_<module>` | Module-owned tables (webhooks, warehouse, recipes, etc.) |

Each module's migrations live in `app/modules/<module>/migrations/` and are
completely independent — they have their own `env.py`, `versions/` directory,
and Alembic branch label (`<module>`, except `warehouse`, whose label is `documents`). This means:

- `alembic heads` with `backend/alembic.ini` shows only the core chain's
  heads. Module chains are separate script locations, not additional core
  branches; their presence does not depend on which organizations enable them.
  Inspect a module with its own Alembic config, or use `manage.py db doctor`
  to compare each discovered module's recorded revision to its head.
- Modules can be enabled/disabled without affecting other modules' schema.
- Module migrations run at startup after core migrations
  (`backend/entrypoint.sh` → `manage.py db upgrade-modules`) and at install
  (`BaseModule.on_install()` → `_run_module_migrations('upgrade')`). The base
  `on_enable()` hook does not run migrations; organization toggles and schema
  installation are different operations.

## Table Ownership Matrix

### Module-owned tables (12 modules, 70 tables)

The inventory below describes the current models and migration chains in
0.11.0, not just each module's initial revision. Each link contains the full
chain (including incremental changes); do not infer the current schema from
`001_initial.py` alone.

| Module | Tables | Migration chain |
|--------|--------|-----------------|
| `api_keys` | `api_keys` | [versions](../../backend/app/modules/api_keys/migrations/versions/) |
| `approvals` | `approval_decisions`, `approval_requests`, `approval_workflows` | [versions](../../backend/app/modules/approvals/migrations/versions/) |
| `warehouse` | `document_extra_costs`, `document_lines`, `document_number_sequences`, `document_package_lines`, `document_packages`, `document_profiles`, `document_relations`, `document_shipments`, `document_type_configs`, `document_warehouse_receiving`, `document_work_item_overlays`, `documents`, `inventory_periods`, `putaway_capacity`, `putaway_home_silenced`, `putaway_location_settings`, `putaway_rule_locations`, `putaway_rules`, `tax_rate_assignments`, `tax_rates`, `wms_pick_line_lots`, `wms_pick_lines`, `wms_pick_session_documents`, `wms_pick_sessions` | [versions](../../backend/app/modules/warehouse/migrations/versions/) |
| `equipment` | `audit_campaigns`, `audit_response_items`, `audit_responses`, `equipment_assignments`, `equipment_attachments`, `equipment_maintenance_logs` | [versions](../../backend/app/modules/equipment/migrations/versions/) |
| `example_widgets` | `example_widgets` | [versions](../../backend/app/modules/example_widgets/migrations/versions/) |
| `maker` | `maker_bom_lines`, `maker_module_settings`, `maker_production_order_lines`, `maker_production_orders`, `maker_recipe_cost_lines`, `maker_recipes` | [versions](../../backend/app/modules/maker/migrations/versions/) |
| `printing` | `print_agents`, `print_jobs` | [versions](../../backend/app/modules/printing/migrations/versions/) |
| `purchase_orders` | `po_partner_pricelist`, `po_reorder_rules`, `po_settings`, `purchase_order_lines`, `purchase_orders` | [versions](../../backend/app/modules/purchase_orders/migrations/versions/) |
| `recipes` | `ingredient_nutrition_defaults`, `meal_plan_entries`, `meal_plans`, `picking_session_items`, `picking_sessions`, `recipe_collection_members`, `recipe_collections`, `recipe_ingredients`, `recipe_tag_configs`, `recipes`, `shopping_exclusions`, `unit_conversions` | [versions](../../backend/app/modules/recipes/migrations/versions/) |
| `shopping_lists` | `shopping_list_history`, `shopping_list_items`, `shopping_lists` | [versions](../../backend/app/modules/shopping_lists/migrations/versions/) |
| `stock_takes` | `cycle_count_schedules`, `stock_take_closed_locations`, `stock_take_counts`, `stock_take_items`, `stock_takes` | [versions](../../backend/app/modules/stock_takes/migrations/versions/) |
| `webhooks` | `webhook_delivery_logs`, `webhook_endpoints` | [versions](../../backend/app/modules/webhooks/migrations/versions/) |

### Runtime-managed tables (excluded from Alembic)

| Module | Table | Created by | Reason |
|--------|-------|------------|--------|
| `nutrition` | `off_products_local` | `OFFBase.metadata.create_all(bind=products_engine)` at startup | Uses a separate `DeclarativeBase` (`OFFBase`) and separate database (`PRODUCTS_DATABASE_URL`). Alembic only tracks Core `Base.metadata`. |

### Core-owned tables (36 tables at the current head)

Core tables are owned by `backend/migrations/versions/`: the baseline plus
incremental revisions, not the baseline alone.

`ai_connections`, `ai_usage_logs`, `announcements`, `audit_log`, `categories`, `document_templates`, `email_jobs`, `event_deliveries`, `event_outbox`, `item_attachments`, `item_history`, `item_import_jobs`, `items`, `label_pool`, `location_relocations`, `module_installations`, `notifications`, `organization_invitations`, `organizations`, `partners`, `product_templates`, `registration_requests`, `roles`, `stock_anchors`, `stock_ledger_totals`, `stock_lots`, `stock_moves`, `stock_reservations`, `stock_valuation_layers`, `storage_locations`, `storage_types`, `system_settings`, `uom_categories`, `uoms`, `user_roles`, `users`.

The retired `stock_quants` table is not part of the current schema
(the archived `quantdrop01` dropped it); the `stock_quants_from_records` read view is
core-owned. Alembic's bookkeeping tables (`alembic_version` and
`alembic_version_<module>`) are excluded from the counts above. The nutrition
cache is listed separately because it lives in another database.

### Exceptions

| Module | Status | Reason |
|--------|--------|--------|
| `example_widgets` | Has its own migrations | Demo/reference module, not a required production feature. Has its own `migrations/versions/001_initial.py` (it is a normal module-migration setup, not a baseline exception). The `e4f5a6b7c8d9` core migration (archived with the previous chain) is also guarded with `to_regclass` for the table. |

## How to Add a New Table to a Module

1. **Define the model** in `app/modules/<module>/models.py` (or `models/` package),
   on the base the module SDK exports:
   ```python
   from app.core.module_sdk import CoreModelBase


   class NewThing(CoreModelBase):
       __tablename__ = 'new_things'
       ...
   ```

2. **Create a migration** in `app/modules/<module>/migrations/versions/`:
   ```bash
   # If this is the module's first table:
   # Copy the pattern from api_keys/migrations/versions/001_initial.py

   # If the module already has 001_initial.py, add a new revision:
   # 002_add_new_things.py
   ```

3. **Verify** the architecture linter passes:
   ```bash
   docker compose exec backend uv run python -m app.core.architecture_lint
   ```

4. **Verify** the table ownership test passes:
   ```bash
   docker compose exec backend uv run pytest -n 4 tests/integration/test_table_ownership.py -q --no-cov
   ```

**NEVER** add module table `create_table` calls to `migrations/versions/baseline_002_full_schema.py`.
The `test_table_ownership.py` test will block CI if you do.

## Existing Environment Migration (Stamp Procedure)

When deploying to an environment where module tables already exist (created by
the core baseline that preceded the module split), every `001_initial` is idempotent: its
`create_table` / `create_index` calls go through
`app/core/migration_helpers.py`, which skips what is already there. The
baseline no longer dies on `relation already exists`, and
`db upgrade-modules` stamps the module and carries on.

For manual stamping — before enabling a module, or to repair drift:

```bash
docker compose exec -T backend python manage.py db stamp-module webhooks 002_claimed_at
```

`stamp-module` verifies with `to_regclass` that the tables the target
revision's chain creates actually exist, and refuses otherwise. Stamping ahead
of the schema hides missing DDL until the first query fails. `--force`
overrides, for the case where the tables live under a different name.

## Drift Check (`db doctor`)

`backend/entrypoint.sh` runs `manage.py db doctor` inside the migration
advisory lock, before any migration. It compares every
`alembic_version_<module>` table against its migration chain and exits 1 on any
drift status in the table below. The schema *ahead* of the version table is
the state that crash-looped the backend, since the pending migration re-creates DDL that already exists and
`restart: unless-stopped` runs it again.

```bash
docker compose exec -T backend python manage.py db doctor
```

| Status | Drift? | Meaning |
|---|---|---|
| `ok` | no | version table at head |
| `pending` | no | behind head, and none of the pending DDL is in the database yet |
| `fresh` | no | no version row, no tables — a fresh install |
| `reconcilable` | no | baseline leftovers; `db upgrade-modules` stamps this itself |
| `schema_ahead` | **yes** | DDL from unapplied revisions already exists |
| `partial_schema` | **yes** | some of the module's tables exist, some do not |
| `unknown_revision` | **yes** | version table names a revision no migration file defines |

Each drift row prints the exact `db stamp-module` command that fixes it.

Two more lists follow the table and never fail the check: constraints still
`NOT VALID`, and columns whose live type differs from the type their model
declares (Alembic's `compare_type`, over every table that exists on both
sides). The second is how a database that grew through an older chain shows
itself — `timestamp without time zone` under a `DateTime(timezone=True)` model,
for one. The doctor runs before the migrations, so a pending revision may be
about to fix what it lists; a row that is still there after a restart is drift
no migration will repair.

`convert_naive_timestamps_to_utc` (`app/core/migration_helpers.py`) is the
repair for that timestamp case: core `tzaware01` (archived with the previous
chain) and one revision in each module chain except `example_widgets` pass it
the columns their models declare aware, and it alters
only those the database holds naive, reading the stored values as UTC.

## What a Revision May Import

A fresh installation replays every revision from the first, so a revision that
imports a model, a service or a seed list runs today's code against yesterday's
schema, and the first refactor of that code breaks installs that have nothing to
do with it. A revision (`migrations/versions/*.py`, core or module — not
`env.py`) therefore imports **nothing from `app` except the migration helpers**.
What it needs besides — a table's columns, a seed list, an inference map — it
freezes in its own file, as `tzaware01` does with its column list and `aiconn02`
does with its table definitions.

The helpers live in `app/core/migration_helpers.py`, and they are **frozen and
additive-only**: add a helper when a revision needs one, but never rename,
remove or change the behaviour of an existing public name — committed revisions
call them by name. A revision this repository ships imports them from
`app.core.migration_helpers`; a revision of a module installed from outside
imports the same names from `app.core.module_sdk`, because the install-time scan
refuses the internal path to a module it does not ship (see *The Declared Import
Surface* in `docs/MODULE_CAPABILITIES.md`). The test in *CI Guards* fails on a
stray import in this repository's chains and on a vanished helper.

## CI Guards

| Test | File | What it catches |
|------|------|-----------------|
| Table ownership | `tests/integration/test_table_ownership.py` | Module table accidentally added to core baseline |
| Round-trip | `tests/integration/test_module_migration_roundtrip.py` | Module migration upgrade/downgrade broken; schema/model mismatch in columns, indexes, unique constraints or FKs; `001_initial` not idempotent (auto-discovers new modules) |
| Drift detection | `tests/integration/test_migration_doctor_drift.py` | `db doctor` stops catching the crash-loop state, or starts flagging a fresh install |
| Architecture lint | `app/core/architecture_lint/` | Module with tables but no `versions/` directory |
| Frozen imports | `tests/unit/test_migrations_import_no_application_code.py` | A core or module revision importing from `app` other than `app.core.migration_helpers`; `migration_helpers` losing a public name or gaining one nobody froze |

## Core Migration Chain

The core chain starts with `baseline_002`, which builds the domain-neutral
schema, and `itemtypes01`, which removes the item-type table and
`items.item_type` before the first release. Later revisions add indexes,
item import jobs and ledger totals. Module tables stay
in their own chains and the baseline never creates one (`test_table_ownership`
enforces that). Objects the models cannot express — the audit trigger, the
stock guard, the quantities-from-records view, the trigram indexes — are
written by hand in the baseline, and the tests named in the migration section
of `CONTRIBUTING.md` keep them there.

A database created before v0.11.0 records a revision that no longer exists.
`manage.py db stamp-baseline` requires the previous chain's last revision and a
schema the models still recognize — short of what the module revisions still
pending in that database will close, since those chains run after the stamp: a
missing column one of them adds, a spare one it drops, a differing one it
alters, and the indexes and constraints they build; a revision that only alters
a column does not excuse that column missing — then stamps it onto `baseline_002`, from
where the core upgrade runs the remaining revisions;
`DEPLOYMENT.md` step 4b has the deploy procedure. The chain that came before
is kept in `migrations/versions_archive/` for reading.

## Reference Implementation

The `api_keys` module is the canonical reference for the module migration pattern:

- `app/modules/api_keys/migrations/env.py` — Alembic env.py per-module config
- `app/modules/api_keys/migrations/versions/001_initial.py` — initial migration
- `backend/tests/integration/test_module_migration_roundtrip.py` — round-trip test covering every module (auto-discovers them)

## Migration Module 001_initial.py Conventions

- `revision = '001_initial'`
- `down_revision = None`
- `branch_labels = ('<module_name>',)`
- `depends_on = None`
- Use `create_table_if_absent` / `create_index_if_absent` — from
  `app.core.migration_helpers` in this repository's modules, from
  `app.core.module_sdk` in a community module — instead of `op.create_table` /
  `op.create_index`.
  A baseline runs against schemas that may already contain its tables, and
  `test_module_migration_roundtrip.py::TestBaselineIsIdempotent` enforces it.
  **Only in `001_initial`** — later revisions carry real schema changes, and a
  guard there would turn a failed upgrade into a silent one.
- FKs to core tables (organizations, users, etc.) are inline — OK.
- FKs to other module tables are inline — OK.
- Downgrade drops tables in **reverse FK order** (child before parent).
- For modules extracted from baseline: include the **FINAL state** of all
  columns, not the state the baseline first created.
- **No native enum types.** An enumerated column is `varchar` with a
  `CHECK (<column> IN (...))` constraint, never `postgresql.ENUM` / `CREATE
  TYPE`. A label added to a native type later needs `ALTER TYPE ... ADD VALUE`,
  which cannot run in the migration's transaction; a text column's next label is
  a constraint swap. `test_no_native_enum_types_exist.py` enforces it.
