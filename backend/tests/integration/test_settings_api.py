"""Integration tests for CoreSettingsAPI namespace isolation."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api.settings import CoreSettingsAPI
from app.models.organization import Organization


@pytest.fixture
def settings_api() -> CoreSettingsAPI:
    return CoreSettingsAPI()


@pytest.fixture
async def test_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name='Settings Test Org',
        enabled_modules=['core'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(org)
    return org


@pytest.mark.integration
class TestCoreSettingsAPI:
    async def test_set_and_get_roundtrip(
        self,
        real_async_db_session: AsyncSession,
        settings_api: CoreSettingsAPI,
        test_org: Organization,
    ):
        await settings_api.set_bulk_async(
            real_async_db_session, test_org.id, 'test_module', {'key1': 'value1'}
        )

        result = await settings_api.get_async(
            real_async_db_session, test_org.id, 'test_module', 'key1'
        )
        assert result == 'value1'

    async def test_get_returns_default_when_missing(
        self,
        real_async_db_session: AsyncSession,
        settings_api: CoreSettingsAPI,
        test_org: Organization,
    ):
        result = await settings_api.get_async(
            real_async_db_session,
            test_org.id,
            'test_module',
            'nonexistent',
            default='fallback',
        )
        assert result == 'fallback'

    async def test_get_namespace_returns_full_dict(
        self,
        real_async_db_session: AsyncSession,
        settings_api: CoreSettingsAPI,
        test_org: Organization,
    ):
        await settings_api.set_bulk_async(
            real_async_db_session, test_org.id, 'test_module', {'a': 1}
        )
        await settings_api.set_bulk_async(
            real_async_db_session, test_org.id, 'test_module', {'b': 2}
        )

        result = await settings_api.get_async(
            real_async_db_session, test_org.id, 'test_module'
        )
        assert result == {'a': 1, 'b': 2}

    async def test_set_bulk_merges(
        self,
        real_async_db_session: AsyncSession,
        settings_api: CoreSettingsAPI,
        test_org: Organization,
    ):
        await settings_api.set_bulk_async(
            real_async_db_session, test_org.id, 'test_module', {'existing': True}
        )

        await settings_api.set_bulk_async(
            real_async_db_session,
            test_org.id,
            'test_module',
            {'new_key': 'val', 'count': 42},
        )

        ns = await settings_api.get_async(
            real_async_db_session, test_org.id, 'test_module'
        )
        assert ns['existing'] is True
        assert ns['new_key'] == 'val'
        assert ns['count'] == 42

    async def test_namespaces_are_isolated(
        self,
        real_async_db_session: AsyncSession,
        settings_api: CoreSettingsAPI,
        test_org: Organization,
    ):
        await settings_api.set_bulk_async(
            real_async_db_session, test_org.id, 'module_a', {'key': 'a_val'}
        )
        await settings_api.set_bulk_async(
            real_async_db_session, test_org.id, 'module_b', {'key': 'b_val'}
        )

        assert (
            await settings_api.get_async(
                real_async_db_session, test_org.id, 'module_a', 'key'
            )
            == 'a_val'
        )
        assert (
            await settings_api.get_async(
                real_async_db_session, test_org.id, 'module_b', 'key'
            )
            == 'b_val'
        )

    def test_settings_security_docstring_present(self):
        """The security note is the contract a reader relies on. Isolation
        is no longer described as a convention callers were asked to
        respect: the boundary is enforced through the caller's identity
        (``app.core.module_identity``), and a foreign name is refused."""
        assert CoreSettingsAPI.__doc__ is not None
        doc = CoreSettingsAPI.__doc__.lower()
        assert 'enforced' in doc
        assert 'permissionerror' in doc
        assert 'by convention' not in doc

    async def test_set_raises_on_missing_org(
        self,
        real_async_db_session: AsyncSession,
        settings_api: CoreSettingsAPI,
    ):
        from uuid import uuid4

        with pytest.raises(ValueError, match='not found'):
            await settings_api.set_bulk_async(
                real_async_db_session, uuid4(), 'mod', {'key': 'val'}
            )
