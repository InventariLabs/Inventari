from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.modules.stock_takes.models  # noqa: F401 — resolve Item.stock_take_items mapper
from app.config import settings
from app.models.organization import Organization
from app.models.storage_type import StorageType

# Use the same per-worker test DB the conftest seeds via setup_test_db.
# settings.DATABASE_URL is set to TEST_DATABASE_URL in conftest.py (with
# PYTEST_XDIST_WORKER suffix when running under xdist), and setup_test_db
# rebuilds the public schema in that DB from the current models. Hitting the
# un-suffixed 'inventari_test' database here would target a stale schema
# left over from before the most recent model migrations.
ASYNC_URL = settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


@pytest.fixture(scope='session', autouse=True)
def _ensure_async_smoke_schema(setup_test_db):
    """Make the per-worker test DB exist before any async smoke test runs.

    Provisioning — database, current schema, seed snapshot — lives in
    conftest's ``setup_test_db``, and it fires only when a test asks for it.
    The async smoke tests build their own engines and ask for nothing, so on
    a worker whose first test lives in this file the database was never
    created: the bridge used to run ``create_all`` directly, which builds
    tables only in a database that already exists, and the run died with
    "database does not exist" under whichever tests crossed that worker.
    Asking for the fixture is the whole bridge. The name stays: this module
    is the one that must never find an empty schema.
    """
    return None


def make_engine():
    return create_async_engine(ASYNC_URL, echo=False, poolclass=NullPool)


@pytest.mark.integration
@pytest.mark.async_db
async def test_async_session_select():
    engine = make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        result = await session.scalar(text('SELECT 1'))
        assert result == 1
    await engine.dispose()


@pytest.mark.integration
@pytest.mark.async_db
async def test_async_session_insert_rollback():
    engine = make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        st = StorageType(name='AsyncRollbackTest', type_code='ASYNC_RB', icon='Test')
        session.add(st)
        await session.flush()

        stmt = select(StorageType).where(StorageType.type_code == 'ASYNC_RB')
        found = await session.scalar(stmt)
        assert found is not None
        assert found.name == 'AsyncRollbackTest'

        await session.rollback()

        gone = await session.scalar(stmt)
        assert gone is None
    await engine.dispose()


@pytest.mark.integration
@pytest.mark.async_db
async def test_async_session_org_insert_rollback():
    engine = make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        org = Organization(name='Async Test Org', enabled_modules=['core'])
        session.add(org)
        await session.flush()

        stmt = select(Organization).where(Organization.name == 'Async Test Org')
        found = await session.scalar(stmt)
        assert found is not None

        await session.rollback()

        gone = await session.scalar(stmt)
        assert gone is None
    await engine.dispose()


@pytest.mark.integration
@pytest.mark.async_db
async def test_async_session_count_existing_data():
    engine = make_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        r = await session.scalar(text('SELECT count(*) FROM storage_types'))
        assert r is not None
        assert isinstance(r, int)
    await engine.dispose()


@pytest.mark.integration
@pytest.mark.async_db
async def test_real_async_client_health(real_async_client, auth_headers):
    resp = await real_async_client.get('/api/v1/locations', headers=auth_headers)
    assert resp.status_code == 200


@pytest.mark.integration
@pytest.mark.async_db
async def test_real_async_client_list_items(real_async_client, auth_headers, test_item):
    resp = await real_async_client.get('/api/v1/items', headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert 'items' in data or len(data) > 0


@pytest.mark.integration
@pytest.mark.async_db
async def test_real_async_client_get_item(real_async_client, auth_headers, test_item):
    resp = await real_async_client.get(
        f'/api/v1/items/{test_item.id}', headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()['name'] == 'Pork Loin'


@pytest.mark.integration
@pytest.mark.async_db
async def test_real_async_client_consume_item(
    real_async_client, auth_headers, test_item
):
    resp = await real_async_client.patch(
        f'/api/v1/items/{test_item.id}/consume',
        json={'quantity': 1},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert Decimal(resp.json()['quantity']) == 1


@pytest.mark.integration
@pytest.mark.async_db
async def test_real_async_client_stats_overview(
    real_async_client, auth_headers, test_item
):
    resp = await real_async_client.get('/api/v1/stats/overview', headers=auth_headers)
    # `stats` is in ALWAYS_ON_MODULES and this endpoint carries no
    # require_module, so there is no 404 to accept: were the gate there, a
    # refusal would arrive as 403.
    assert resp.status_code == 200


@pytest.mark.integration
@pytest.mark.async_db
async def test_real_async_client_create_storage(
    real_async_client,
    auth_headers,
    test_user,
):
    payload = {
        'name': 'Async Test Storage',
        'location_type_id': None,
        'description': 'Created via async client',
    }
    resp = await real_async_client.post(
        '/api/v1/locations', json=payload, headers=auth_headers
    )
    assert resp.status_code == 201


@pytest.mark.integration
@pytest.mark.async_db
async def test_real_async_client_delete_item(
    real_async_client, auth_headers, test_item
):
    resp = await real_async_client.delete(
        f'/api/v1/items/{test_item.id}', headers=auth_headers
    )
    assert resp.status_code in [200, 204]
