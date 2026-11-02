# CLI Reference

Inventari ships with a unified management CLI — `backend/manage.py` — built on
[Typer](https://typer.tiangolo.com/). It replaces the old scattered scripts
with a single, documented entry point.

```bash
docker compose exec backend uv run python manage.py --help
```

That is the development form. The production image has no project virtualenv to
`uv run` into — its dependencies are installed system-wide — so there the same
command is `docker compose -f docker-compose.prod.yml exec backend python manage.py …`,
as `DEPLOYMENT.md` writes it. Every command below is given without that prefix.

### `db` — Database Management

| Command | Description |
|---------|-------------|
| `manage.py db upgrade [revision]` | Apply core Alembic migrations (default: `head`); upgrading to `head` also applies the per-module migrations, as `upgrade-modules` does |
| `manage.py db upgrade-modules` | Apply per-module Alembic migrations (`alembic_version_<module>` chains) |
| `manage.py db doctor` | Check every module's version table against its migration chain (exit 1 on drift) |
| `manage.py db stamp-module <module> <revision> [--yes] [--force]` | Record a revision in a module's version table without running its migrations. It asks first (`--yes`/`-y` skips the question) and refuses when the revision's tables are missing (`--force` stamps anyway) |
| `manage.py db stamp-baseline` | Stamp a database created before v0.11.0 onto the flattened core chain, after checking its schema against the models (see `DEPLOYMENT.md`) |
| `manage.py db downgrade <revision>` | Roll back to a revision (development, test or staging installs only — see below) |
| `manage.py db migrate "<message>"` | Auto-generate a new core migration from the model changes; writes nothing when no model changed. Read the file before applying it |
| `manage.py db seed [--profile PROFILE] [--org ORG] [--insert-only / --overwrite]` | Seed system data. Profiles: `clean_core`, `food_home`, `equipment_wms`. Without `--org` it uses the only organization when exactly one exists; with none it seeds installation-wide data (units of measure) and says so; with more than one it refuses and asks for `--org`. Insert-only is the default — existing rows are left untouched; `--overwrite` refreshes them |
| `manage.py db check-reservations` | Compare what the records put on each shelf with what documents promise there (exit 1 where the promises exceed the records) |
| `manage.py db reset [--yes-i-am-sure]` | **DESTRUCTIVE** — terminates the other connections, then drops the `public` schema and creates it empty; run `db upgrade` afterwards (development, test or staging installs only — see below) |

> `db reset` and `db downgrade` run only on an install that says its data may go: `DEBUG` or `TESTING` on, or `INVENTARI_ENV` set to `development` or `staging` — the `ENVIRONMENT` alias answers wherever `INVENTARI_ENV` is read (see `.env.example`). The production compose turns `DEBUG` off and sets no `INVENTARI_ENV`, so a production install is refused without having to say so; one that says `production` on either name is refused even with `DEBUG` on. The refusal says what it read (`DEBUG`, `TESTING` and `INVENTARI_ENV`, or that the install says `production`/`prod`), exits 1 and touches nothing.
>
> `db reset` also asks for confirmation: you must type the database name. In CI, pass `--yes-i-am-sure` to skip the prompt (the install check is never skipped).

### `user` — User Management

| Command | Description |
|---------|-------------|
| `manage.py user create-admin --email E --password P [--name N] [--allow-weak-password] [--no-instance-superuser]` | Create an admin account with its own organization, or reset the password of an existing one (which also invalidates its earlier sessions and exits 1 if Redis cannot be reached to do so). The first account on an instance becomes its superuser unless `--no-instance-superuser` is given. `--name` defaults to `Administrator` |

```bash
docker compose exec backend uv run python manage.py user create-admin \
  --email admin@example.com \
  --password ChangeMe123 \
  --name "Admin"
```

The password must be at least 8 characters with an uppercase letter, a lowercase letter and a digit; `--allow-weak-password` lifts the production refusal of the known-weak seed passwords (the `Admin123` the bootstrap uses heads that list) for a throwaway stack.

### `module` — Module Management

| Command | Description |
|---------|-------------|
| `manage.py module create <name>` | Scaffold a new in-tree module directory |
| `manage.py module install <source> [--rev REV] [--signature FILE] [--allow-unsigned]` | Install a community module from a local path or git URL; a git source needs `--rev`, and a package with no signature is refused unless `--allow-unsigned` |
| `manage.py module upgrade <source> [--rev REV] [--signature FILE] [--allow-unsigned] [--force]` | Upgrade an installed community module to a newer package — files replaced, its migrations run, data left alone |
| `manage.py module sign <source> --key <file> --key-id <id>` | Sign a community module package (Ed25519) so installers can verify it |
| `manage.py module uninstall <name> [--force] [--drop-data]` | Remove a previously installed community module. Its data is kept unless `--drop-data` (which asks you to type `data`, unless `--force`) |
| `manage.py module new-community <name> [-o DIR] [-l pl -l de]` | Scaffold a standalone community module package for distribution in `DIR` (default: the current directory); English catalogs only unless `-l` asks for more of the core's languages (`pl`, `de`, `fr`, `es`) |
| `manage.py module validate [--module NAME] [--base-path DIR] [--allow-core]` | AST-validate manifests and import safety |
| `manage.py module smoke <name> [--base-path DIR]` | Run comprehensive smoke test on a single module (manifest, i18n, frontend hookup) |
| `manage.py module schema` | Print the manifest.json JSON Schema (for IDE config) |
| `manage.py module list [--json]` | List all registered modules and their status |

### `arch` — Architecture Linting

| Command | Description |
|---------|-------------|
| `manage.py arch lint [--quiet] [--baseline FILE]` | Check module boundary imports and CQRS rules |
| `manage.py arch lint --write-baseline` | Accept current violations as baseline |
| `manage.py arch lint --update-contracts-snapshot` / `--update-core-api-snapshot` / `--update-module-sdk-snapshot` | Regenerate the committed contract, `core_api` surface and module SDK snapshots (to check against another file instead, pass `--contracts-snapshot FILE`, `--core-api-snapshot FILE` or `--module-sdk-snapshot FILE`) |
| `manage.py arch lint --write-rejection-ledger` / `--write-baseline-sizes` | Regenerate the rejection-sentence ledger / record the size of every suppression list |

### `audit` — Dependency Licences

| Command | Description |
|---------|-------------|
| `manage.py audit scan-dependencies [--skip-frontend] [--write [--output FILE]]` | Check the licence of every dependency the manifests resolve to (backend + frontend; exit 1 on a blocked licence). `--write` regenerates `THIRD_PARTY_LICENSES.md`; `--backend-dir` / `--frontend-dir` point at other trees |

### `backfill` — One-shot Data Backfills

| Command | Description |
|---------|-------------|
| `manage.py backfill stock-moves [--dry-run] [--batch-size N]` | Translate `ItemHistory` → `StockMove` for WMS organizations (idempotent) |
| `manage.py backfill category-emoji` | Populate `Category.emoji` for high-confidence keyword matches (dry-run by default; pass `--apply` to commit) |
| `manage.py backfill rebind-module-secrets` | Bind module settings secrets to the module that owns them (dry-run by default; pass `--apply` to write) |

### `secrets` — Stored Secrets

| Command | Description |
|---------|-------------|
| `manage.py secrets reencrypt [--apply]` | Re-encrypt every stored secret under the current key after changing `ENCRYPTION_KEY` (or `SECRET_KEY` on an install without one), with the old key in `PREVIOUS_ENCRYPTION_KEY`. Dry run by default; exit code 1 when a value no known key opens |

### `demo` — Demo Instance

| Command | Description |
|---------|-------------|
| `manage.py demo reset [--items N] [--email E] [--password P]` | Rebuild the demo instance from scratch — **destructive**, refused anywhere that is not a demo instance: `INVENTARI_DEMO=true` must be set and the install must not say `production` (see [DEMO.md](DEMO.md)) |
| `manage.py demo fill-pool [--items N] [--size N]` | Seed visitors' sandboxes until the pool holds enough; run by the demo-reset loop |

### `qa` — QA Fixtures

| Command | Description |
|---------|-------------|
| `manage.py qa fixture [--variant empty\|one\|many\|all] [--profile PROFILE] [--items N] [--password P] [--reset] [--yes]` | Provision the empty / one / many QA organizations for testing the app by hand (default: all three, profile `equipment_wms`); `--reset` wipes them first |
| `manage.py qa reset <variant> [--yes]` | Clear one QA organization without rebuilding it |

> The `qa` group goes through the same install check as `db reset`: every account it creates has a known password.

### `shell` — Interactive Shell

```bash
docker compose exec backend uv run python manage.py shell
```

Opens an IPython REPL (falls back to the standard Python console) with:
- `db` — pre-configured SQLAlchemy session
- All SQLAlchemy models auto-imported into scope

### Makefile shortcuts

These `make` targets wrap `manage.py` (the exceptions are marked); `make help` lists every target, including the ones that run tests and linters rather than this CLI:

```bash
make shell                       # manage.py shell
make db-upgrade                  # manage.py db upgrade (core, then modules)
make db-migrate m="description"  # manage.py db migrate "description"
make db-reset                    # manage.py db reset --yes-i-am-sure + upgrade
make db-seed                     # manage.py db seed
make db-seed-clean               # db reset --yes-i-am-sure + upgrade + seed
make db-seed-demo                # seed demo items, suppliers, warehouse hierarchy (runs seed_demo_data.py, not manage.py)
make demo-reset                  # manage.py demo reset (with INVENTARI_DEMO=true)
make off-import FILE=…           # not manage.py: python -m app.modules.nutrition.import_parquet, see OFF_DATABASE_SETUP.md
make lint-architecture           # manage.py arch lint
make validate-module             # manage.py module validate
make module-smoke name=<module>  # manage.py module smoke <module>
make new-module                  # manage.py module create, then the frontend scaffold and the catalog/API snapshot sync
make new-community-module        # manage.py module new-community
make create-admin email=… password=… name=…  # manage.py user create-admin
```

---

[← Back to the README](../README.md)
