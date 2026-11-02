# Inventari Application Tests

This directory contains unit and integration tests for the Inventari application backend.
Tests run against a real **PostgreSQL** database inside Docker — not SQLite.

## Running Tests

### All Tests (preferred — parallel)

```bash
# From repo root (runs tests in container via Makefile)
make test

# Directly in Docker container — parallel execution
docker compose exec backend uv run pytest -n <N> -q   # N: what `python3 scripts/test-workers.py pytest` prints
```

### Unit Tests Only

```bash
docker compose exec backend uv run pytest tests/unit -v
```

### Integration Tests Only

```bash
docker compose exec backend uv run pytest tests/integration -v
```

### Single File

```bash
docker compose exec backend uv run pytest tests/integration/test_auth_api.py -v
```

### With Code Coverage

```bash
docker compose exec backend uv run pytest tests --cov=app --cov-report=html
```

### Makefile Options

```bash
make help               # Show help
make test               # Run all tests (parallel)
make test-unit          # Run unit tests only
make test-integration   # Run integration tests only
make test-coverage      # Run tests with code coverage
```

## Directory Structure

```
backend/
├── conftest.py                # Shared fixtures and pytest configuration (lives at backend/, not in tests/)
├── tests/                     # Cross-cutting core tests
│   ├── __init__.py
│   ├── README.md              # This file
│   ├── unit/                  # Tests that need no database (the few that do carry the integration marker)
│   │   └── ...                # No test_auth_service.py here — auth-service tests live in tests/integration/
│   └── integration/           # Integration tests (PostgreSQL)
│       ├── __init__.py
│       ├── test_auth_api.py    # Auth endpoints
│       ├── test_auth_service.py # Auth service (DB-touching, hence integration/)
│       ├── test_items_api.py   # Item endpoints
│       ├── test_storages_api.py
│       └── ...
└── app/modules/<module>/tests/   # Module-specific tests live alongside their module
    ├── integration/
    └── unit/

backend/tests/integration/file_storage/   # Subsystem test subpackage
└── test_file_storage_service.py
```

Note: the `tests/` directory has no conftest of its own — the core fixtures (`db_session`,
`client`, `real_async_client`, `test_user`, `auth_headers`, …) live in
`backend/conftest.py` at the backend project root; `tests/unit/`, `tests/integration/` and each
module's tests add conftests for fixtures of their own (see Fixtures).

## Requirements

Test dependencies are defined in [`pyproject.toml`](../pyproject.toml) under `[dependency-groups] dev`.
The full Docker environment must be running: `docker compose up -d`.

## Test Markers

- `@pytest.mark.unit` — tests that need no database (the marker decides, not the folder)
- `@pytest.mark.integration` — tests that hit PostgreSQL
- `@pytest.mark.slow` — tests skipped in fast runs
- `@pytest.mark.async_db` — tests that run against a real `AsyncSession` (asyncpg)
- `@pytest.mark.module('<name>')` — a test of one module; `app.core.module_test_plugin` creates its fixtures

They are registered in `pytest.ini`, which runs with `--strict-markers`: an unregistered marker fails the run.

```bash
# Skip slow tests
docker compose exec backend uv run pytest -n <N> -m "not slow"   # or: make test-fast
```

## Fixtures

The core fixtures are defined in **`backend/conftest.py`** (project root); pytest finds it
automatically. `tests/unit/conftest.py` and `tests/integration/conftest.py` add a few of their own
(`lint_of_a_scaffolded_copy`, `demo_world`), and each module's tests directory has a `conftest.py` defining that
module's fixtures. The lists below are the ones most tests reach for, not all of them.

### Database

- `db_session` — a SQLAlchemy session on the worker's PostgreSQL test database. Tests may commit; after the test every table it changed is emptied and the system seed replayed (`tests/_db_hygiene.py`). **Do not create your own DB sessions in tests.**
- `client` — `TestClient` wired to the FastAPI app, uses `db_session` (synchronous, but built on a real asyncpg engine)
- `real_async_client` — `httpx.AsyncClient` with a real `AsyncSession` (asyncpg), defined in `backend/conftest.py`. Use this for tests that need to exercise async endpoints against the real async driver. There is **no** `async_client` fixture — request `real_async_client` by name.

### Users & Auth

- `test_user` — a user with an organization, seeded fresh per test
- `test_user2` — a second user for isolation/cross-user tests
- `auth_headers` — `{"Authorization": "Bearer <token>"}` for `test_user`
- `auth_headers_user2` — same for `test_user2`

### Domain Fixtures

- `test_storage_location` — a storage location belonging to `test_user`'s org
- `test_category` — a category
- `test_item` — a single item
- `test_items_batch` — 5 items
- `test_stock_take` — a stock take with items (used in module-level tests; the stock-take module's tests live at `app/modules/stock_takes/tests/integration/`, not here)
- `test_household`, `test_storage_type`, `test_storage_type_fridge` — the organization and storage types the fixtures above stand on
- `real_async_db_session` and the `async_test_*` twins of the fixtures above — the same records through a real `AsyncSession`

## Writing New Tests

### Naming convention

```
Class: Test<Feature>
Method: test_<verb>_<subject>_<outcome>

Example: test_create_item_returns_201
         test_delete_item_not_found_returns_404
```

### Integration Test Template

```python
import pytest
from fastapi import status


@pytest.mark.integration
class TestItemsCreate:
    def test_create_item_success(self, client, auth_headers, test_storage_location):
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'New product',
                'location_id': str(test_storage_location.id),
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['name'] == 'New product'

    def test_create_item_unauthenticated_returns_401(self, client):
        response = client.post('/api/v1/items', json={'name': 'x'})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
```

### Module Test Location

New module tests go in `backend/app/modules/<module>/tests/integration/`. See `AGENTS.md` for the full testing convention.

## Troubleshooting

### Import errors

Always run tests **inside the container** — `docker compose exec backend uv run pytest`. Running outside the container will fail due to missing environment variables and package resolution.

### Database errors

Tests require the full Docker stack (`docker compose up -d`). The `db_session` fixture handles PostgreSQL transactions automatically.

1. Check that `db_session` (not a raw `Session`) is injected in the test
2. Check that `@pytest.mark.integration` is present on DB-touching tests

### Auth errors (401)

1. Use the `auth_headers` fixture, not a hardcoded token
2. Ensure `test_user` fixture is included (it creates the user + org)

## Additional Resources

- [pytest Documentation](https://docs.pytest.org/en/stable/)
- [FastAPI Testing Documentation](https://fastapi.tiangolo.com/tutorial/testing/)
- [AGENTS.md](../../AGENTS.md) — full testing conventions for this project

- [pytest-cov Documentation](https://pytest-cov.readthedocs.io/)