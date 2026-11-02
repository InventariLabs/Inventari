"""A key belongs to an organization, not to whoever happens to hold it.

An API key row carries both ``organization_id`` and ``user_id``, but
validation used the key's organization for one thing only — deciding whether
the module was enabled. The request context was then built from the *user's
current* organization, so a key issued in organization A went on working
after its owner moved to organization B, and worked there as B.

Nothing in the membership paths touched keys either: leaving an
organization, being removed from it, and joining another all left every key
the user held valid.

The same path also ignored the credential-change marker, so a key survived
its owner's password reset — the one thing a reset is supposed to end.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.token_blacklist import token_blacklist
from app.models.organization import Organization
from app.models.user import User
from app.modules.api_keys.api_key_service import (
    create_api_key_async,
    validate_api_key,
)
from app.modules.api_keys.models import ApiKey
from app.modules.api_keys.module import _resolve_api_key
from app.services.token_service import get_password_hash
from tests.integration._fake_token_store import FakeTokenStore


@pytest.fixture
def blacklist_on() -> Iterator[None]:
    previous = token_blacklist._redis  # noqa: SLF001
    token_blacklist.set_redis(FakeTokenStore())  # type: ignore[arg-type]
    yield
    token_blacklist._redis = previous  # noqa: SLF001


@pytest.fixture
async def home_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Home', enabled_modules=['core', 'api_keys'])
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def other_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Elsewhere', enabled_modules=['core', 'api_keys'])
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def owner(real_async_db_session: AsyncSession, home_org: Organization) -> User:
    user = User(
        email=f'owner-{uuid4().hex[:8]}@example.com',
        hashed_password=get_password_hash('irrelevant'),
        full_name='Key Owner',
        organization_id=home_org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(user)
    return user


async def _issue(db: AsyncSession, org: Organization, user: User) -> str:
    _, raw = await create_api_key_async(
        db, organization_id=org.id, user_id=user.id, name='CI', permissions=[]
    )
    return raw


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheKeyStaysWithItsOrganization:
    async def test_it_answers_in_the_organization_that_issued_it(
        self, real_async_db_session: AsyncSession, home_org: Organization, owner: User
    ) -> None:
        raw = await _issue(real_async_db_session, home_org, owner)

        assert await validate_api_key(real_async_db_session, raw) is not None

    async def test_it_stops_when_the_owner_moves_on(
        self,
        real_async_db_session: AsyncSession,
        home_org: Organization,
        other_org: Organization,
        owner: User,
    ) -> None:
        raw = await _issue(real_async_db_session, home_org, owner)

        owner.organization_id = other_org.id
        await real_async_db_session.commit()

        assert await validate_api_key(real_async_db_session, raw) is None

    async def test_it_stops_when_the_owner_is_removed(
        self, real_async_db_session: AsyncSession, home_org: Organization, owner: User
    ) -> None:
        raw = await _issue(real_async_db_session, home_org, owner)

        owner.organization_id = None  # what remove_member/leave leaves behind
        await real_async_db_session.commit()

        assert await validate_api_key(real_async_db_session, raw) is None

    async def test_coming_back_does_not_bring_the_key_back(
        self,
        real_async_db_session: AsyncSession,
        home_org: Organization,
        owner: User,
    ) -> None:
        """A removal an admin performed is not undone by a re-invitation."""
        raw = await _issue(real_async_db_session, home_org, owner)
        owner.organization_id = None
        await real_async_db_session.commit()

        assert await validate_api_key(real_async_db_session, raw) is None

        owner.organization_id = home_org.id
        await real_async_db_session.commit()

        assert await validate_api_key(real_async_db_session, raw) is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheKeyDiesWithItsOwnersPassword:
    async def test_a_reset_ends_the_key_issued_before_it(
        self,
        real_async_db_session: AsyncSession,
        blacklist_on: None,
        home_org: Organization,
        owner: User,
    ) -> None:
        raw = await _issue(real_async_db_session, home_org, owner)

        await token_blacklist.mark_credentials_changed(str(owner.id))

        assert await validate_api_key(real_async_db_session, raw) is None

    async def test_a_key_minted_after_the_reset_is_fine(
        self,
        real_async_db_session: AsyncSession,
        blacklist_on: None,
        home_org: Organization,
        owner: User,
    ) -> None:
        await token_blacklist.mark_credentials_changed(str(owner.id))
        # created_at defaults to Postgres now(), which is the *transaction's*
        # start — so the key has to be written by a transaction that opens
        # after the marker, not merely committed after it. Fail-closed either
        # way: a key whose transaction predates the reset is refused.
        await real_async_db_session.commit()
        raw = await _issue(real_async_db_session, home_org, owner)

        assert await validate_api_key(real_async_db_session, raw) is not None


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheRefusalOutlivesTheRequestItEnds:
    """Resolving a key answers for its own writes and for nobody else's.

    A refused key ends its request in a 401, and the 401 rolls the request's
    session back — so a revocation written there would not last. Committing
    that session instead would commit whatever else it held as well.
    """

    async def test_a_revocation_survives_the_rollback_of_the_401(
        self, real_async_db_session: AsyncSession, home_org: Organization, owner: User
    ) -> None:
        raw = await _issue(real_async_db_session, home_org, owner)
        owner_id = owner.id
        owner.organization_id = None
        await real_async_db_session.commit()

        assert await _resolve_api_key(real_async_db_session, raw) is None
        await real_async_db_session.rollback()

        active = await real_async_db_session.scalar(
            select(ApiKey.is_active).where(ApiKey.user_id == owner_id)
        )
        assert active is False

    async def test_it_commits_nothing_the_request_has_not_finished(
        self, real_async_db_session: AsyncSession, home_org: Organization
    ) -> None:
        await real_async_db_session.commit()
        org_id = home_org.id
        home_org.name = 'Not finished yet'

        assert await _resolve_api_key(real_async_db_session, 'inv_live_nope') is None
        await real_async_db_session.rollback()

        name = await real_async_db_session.scalar(
            select(Organization.name).where(Organization.id == org_id)
        )
        assert name == 'Home'
