# Module Template

There are two ways to start a module. An in-tree module is reviewed code that
this repository ships: `make new-module`, steps below. A community module is a
separate package for distribution: `make new-community-module NAME=<name>`
(see [MODULE_QUICKSTART.md](../MODULE_QUICKSTART.md), Path B).

Minimal flow for an in-tree module:

1. Generate the scaffold (from the project root):

```bash
make new-module NAME=your_module_name
```

This creates the backend and frontend scaffolds from `example_widgets`, adds the
name to `REPO_SHIPPED_MODULES` in `backend/app/core/module_safety.py`, syncs the
module catalog and i18n key snapshots, and regenerates `docs/api/openapi.json`
and the API types. For the backend scaffold alone:
`docker compose exec backend uv run python manage.py module create your_module_name`.

2. Update `manifest.json`:
   - `name` must match directory name,
   - `version` should follow semver,
   - `capabilities` is a list drawn from `network`, `filesystem`, `process` and
     `database`; any other value fails validation.

3. Keep imports module-safe:
   - do not import `app.models.*` directly,
   - use public Core API and DTO contracts.

4. Validate locally:

```bash
make validate-module
```

5. Run backend tests:

```bash
make test-backend
```
