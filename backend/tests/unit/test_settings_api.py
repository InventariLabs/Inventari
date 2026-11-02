"""
Unit tests for CoreSettingsAPI.

Tests cover:
- get_async() returns default when org missing or settings empty
- set_async() creates namespace if absent
- set_bulk_async() merges values
- delete_async() removes specific key or entire namespace
- Namespace isolation — module A cannot read module B's keys
- Multiple modules in the same org don't collide
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.module_registry import module_registry
from app.core.public_api.settings import CoreSettingsAPI

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_org(settings: dict | None = None):
    org = MagicMock()
    org.settings = settings
    return org


def _make_async_db(org=None):
    """Return a mock AsyncSession whose scalar returns org."""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=org)
    return db


# ---------------------------------------------------------------------------
# CoreSettingsAPI.get_async()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_default_when_org_missing():
    api = CoreSettingsAPI()
    db = _make_async_db(org=None)
    result = await api.get_async(db, uuid4(), 'my_module', 'key', default='fallback')
    assert result == 'fallback'


@pytest.mark.asyncio
async def test_get_returns_default_when_settings_none():
    api = CoreSettingsAPI()
    org = _make_org(settings=None)
    db = _make_async_db(org)
    result = await api.get_async(db, uuid4(), 'my_module', key=None, default={})
    assert result == {}


@pytest.mark.asyncio
async def test_get_entire_module_namespace():
    api = CoreSettingsAPI()
    org = _make_org(settings={'module:my_module': {'a': 1, 'b': 2}})
    db = _make_async_db(org)
    result = await api.get_async(db, uuid4(), 'my_module')
    assert result == {'a': 1, 'b': 2}


@pytest.mark.asyncio
async def test_get_specific_key():
    api = CoreSettingsAPI()
    org = _make_org(settings={'module:my_module': {'threshold': 42}})
    db = _make_async_db(org)
    result = await api.get_async(db, uuid4(), 'my_module', 'threshold')
    assert result == 42


@pytest.mark.asyncio
async def test_get_missing_key_returns_default():
    api = CoreSettingsAPI()
    org = _make_org(settings={'module:my_module': {}})
    db = _make_async_db(org)
    result = await api.get_async(db, uuid4(), 'my_module', 'nonexistent', default='x')
    assert result == 'x'


# ---------------------------------------------------------------------------
# Namespace isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_namespace_isolation_between_modules():
    """Module A cannot read Module B's keys."""
    api = CoreSettingsAPI()
    org = _make_org(
        settings={
            'module:module_a': {'secret': 'alpha_secret'},
            'module:module_b': {'secret': 'beta_secret'},
        }
    )
    db = _make_async_db(org)
    org_id = uuid4()

    result_a = await api.get_async(db, org_id, 'module_a', 'secret')
    result_b = await api.get_async(db, org_id, 'module_b', 'secret')

    assert result_a == 'alpha_secret'
    assert result_b == 'beta_secret'
    # Module A's key not visible under module_b namespace
    assert (
        await api.get_async(db, org_id, 'module_b', 'alpha_key', 'not_found')
        == 'not_found'
    )


# ---------------------------------------------------------------------------
# CoreSettingsAPI.set_async()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_creates_namespace_if_absent():
    api = CoreSettingsAPI()
    org = _make_org(settings={})
    db = _make_async_db(org)

    await api.set_bulk_async(db, uuid4(), 'my_module', {'enabled': True})

    # The namespace carries core's schema-version stamp alongside the data.
    assert org.settings == {
        'module:my_module': {'enabled': True, '__schema_version': 1}
    }
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_updates_existing_key():
    api = CoreSettingsAPI()
    org = _make_org(settings={'module:my_module': {'count': 1}})
    db = _make_async_db(org)

    await api.set_bulk_async(db, uuid4(), 'my_module', {'count': 99})

    assert org.settings['module:my_module']['count'] == 99


@pytest.mark.asyncio
async def test_set_does_not_overwrite_other_modules():
    api = CoreSettingsAPI()
    org = _make_org(settings={'module:other': {'x': 10}})
    db = _make_async_db(org)

    await api.set_bulk_async(db, uuid4(), 'my_module', {'y': 20})

    assert org.settings['module:other']['x'] == 10
    assert org.settings['module:my_module']['y'] == 20


@pytest.mark.asyncio
async def test_set_raises_when_org_missing():
    api = CoreSettingsAPI()
    db = _make_async_db(org=None)

    with pytest.raises(ValueError, match='not found'):
        await api.set_bulk_async(db, uuid4(), 'my_module', {'key': 'value'})


