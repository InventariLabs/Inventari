# Inventari: Module Testing Guide

How to write and run tests for your Inventari module.

## Quick Start

```bash
# Run all tests for your module
docker compose exec backend uv run pytest app/modules/my_module/ -v

# Run with parallel execution (recommended; `python3 scripts/test-workers.py pytest`
# prints the worker count for your machine)
docker compose exec backend uv run pytest app/modules/my_module/ -n 4 -v

# Run a specific test file
docker compose exec backend uv run pytest app/modules/my_module/tests/integration/test_my_module_api.py -v
```

Tests live in your working tree only. `module install` drops every `tests/`
directory before copying anything — on both halves, `backend/` and `frontend/`
alike — so a module you ship never carries its tests, and a module you
installed has no tests directory to run. The frontend half matters as much as
the backend one: `npm run test:run` collects `**/*.{test,spec}.*` from the whole
tree, so a test file that shipped with a module would execute in node, with the
file system, on the machine of whoever ran the suite.

The install says what it dropped, path by path. If your fixtures or a vendored
library sit in a directory named `tests`, they are the workbench too: move them
somewhere else, or they will not be there after the install.

Keep them, run them: they are your workshop; they just never ship.

## Running a community package's tests

A package in its own repository keeps its tests the same way — under
`backend/tests/`, where the scaffold writes them — and none of them ever
installs, so there is never a copy inside the checkout to run. To execute the
package's own backend tests, and to type check its frontend half, against a
development checkout, the package's two halves are staged into that checkout
for the length of the run and taken away again.

Staging happens while the backend is down. The development backend reloads
itself the moment files appear under `backend/app/modules/`, and every load
installs or upgrades whatever module the tree carries — a
`module_installations` row, the module's migrations, its `on_upgrade` hook —
against the development database. A backend container start is the same story:
`entrypoint.sh` runs `db upgrade-modules` over every module in the tree before
the app boots, and the boot installs or upgrades whatever it finds there. So
the backend stops before the first file moves, the test run itself starts a
container with its entrypoint bypassed, and the backend comes back only once
the tree holds what it held before.

Start in your package repository, with your Inventari stack running
(`docker compose up -d`):

<!-- testing-guide-check: community-loop -->
```bash
PKG=$(pwd)                 # your package repository
INV=/path/to/inventari     # a development checkout of Inventari
NAME=warranty_tracker      # your module's name
cd "$INV"

# 1. Stop the backend before any file moves.
docker compose stop backend

# 2. Stage the package's two halves into the checkout. Whatever sits at
#    these paths — an installed copy of this module — is parked in /tmp
#    and comes back in step 4; it must never be overwritten. A park that
#    is already there belongs to an interrupted earlier run or to another
#    checkout: mv would move this module *inside* it, and step 4 would
#    then restore that other copy as this one. So both paths are checked
#    first, and nothing is moved while either is taken.
for park in "/tmp/$NAME.installed-backend" "/tmp/$NAME.installed-frontend"; do
  if [ -e "$park" ]; then
    echo "Refusing to stage: $park already exists — it holds a copy parked by" >&2
    echo "an earlier run or another checkout, and nothing has been moved. The" >&2
    echo "backend is stopped: move that copy back into the checkout it came" >&2
    echo "from (or delete it if it is stale), start the backend, then run again." >&2
    exit 1
  fi
done
[ -d backend/app/modules/$NAME ] && mv backend/app/modules/$NAME "/tmp/$NAME.installed-backend"
[ -d frontend/src/modules/$NAME ] && mv frontend/src/modules/$NAME "/tmp/$NAME.installed-frontend"
cp -R "$PKG/backend" backend/app/modules/$NAME
cp -R "$PKG/frontend" frontend/src/modules/$NAME

# 3. The package's own backend tests, and the frontend type check across
#    the staged half — tsconfig.json includes all of frontend/src/.
#    The test container's entrypoint is bypassed: it would migrate every
#    module the tree carries, which is what step 1 stopped the backend to
#    avoid. pytest builds and uses its own test databases.
docker compose run --rm --entrypoint uv backend run pytest app/modules/$NAME -n 4 -q
docker compose exec frontend npx tsc --noEmit

# 4. Take the staged copy away, put back what step 2 parked, start the backend.
rm -rf backend/app/modules/$NAME frontend/src/modules/$NAME
[ -d "/tmp/$NAME.installed-backend" ] && mv "/tmp/$NAME.installed-backend" backend/app/modules/$NAME
[ -d "/tmp/$NAME.installed-frontend" ] && mv "/tmp/$NAME.installed-frontend" frontend/src/modules/$NAME
docker compose start backend
```

