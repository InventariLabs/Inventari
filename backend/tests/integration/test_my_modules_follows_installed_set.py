"""GET /modules/my after the installed module set changed.

The list is cached per organization for five minutes in Redis, which outlives
a backend restart. A community module uninstalled and installed again is
restarted into a process that registers it, while the list cached by the
process that did not still says it is off -- the screen, the tile and the
catalog card then disagree with the API and the pre-post checks, which read
the organization's own list.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import status

from app.core import cache as cache_module
from app.core.module_registry import module_registry
from app.models.organization import Organization
from app.models.user import User
from app.services.token_service import create_access_token
from tests.integration._fake_redis import FakeRedis

MY_MODULES_URL = '/api/v1/modules/my'
COMMUNITY_MODULE = 'outside_pack'
_REGISTERED = tuple(module_registry.get_all())


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


def _installed(monkeypatch: pytest.MonkeyPatch, *, version: str | None) -> None:
    """Make the registry hold the community module at *version*, or not at all."""
    real = list(_REGISTERED)
    if version is not None:
        real.append(
            SimpleNamespace(
                metadata=SimpleNamespace(
                    name=COMMUNITY_MODULE,
                    version=version,
                    is_premium=False,
                    is_reference=False,
                )
            )
        )
    monkeypatch.setattr(module_registry, 'get_all', lambda: real)


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheCachedListFollowsTheInstalledSet:
    @pytest.fixture(autouse=True)
    def _cache(self):
        original = cache_module._redis
        cache_module._redis = FakeRedis()  # type: ignore[assignment]
        yield
        cache_module._redis = original

    async def _admin_of_an_org_listing_the_module(self, session) -> User:
        org = Organization(
            name=f'Reinstall Org {uuid.uuid4().hex[:8]}',
            enabled_modules=['core', COMMUNITY_MODULE],
        )
        session.add(org)
        await session.flush()
        user = User(
            email=f'reinstall_{uuid.uuid4().hex[:8]}@example.com',
            hashed_password='x',
            full_name='Admin',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        session.add(user)
        await session.commit()
        return user

    async def test_a_module_installed_after_the_list_was_cached_is_listed(
        self, real_async_client, real_async_db_session, monkeypatch
    ):
        """The reported walk: the list is computed while the module is
        uninstalled (cached), the module is installed again and the backend
        restarted -- the same Redis answers. Fails on dev, which serves the
        old list until its TTL runs out."""
        user = await self._admin_of_an_org_listing_the_module(real_async_db_session)

        _installed(monkeypatch, version=None)
        before = await real_async_client.get(MY_MODULES_URL, headers=_auth(user))
        assert before.status_code == status.HTTP_200_OK, before.text
        assert COMMUNITY_MODULE not in before.json()

        _installed(monkeypatch, version='1.0.0')
        after = await real_async_client.get(MY_MODULES_URL, headers=_auth(user))
        assert COMMUNITY_MODULE in after.json()

    async def test_a_module_uninstalled_after_the_list_was_cached_is_dropped(
        self, real_async_client, real_async_db_session, monkeypatch
    ):
        user = await self._admin_of_an_org_listing_the_module(real_async_db_session)

        _installed(monkeypatch, version='1.0.0')
        before = await real_async_client.get(MY_MODULES_URL, headers=_auth(user))
        assert COMMUNITY_MODULE in before.json()

        _installed(monkeypatch, version=None)
        after = await real_async_client.get(MY_MODULES_URL, headers=_auth(user))
        assert COMMUNITY_MODULE not in after.json()

    async def test_the_list_is_still_served_from_the_cache_while_the_set_is_unchanged(
        self, real_async_client, real_async_db_session, monkeypatch
    ):
        user = await self._admin_of_an_org_listing_the_module(real_async_db_session)
        _installed(monkeypatch, version='1.0.0')

        await real_async_client.get(MY_MODULES_URL, headers=_auth(user))
        fake = cache_module._redis
        sets_after_first = fake.commands.count('set')  # type: ignore[union-attr]
        await real_async_client.get(MY_MODULES_URL, headers=_auth(user))

        assert fake.commands.count('set') == sets_after_first  # type: ignore[union-attr]

    async def test_an_upgrade_of_the_same_module_recomputes_the_list(
        self, real_async_client, real_async_db_session, monkeypatch
    ):
        """`module upgrade` keeps the set of names and changes one version.
        The list itself comes out the same, so what pins the direction is that
        the entry written before the upgrade is not served after its restart:
        the first request computes and stores the list again."""
        user = await self._admin_of_an_org_listing_the_module(real_async_db_session)
        _installed(monkeypatch, version='1.0.0')
        await real_async_client.get(MY_MODULES_URL, headers=_auth(user))
        fake = cache_module._redis
        assert isinstance(fake, FakeRedis)
        sets_before_upgrade = fake.commands.count('set')

        _installed(monkeypatch, version='1.1.0')
        after = await real_async_client.get(MY_MODULES_URL, headers=_auth(user))

        assert COMMUNITY_MODULE in after.json()
        assert fake.commands.count('set') == sets_before_upgrade + 1