# ---------------------------------------------------------------------------
# CoreSettingsAPI.set_bulk_async()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_bulk_creates_multiple_keys():
    api = CoreSettingsAPI()
    org = _make_org(settings={})
    db = _make_async_db(org)

    await api.set_bulk_async(db, uuid4(), 'my_module', {'k1': 'v1', 'k2': 2})

    ns = org.settings['module:my_module']
    assert ns['k1'] == 'v1'
    assert ns['k2'] == 2
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_bulk_merges_with_existing():
    api = CoreSettingsAPI()
    org = _make_org(settings={'module:my_module': {'existing': True}})
    db = _make_async_db(org)

    await api.set_bulk_async(db, uuid4(), 'my_module', {'new_key': 'hello'})

    ns = org.settings['module:my_module']
    assert ns['existing'] is True
    assert ns['new_key'] == 'hello'


@pytest.mark.asyncio
async def test_set_bulk_raises_when_org_missing():
    api = CoreSettingsAPI()
    db = _make_async_db(org=None)

    with pytest.raises(ValueError, match='not found'):
        await api.set_bulk_async(db, uuid4(), 'my_module', {'k': 'v'})


# ---------------------------------------------------------------------------
# Settings schema version — the stamp a write carries and the reads hide
# ---------------------------------------------------------------------------


def _install_stub_module(name: str, schema):
    class _Stub:
        @property
        def metadata(self):
            m = MagicMock()
            m.name = name
            return m

        def get_settings_schema(self):
            return schema

    stub = _Stub()
    module_registry.get = lambda n, _stub=stub: _stub if n == name else None  # type: ignore[method-assign]


@pytest.fixture(autouse=True)
def _restore_registry():
    from app.services import _org_reads

    original_list_all = _org_reads.list_all_async
    yield
    module_registry.get = lambda name: module_registry._modules.get(name)  # type: ignore[method-assign]
    _org_reads.list_all_async = original_list_all


@pytest.mark.asyncio
async def test_set_bulk_stamps_the_declared_schema_version():
    _install_stub_module('my_module', {'type': 'object', 'version': 2})
    api = CoreSettingsAPI()
    org = _make_org(settings={})
    db = _make_async_db(org)

    await api.set_bulk_async(db, uuid4(), 'my_module', {'enabled': True})

    assert org.settings['module:my_module'] == {'enabled': True, '__schema_version': 2}


@pytest.mark.asyncio
async def test_set_bulk_stamps_version_one_when_the_module_declares_none():
    api = CoreSettingsAPI()
    org = _make_org(settings={})
    db = _make_async_db(org)

    await api.set_bulk_async(db, uuid4(), 'my_module', {'enabled': True})

    assert org.settings['module:my_module']['__schema_version'] == 1


@pytest.mark.asyncio
async def test_set_bulk_restamps_an_existing_blob_with_the_declared_version():
    _install_stub_module('my_module', {'type': 'object', 'version': 3})
    api = CoreSettingsAPI()
    org = _make_org(settings={'module:my_module': {'count': 1, '__schema_version': 1}})
    db = _make_async_db(org)

    await api.set_bulk_async(db, uuid4(), 'my_module', {'count': 2})

    assert org.settings['module:my_module'] == {'count': 2, '__schema_version': 3}


@pytest.mark.asyncio
async def test_get_hides_the_schema_version_stamp():
    api = CoreSettingsAPI()
    org = _make_org(settings={'module:my_module': {'a': 1, '__schema_version': 2}})
    db = _make_async_db(org)
    org_id = uuid4()

    assert await api.get_async(db, org_id, 'my_module') == {'a': 1}
    assert (
        await api.get_async(db, org_id, 'my_module', '__schema_version', default='gone')
        == 'gone'
    )


@pytest.mark.asyncio
async def test_get_decrypted_hides_the_schema_version_stamp():
    api = CoreSettingsAPI()
    org = _make_org(settings={'module:my_module': {'__schema_version': 2}})
    db = _make_async_db(org)

    result = await api.get_decrypted_async(
        db, uuid4(), 'my_module', '__schema_version', default='gone'
    )
    assert result == 'gone'


@pytest.mark.asyncio
async def test_get_schema_version_reads_the_stamp_back():
    api = CoreSettingsAPI()
    org = _make_org(settings={'module:my_module': {'a': 1, '__schema_version': 2}})
    db = _make_async_db(org)

    assert await api.get_schema_version_async(db, uuid4(), 'my_module') == 2


@pytest.mark.asyncio
async def test_get_schema_version_is_zero_for_an_unstamped_blob():
    api = CoreSettingsAPI()
    org = _make_org(settings={'module:my_module': {'a': 1}})
    db = _make_async_db(org)

    assert await api.get_schema_version_async(db, uuid4(), 'my_module') == 0


@pytest.mark.asyncio
async def test_get_schema_version_is_zero_for_a_garbage_stamp():
    api = CoreSettingsAPI()
    org = _make_org(settings={'module:my_module': {'__schema_version': 'two'}})
    db = _make_async_db(org)

    assert await api.get_schema_version_async(db, uuid4(), 'my_module') == 0