The package's own frontend specs live in `frontend/tests/` (the installer drops
that folder, like `backend/tests/`) and run in the same window, between steps 3
and 4, against the staged half:

```bash
docker compose exec frontend npx vitest run --experimental.fsModuleCache=false src/modules/$NAME
```

The flag matters: the test setup collects every module's catalogs with a glob,
and Vitest's on-disk module cache keeps the result of an earlier run, so a
package staged afterwards is missing from it and every translated text renders
as its key.

These are the checks a package runs: `module validate`, its own backend tests,
its own frontend specs and the staged `npx tsc --noEmit`. The repository's
`make lint` and `make check-frontend`, and the checks inside them (for example
`check:invalidation`, the i18n key snapshots and the schema test that reads
only Core's metadata), read the checkout's tree and are not written for a
package; a failure there that points at Core files is not the package's to fix.

Run from start to finish, it changes nothing it should not: the staged files
exist only while no backend process can see them, the test run writes only its
own test databases, and the backend comes back up on the tree it recognized —
an installed copy of the module and the development database are as they were.
Step 2 refuses to move anything while either park path is already taken, so the
copy this run would park can never be dropped inside a park left behind by an
earlier one and restored later as this module's: a second checkout, or a loop
left half finished, stops at the refusal with every file where it was.
Interrupted between steps 2 and 4, the copy parked in `/tmp` is still there:
move it back into place by hand and start the backend — every later run
refuses until it is back, instead of staging over it.

## Test Structure

```
app/modules/my_module/
└── tests/
    ├── __init__.py
    └── integration/
        ├── __init__.py
        ├── conftest.py          # Module-specific fixtures
        └── test_my_module_api.py
```

A community package keeps its tests under `backend/tests/`, and
`module new-community` starts it with one test:

```
backend/tests/
├── __init__.py
└── test_records.py              # keeps a row in the module's own table
```

The tests run against the platform's test databases, one per worker. Besides
the core's tables, each holds the tables of every module whose models are
imported — a community module's too, built from its `ModuleModelBase`
metadata — and every other table is emptied between tests; the three system-data
tables (units of measure and categories) are put back to the snapshot the worker
starts from. The module's migration chain is not run for them, so a constraint
that only a migration declares, one the model leaves out, is not enforced in a
test.

## Fixtures

### Common Fixtures (from root `conftest.py`)

The root `backend/conftest.py` defines more fixtures than this table lists (for
example `test_user2`, `test_item`, `test_storage_location` and `auth_headers_user2`).
These six are available in every backend test:

| Fixture | Description |
|---------|-------------|
| `db_session` | Sync SQLAlchemy session, auto-cleared between tests |
| `client` | FastAPI `TestClient` with dependency overrides |
| `real_async_client` | `httpx.AsyncClient` with real async session |
| `test_household` | Test organization |
| `test_user` | Admin user in test organization |
| `auth_headers` | JWT auth headers for `test_user` |

### Module-Specific Fixtures

Create a `conftest.py` in your test directory to set up module-specific state:

```python
"""Fixtures for my_module integration tests."""

import pytest
from sqlalchemy.orm import Session

# Ensure model is registered in Base.metadata
import app.modules.my_module.models  # noqa: F401


@pytest.fixture
def my_org(db_session: Session):
    """Organization with my_module enabled."""
    from app.models.organization import Organization

    org = Organization(
        name='My Test Org',
        enabled_modules=['core', 'items', 'locations', 'categories', 'my_module'],
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def my_user(db_session: Session, my_org):
    """User in my org."""
    from app.models.user import User
    from app.services.token_service import get_password_hash

    user = User(
        email='my-test@example.com',
        hashed_password=get_password_hash('testpassword123'),
        full_name='Test User',
        organization_id=my_org.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def my_auth(my_user):
    """Auth headers for my user."""
    from app.services.token_service import create_access_token

    token = create_access_token(data={'sub': str(my_user.id)})
    return {'Authorization': f'Bearer {token}'}
```

> **Important:** Always import your model at the top of `conftest.py` to ensure
> it's registered in the metadata `setup_test_db` builds its tables from before it
> runs (`Base.metadata`; a community module's models use `ModuleModelBase.metadata`).

## Writing Tests

### API Tests (Recommended Pattern)

```python
"""Integration tests for my_module API."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
class TestMyModuleAPI:
    def test_list_empty(self, client: TestClient, my_auth):
        resp = client.get('/api/v1/my-module', headers=my_auth)
        assert resp.status_code == 200
        # A list answers with the pagination envelope, not a bare array.
        assert resp.json()['items'] == []
        assert resp.json()['total'] == 0

    def test_create(self, client: TestClient, my_auth):
        resp = client.post(
            '/api/v1/my-module',
            json={'name': 'Test Item'},
            headers=my_auth,
        )
        assert resp.status_code == 201
        assert resp.json()['name'] == 'Test Item'

    def test_get_nonexistent_returns_404(self, client: TestClient, my_auth):
        resp = client.get(f'/api/v1/my-module/{uuid4()}', headers=my_auth)
        assert resp.status_code == 404
```

### Multi-Tenancy Tests

Always verify that data is isolated between organizations:

```python
@pytest.mark.integration
class TestMultiTenancy:
    # `other_auth` is a fixture you add beside `my_auth`: the same shape, for a
    # user of a second organization.
    def test_isolated_by_org(self, client: TestClient, my_auth, other_auth):
        # Create in org A
        client.post('/api/v1/my-module', json={'name': 'A Item'}, headers=my_auth)

        # Org B sees nothing
        resp = client.get('/api/v1/my-module', headers=other_auth)
        assert resp.status_code == 200
        assert resp.json()['items'] == []
```

### DB Verification Tests

When you need to verify database state directly:

```python
def test_create_persists(self, client: TestClient, my_auth, db_session: Session):
    from app.modules.my_module.models import MyModel

    resp = client.post('/api/v1/my-module', json={'name': 'Test'}, headers=my_auth)
    assert resp.status_code == 201
    item_id = resp.json()['id']

    # Verify in DB
    item = db_session.query(MyModel).filter_by(id=item_id).first()
    assert item is not None
    assert item.name == 'Test'
```

## Markers

| Marker | Purpose |
|--------|---------|
| `@pytest.mark.integration` | DB-touching tests, always use for integration tests |
| `@pytest.mark.unit` | Pure logic tests, no DB |
| `@pytest.mark.slow` | Slow tests; deselect them with `-m "not slow"` |
| `@pytest.mark.async_db` | Tests that exercise a real `AsyncSession` on asyncpg |
| `@pytest.mark.module('name')` | Module-specific tests: adds the fixtures `module_org`, `module_user`, `module_auth_headers` and `module_client` for `name` |

## Common Pitfalls

1. **Forgetting model import in conftest** — Tables won't be created, and the first query against one fails with a database error about a missing relation, not with a 404.
2. **Expecting `real_async_client` to see uncommitted setup** — each request gets its own async session on its own connection and commits at the end, so one request's writes are visible to the next. What a request cannot see is data the sync `db_session` added in the test and did not commit: commit setup before the first request (the standard fixtures do).
3. **Not enabling module** — The test org must include your module in `enabled_modules`.
4. **Hardcoded org IDs** — Always use fixture-provided org/user, never hardcode UUIDs.

## Running Full Suite

```bash
# All backend tests
docker compose exec backend uv run pytest -n 4 -q

# Frontend tests
cd frontend && npm run test:run

# Lint: the commit hook (installed by `make setup-hooks`) runs ruff format and
# ruff check over the whole tree on every commit, so do not run them by hand.
make lint
```

## See Also

- [MODULE_QUICKSTART.md](../MODULE_QUICKSTART.md) — 5-minute quickstart (entry point)
- [MODULES_GUIDE.md](../MODULES_GUIDE.md) — full reference & CoreAPI
- [MODULE_ADVANCED_GUIDE.md](MODULE_ADVANCED_GUIDE.md) — interceptors, event bus
