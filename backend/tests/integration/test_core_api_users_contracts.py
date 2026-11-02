"""
Contract tests for CoreUsersAPI (app.core.public_api.core_api.users).

These tests pin down the SHAPE of every public method and assert the
multi-tenant org-scoping contract: a method that filters by org must
never return rows belonging to a different organization.

Goal: catch regressions early if a CoreAPI method silently changes its
return type or starts leaking cross-tenant data.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.models.user import User
from app.services.user_service import UserService

from ._core_api_helpers import make_other_org, make_user


@pytest.mark.integration
@pytest.mark.asyncio
class TestCoreUsersAPIShape:
    """Verify return-type shape of every public CoreUsersAPI method."""

    async def test_get_async_returns_user_profile_dto(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_household
    ):
        db = real_async_db_session
        result = await core_api.users.get_async(
            db, async_test_household.id, async_test_user.id
        )
        assert result is not None
        assert result.id == async_test_user.id
        assert result.email == async_test_user.email
        assert result.organization_id == async_test_household.id
        assert isinstance(result.role, str)
        assert isinstance(result.preferred_language, str)

    async def test_get_async_returns_none_for_missing_id(
        self, real_async_db_session: AsyncSession
    ):
        db = real_async_db_session
        result = await core_api.users.get_async(db, None, uuid4())
        assert result is None

    async def test_get_first_by_created_at_async_returns_user(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_household
    ):
        db = real_async_db_session
        result = await UserService.get_first_by_created_at_async(
            db, async_test_household.id
        )
        assert result is not None
        assert result.id == async_test_user.id

    async def test_list_org_members_async_returns_only_org_users(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user,
        async_test_user2,
    ):
        db = real_async_db_session
        result = await core_api.users.list_org_members_async(
            db, async_test_household.id
        )
        user_ids = {u.id for u in result}
        assert async_test_user.id in user_ids
        assert async_test_user2.id in user_ids
        assert len(result) == 2

    async def test_promote_superuser_promotes_user(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        db = real_async_db_session
        async_test_user.is_superuser = False
        await db.commit()
        result = await core_api.users.promote_superuser_async(db, async_test_user.id)
        assert result is not None
        assert result.is_superuser is True
        assert result.id == async_test_user.id

    async def test_promote_superuser_returns_none_for_missing(
        self, real_async_db_session: AsyncSession
    ):
        db = real_async_db_session
        result = await core_api.users.promote_superuser_async(db, uuid4())
        assert result is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestCoreUsersAPIOrgScoping:
    """Multi-tenant safety: CoreUsersAPI methods must not leak cross-org data."""

    async def test_list_org_members_async_excludes_other_org(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        db = real_async_db_session
        other_org = await db.run_sync(make_other_org)
        other_user = await db.run_sync(
            lambda s: make_user(
                s, f'other_{uuid4().hex[:8]}@example.com', other_org.id, role='admin'
            )
        )

        result = await core_api.users.list_org_members_async(
            db, async_test_household.id
        )
        user_ids = {u.id for u in result}
        assert async_test_user.id in user_ids
        assert other_user.id not in user_ids

    async def test_get_first_by_created_at_async_filters_by_org(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        db = real_async_db_session
        other_org = await db.run_sync(make_other_org)
        await db.run_sync(
            lambda s: make_user(s, f'other_{uuid4().hex[:8]}@example.com', other_org.id)
        )

        with_org = await UserService.get_first_by_created_at_async(
            db, async_test_household.id
        )
        assert with_org is not None
        assert with_org.id == async_test_user.id

    async def test_get_first_system_user_async_is_explicit_global_read(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        """The org-less global read exists ONLY as the explicitly-named
        bootstrap method — never as an omitted org parameter."""
        db = real_async_db_session
        other_org = await db.run_sync(make_other_org)
        await db.run_sync(
            lambda s: make_user(s, f'other_{uuid4().hex[:8]}@example.com', other_org.id)
        )

        first = await core_api.users.get_first_system_user_async(db)
        assert first is not None  # oldest user across all orgs

    async def test_get_async_is_scoped_to_the_requested_org(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """This test asserted the opposite ("regardless of org") until
        the org parameter existed. A foreign org now sees nothing; the
        explicit cross-org view still needs an explicit None."""
        db = real_async_db_session

        assert await core_api.users.get_async(db, uuid4(), async_test_user.id) is None

        result = await core_api.users.get_async(db, None, async_test_user.id)
        assert result is not None
        assert result.id == async_test_user.id

    async def test_get_by_email_async_does_not_cross_orgs(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """Email is guessable, so an unscoped lookup was enumeration."""
        db = real_async_db_session

        foreign = await core_api.users.get_by_email_async(
            db, uuid4(), async_test_user.email
        )

        assert foreign is None

    async def test_get_by_email_async_resolves_within_the_org(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_household
    ):
        db = real_async_db_session

        found = await core_api.users.get_by_email_async(
            db, async_test_household.id, async_test_user.email
        )

        assert found is not None
        assert found.id == async_test_user.id

    async def test_get_by_ids_async_drops_foreign_rows(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        db = real_async_db_session

        result = await core_api.users.get_by_ids_async(
            db, uuid4(), [async_test_user.id]
        )

        assert result == []

    async def test_block_async_refuses_a_foreign_account(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        db = real_async_db_session

        result = await core_api.users.block_async(
            db, uuid4(), async_test_user.id, 'nope'
        )

        assert result is None
        await db.refresh(async_test_user)
        assert async_test_user.is_blocked is False


@pytest.mark.integration
@pytest.mark.asyncio
class TestCoreUsersAPIReturnTypes:
    """Lock return types — Pydantic DTOs vs SQLAlchemy models."""

    async def test_get_async_returns_dto_not_model(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        db = real_async_db_session
        result = await core_api.users.get_async(db, None, async_test_user.id)
        assert type(result).__name__ == 'UserProfileDTO'
        assert not isinstance(result, User)

    async def test_list_org_members_async_returns_models(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        result = await core_api.users.list_org_members_async(
            db, async_test_household.id
        )
        for user in result:
            assert isinstance(user, User)