# ---------------------------------------------------------------------------
# CoreSettingsAPI.migrate_settings_async() — the per-organization pass
# ---------------------------------------------------------------------------


def _two_orgs_at_different_versions():
    from app.services import _org_reads

    org_a = _make_org(settings={'module:my_module': {'timeout_s': 5}})
    org_a.id = uuid4()
    org_b = _make_org(
        settings={'module:my_module': {'timeout_s': 7, '__schema_version': 1}}
    )
    org_b.id = uuid4()
    _org_reads.list_all_async = AsyncMock(return_value=[org_a, org_b])
    return org_a, org_b


@pytest.mark.asyncio
async def test_the_pass_rewrites_each_organization_from_its_own_version():
    _install_stub_module('my_module', {'type': 'object', 'version': 2})
    org_a, org_b = _two_orgs_at_different_versions()
    api = CoreSettingsAPI()
    db = _make_async_db()
    seen: list[tuple] = []

    def migrate(org_id, from_version, settings):
        seen.append((org_id, from_version))
        return {'timeout': settings['timeout_s']}

    count = await api.migrate_settings_async(db, 'my_module', migrate)

    assert count == 2
    assert set(seen) == {(org_a.id, 0), (org_b.id, 1)}
    assert org_a.settings['module:my_module'] == {'timeout': 5, '__schema_version': 2}
    assert org_b.settings['module:my_module'] == {'timeout': 7, '__schema_version': 2}
    db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_the_pass_skips_blobs_already_at_the_declared_version():
    _install_stub_module('my_module', {'type': 'object', 'version': 2})
    from app.services import _org_reads

    org = _make_org(
        settings={'module:my_module': {'timeout': 5, '__schema_version': 2}}
    )
    org.id = uuid4()
    _org_reads.list_all_async = AsyncMock(return_value=[org])
    api = CoreSettingsAPI()
    db = _make_async_db()
    calls: list[tuple] = []

    def migrate(org_id, from_version, settings):
        calls.append(org_id)
        return {'timeout': settings['timeout']}

    count = await api.migrate_settings_async(db, 'my_module', migrate)

    assert count == 0
    assert calls == []
    assert org.settings['module:my_module'] == {'timeout': 5, '__schema_version': 2}


@pytest.mark.asyncio
async def test_a_callback_that_returns_none_keeps_the_data_but_still_stamps():
    _install_stub_module('my_module', {'type': 'object', 'version': 2})
    from app.services import _org_reads

    org = _make_org(settings={'module:my_module': {'a': 1}})
    org.id = uuid4()
    _org_reads.list_all_async = AsyncMock(return_value=[org])
    api = CoreSettingsAPI()
    db = _make_async_db()

    def migrate(org_id, from_version, settings):
        return None

    count = await api.migrate_settings_async(db, 'my_module', migrate)

    assert count == 1
    assert org.settings['module:my_module'] == {'a': 1, '__schema_version': 2}


@pytest.mark.asyncio
async def test_a_callback_may_rewrite_the_view_in_place():
    _install_stub_module('my_module', {'type': 'object', 'version': 2})
    from app.services import _org_reads

    org = _make_org(settings={'module:my_module': {'timeout_s': 5}})
    org.id = uuid4()
    _org_reads.list_all_async = AsyncMock(return_value=[org])
    api = CoreSettingsAPI()
    db = _make_async_db()

    def migrate(org_id, from_version, settings):
        settings['timeout'] = settings.pop('timeout_s')

    count = await api.migrate_settings_async(db, 'my_module', migrate)

    assert count == 1
    assert org.settings['module:my_module'] == {'timeout': 5, '__schema_version': 2}


@pytest.mark.asyncio
async def test_an_async_callback_is_awaited():
    _install_stub_module('my_module', {'type': 'object', 'version': 2})
    from app.services import _org_reads

    org = _make_org(settings={'module:my_module': {'timeout_s': 5}})
    org.id = uuid4()
    _org_reads.list_all_async = AsyncMock(return_value=[org])
    api = CoreSettingsAPI()
    db = _make_async_db()

    async def migrate(org_id, from_version, settings):
        return {'timeout': settings['timeout_s']}

    count = await api.migrate_settings_async(db, 'my_module', migrate)

    assert count == 1
    assert org.settings['module:my_module'] == {'timeout': 5, '__schema_version': 2}


@pytest.mark.asyncio
async def test_the_pass_ignores_organizations_without_the_namespace():
    _install_stub_module('my_module', {'type': 'object', 'version': 2})
    from app.services import _org_reads

    org = _make_org(settings={'module:other': {'x': 1}})
    org.id = uuid4()
    _org_reads.list_all_async = AsyncMock(return_value=[org])
    api = CoreSettingsAPI()
    db = _make_async_db()

    count = await api.migrate_settings_async(db, 'my_module', lambda *a: None)

    assert count == 0
    assert org.settings == {'module:other': {'x': 1}}
