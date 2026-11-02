"""Integration tests for UserService.

Tests cover:
- get_user_async: fetch user by id
- get_organization_members_async: fetch org members with only_active filter
- get_organization_admins_async: fetch the active admins
- update_user_status_async: update activation/blocked status
- get_user_by_email_async: fetch by email
- get_first_by_created_at_async: first user by creation date
- promote_superuser_async: promote to superuser
- count_async: count users with optional org filter
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.services.user_service import UserService


@pytest.mark.integration
@pytest.mark.asyncio
class TestGetUser:
    async def test_get_user_returns_user(self, real_async_db_session, async_test_user):
        result = await UserService.get_by_id_model_async(
            real_async_db_session, async_test_user.id
        )
        assert result is not None
        assert result.id == async_test_user.id
        assert result.email == async_test_user.email

    async def test_get_user_random_uuid_returns_none(
        self, real_async_db_session, async_test_user
    ):
        result = await UserService.get_by_id_model_async(real_async_db_session, uuid4())
        assert result is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestGetOrganizationMembers:
    async def test_returns_all_members(
        self,
        real_async_db_session,
        async_test_user,
        async_test_user2,
        async_test_household,
    ):
        result = await UserService.get_organization_members_async(
            real_async_db_session, async_test_household.id
        )
        ids = {u.id for u in result}
        assert async_test_user.id in ids
        assert async_test_user2.id in ids
        assert len(result) == 2

    async def test_returns_all_members_when_only_active_false(
        self,
        real_async_db_session,
        async_test_user,
        async_test_user2,
        async_test_household,
    ):
        result = await UserService.get_organization_members_async(
            real_async_db_session, async_test_household.id, only_active=False
        )
        ids = {u.id for u in result}
        assert async_test_user.id in ids
        assert async_test_user2.id in ids
        assert len(result) == 2

    async def test_excludes_inactive_when_only_active_true(
        self,
        real_async_db_session,
        async_test_user,
        async_test_user2,
        async_test_household,
    ):
        async_test_user2.is_active = False
        await real_async_db_session.flush()

        result = await UserService.get_organization_members_async(
            real_async_db_session, async_test_household.id, only_active=True
        )
        ids = {u.id for u in result}
        assert async_test_user.id in ids
        assert async_test_user2.id not in ids
        assert len(result) == 1

    async def test_includes_inactive_when_only_active_false(
        self,
        real_async_db_session,
        async_test_user,
        async_test_user2,
        async_test_household,
    ):
        async_test_user2.is_active = False
        await real_async_db_session.flush()

        result = await UserService.get_organization_members_async(
            real_async_db_session, async_test_household.id, only_active=False
        )
        ids = {u.id for u in result}
        assert async_test_user.id in ids
        assert async_test_user2.id in ids
        assert len(result) == 2


@pytest.mark.integration
@pytest.mark.asyncio
class TestGetOrganizationAdmins:
    async def test_returns_only_admins(
        self,
        real_async_db_session,
        async_test_user,
        async_test_user2,
        async_test_household,
    ):
        result = await UserService.get_organization_admins_async(
            real_async_db_session, async_test_household.id
        )
        ids = {u.id for u in result}
        assert async_test_user.id in ids
        assert async_test_user2.id not in ids
        assert len(result) == 1

    async def test_excludes_inactive_admins(
        self,
        real_async_db_session,
        async_test_user,
        async_test_user2,
        async_test_household,
    ):
        async_test_user.is_active = False
        await real_async_db_session.flush()

        result = await UserService.get_organization_admins_async(
            real_async_db_session, async_test_household.id
        )
        assert len(result) == 0


@pytest.mark.integration
@pytest.mark.asyncio
class TestUpdateUserStatus:
    async def test_deactivate_user(self, real_async_db_session, async_test_user):
        result = await UserService.update_user_status_async(
            real_async_db_session, async_test_user, is_active=False
        )
        assert result.is_active is False

    async def test_block_user_sets_fields(self, real_async_db_session, async_test_user):
        now = datetime.now(UTC)
        result = await UserService.update_user_status_async(
            real_async_db_session,
            async_test_user,
            is_blocked=True,
            blocked_at=now,
            blocking_reason='test',
        )
        assert result.is_blocked is True
        assert result.blocked_at is not None
        assert result.blocking_reason == 'test'

    async def test_unblock_user_clears_fields(
        self, real_async_db_session, async_test_user
    ):
        await UserService.update_user_status_async(
            real_async_db_session,
            async_test_user,
            is_blocked=True,
            blocked_at=datetime.now(UTC),
            blocking_reason='test',
        )

        result = await UserService.update_user_status_async(
            real_async_db_session, async_test_user, is_blocked=False
        )
        assert result.is_blocked is False
        assert result.blocked_at is None
        assert result.blocking_reason is None

    async def test_activate_user(self, real_async_db_session, async_test_user):
        async_test_user.is_active = False
        await real_async_db_session.flush()
        await real_async_db_session.refresh(async_test_user)

        result = await UserService.update_user_status_async(
            real_async_db_session, async_test_user, is_active=True
        )
        assert result.is_active is True


@pytest.mark.integration
@pytest.mark.asyncio
class TestGetUserByEmail:
    async def test_returns_user_for_existing_email(
        self, real_async_db_session, async_test_user
    ):
        result = await UserService.get_user_by_email_async(
            real_async_db_session, async_test_user.email
        )
        assert result is not None
        assert result.id == async_test_user.id

    async def test_returns_none_for_nonexistent_email(
        self, real_async_db_session, async_test_user
    ):
        result = await UserService.get_user_by_email_async(
            real_async_db_session, 'nonexistent@example.com'
        )
        assert result is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestGetFirstByCreatedAt:
    async def test_returns_a_user_for_org(
        self,
        real_async_db_session,
        async_test_user,
        async_test_user2,
        async_test_household,
    ):
        result = await UserService.get_first_by_created_at_async(
            real_async_db_session, async_test_household.id
        )
        assert result is not None
        assert result.organization_id == async_test_household.id

    async def test_returns_none_for_empty_org(
        self, real_async_db_session, async_test_user
    ):
        result = await UserService.get_first_by_created_at_async(
            real_async_db_session, uuid4()
        )
        assert result is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestPromoteSuperuser:
    async def test_promote_existing_user(self, real_async_db_session, async_test_user):
        result = await UserService.promote_superuser_async(
            real_async_db_session, async_test_user.id
        )
        assert result is not None
        assert result.is_superuser is True

    async def test_promote_nonexistent_user_returns_none(
        self, real_async_db_session, async_test_user
    ):
        result = await UserService.promote_superuser_async(
            real_async_db_session, uuid4()
        )
        assert result is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestCount:
    async def test_count_with_org_filter(
        self,
        real_async_db_session,
        async_test_user,
        async_test_user2,
        async_test_household,
    ):
        result = await UserService.count_async(
            real_async_db_session, async_test_household.id
        )
        assert result == 2

    async def test_count_without_org_filter(
        self, real_async_db_session, async_test_user, async_test_user2
    ):
        result = await UserService.count_async(real_async_db_session)
        assert result >= 2

    async def test_count_empty_org(self, real_async_db_session, async_test_user):
        result = await UserService.count_async(real_async_db_session, uuid4())
        assert result == 0
