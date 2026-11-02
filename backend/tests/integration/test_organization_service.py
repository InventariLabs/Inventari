"""
Integration tests for .

Covers:
- get_organization: fetch org by ID
- list_all: list all orgs
- create_organization: create org and assign creator as admin
- update_organization: update org fields including settings merge
- create_invitation_code: generate invitation codes
- join_organization: user joins org via invitation code
- leave_organization: user leaves org
- remove_member: admin removes a member
- list_missing_short_id: find orgs without short_id
- list_all_async / count: async and sync variants
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization, OrganizationInvitation
from app.models.user import User
from app.schemas.organization import OrganizationCreate, OrganizationUpdate
from app.services._org_membership import (
    INVITE_CODE_ALPHABET,
    create_invitation_code,
    join_organization,
    leave_organization,
    remove_member,
)
from app.services._org_reads import (
    count,
    get_by_id_async,
    list_all_async,
    list_missing_short_id,
)
from app.services._org_writes import create_organization, update_organization_audited
from app.services.token_service import get_password_hash


@pytest.mark.integration
@pytest.mark.asyncio
class TestGetOrganization:
    async def test_returns_org_by_id(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        result = await get_by_id_async(db, async_test_household.id)
        assert result is not None
        assert result.id == async_test_household.id
        assert result.name == 'Test Organization'

    async def test_returns_none_for_missing_id(
        self, real_async_db_session: AsyncSession
    ):
        db = real_async_db_session
        result = await get_by_id_async(db, uuid4())
        assert result is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestListAll:
    async def test_returns_all_organizations(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        org2 = Organization(name='Second Org', enabled_modules=['core'])
        db.add(org2)
        await db.flush()

        result = await list_all_async(db)
        names = {o.name for o in result}
        assert 'Test Organization' in names
        assert 'Second Org' in names
        assert len(result) >= 2

    async def test_returns_empty_list_when_no_orgs(
        self, real_async_db_session: AsyncSession
    ):
        db = real_async_db_session
        result = await list_all_async(db)
        assert isinstance(result, list)


@pytest.mark.integration
@pytest.mark.asyncio
class TestCreateOrganization:
    async def test_creates_org_and_sets_creator_as_admin(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        db = real_async_db_session
        org_in = OrganizationCreate(name='New Org', currency='EUR')

        result = await create_organization(db, org_in, async_test_user)
        assert result is not None
        assert result.name == 'New Org'
        assert result.currency == 'EUR'
        assert result.short_id is not None
        assert result.short_id.startswith('ORG-')
        assert result.created_by == async_test_user.id

        await db.refresh(async_test_user)
        assert async_test_user.organization_id == result.id
        assert async_test_user.role == 'admin'

    async def test_creates_org_with_generated_name(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        db = real_async_db_session
        async_test_user.full_name = 'Jane Doe'
        await db.flush()

        org_in = OrganizationCreate(name="Jane Doe's Organization", currency='USD')

        result = await create_organization(db, org_in, async_test_user)
        assert 'Jane Doe' in result.name

    async def test_creates_org_with_settings(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        db = real_async_db_session
        org_in = OrganizationCreate(
            name='With Settings', currency='USD', settings={'key': 'value'}
        )

        result = await create_organization(db, org_in, async_test_user)
        assert result.settings == {'key': 'value'}


@pytest.mark.integration
@pytest.mark.asyncio
class TestUpdateOrganization:
    async def test_updates_name(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        db = real_async_db_session
        org_in = OrganizationUpdate(name='Updated Name')

        result = await update_organization_audited(
            db, async_test_household.id, org_in, actor_user_id=async_test_user.id
        )
        assert result.name == 'Updated Name'

    async def test_updates_currency(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        db = real_async_db_session
        org_in = OrganizationUpdate(currency='EUR')

        result = await update_organization_audited(
            db, async_test_household.id, org_in, actor_user_id=async_test_user.id
        )
        assert result.currency == 'EUR'

    async def test_partial_update_preserves_other_fields(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        db = real_async_db_session
        original_name = async_test_household.name
        org_in = OrganizationUpdate(currency='GBP')

        await update_organization_audited(
            db, async_test_household.id, org_in, actor_user_id=async_test_user.id
        )
        await db.refresh(async_test_household)
        assert async_test_household.name == original_name
        assert async_test_household.currency == 'GBP'

    async def test_update_with_settings_merge(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        db = real_async_db_session
        async_test_household.settings = {'existing_key': 'existing_val'}
        await db.flush()
        await db.refresh(async_test_household)

        org_in = OrganizationUpdate(settings={'new_key': 'new_val'})
        result = await update_organization_audited(
            db, async_test_household.id, org_in, actor_user_id=async_test_user.id
        )
        assert 'new_key' in result.settings

    async def test_update_excludes_unset_fields(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        db = real_async_db_session
        original_currency = async_test_household.currency
        org_in = OrganizationUpdate()

        await update_organization_audited(
            db, async_test_household.id, org_in, actor_user_id=async_test_user.id
        )
        await db.refresh(async_test_household)
        assert async_test_household.currency == original_currency


@pytest.mark.integration
@pytest.mark.asyncio
class TestCreateInvitationCode:
    async def test_creates_new_invitation_code(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        db = real_async_db_session
        result = await create_invitation_code(
            db, async_test_household.id, async_test_user.id
        )
        assert 'code' in result
        assert 'expires_at' in result
        # 6 digits is a 10^6 space an attacker can walk inside the
        # 15-minute window. The alphabet drops the characters people misread
        # (0/O, 1/I) so the longer code stays dictatable over the phone.
        assert len(result['code']) == 8
        assert set(result['code']) <= set(INVITE_CODE_ALPHABET)
        assert not set(result['code']) & set('01OI')

    async def test_each_call_mints_a_new_code(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        # Reusing a live code was a saving worth having while a code was a
        # bearer token. Bound to an address, it would send one invitee the
        # invitation issued for another.
        db = real_async_db_session
        result1 = await create_invitation_code(
            db, async_test_household.id, async_test_user.id
        )
        result2 = await create_invitation_code(
            db, async_test_household.id, async_test_user.id
        )
        assert result1['code'] != result2['code']

    async def test_the_code_is_bound_to_the_address_it_was_issued_for(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        result = await create_invitation_code(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            user_id=async_test_user.id,
            invited_email='anna@example.com',
        )
        assert result['invited_email'] == 'anna@example.com'

    async def test_expired_code_generates_new_one(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        db = real_async_db_session
        expired = OrganizationInvitation(
            organization_id=async_test_household.id,
            code='999999',
            created_by=async_test_user.id,
            expires_at=datetime.now(UTC) - timedelta(minutes=5),
            is_used=False,
        )
        db.add(expired)
        await db.flush()

        result = await create_invitation_code(
            db, async_test_household.id, async_test_user.id
        )
        assert result['code'] != '999999'

    async def test_used_code_generates_new_one(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        db = real_async_db_session
        used = OrganizationInvitation(
            organization_id=async_test_household.id,
            code='888888',
            created_by=async_test_user.id,
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            is_used=True,
        )
        db.add(used)
        await db.flush()

        result = await create_invitation_code(
            db, async_test_household.id, async_test_user.id
        )
        assert result['code'] != '888888'


@pytest.mark.integration
@pytest.mark.asyncio
class TestJoinOrganization:
    async def test_user_joins_organization(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        db = real_async_db_session
        code_result = await create_invitation_code(
            db, async_test_household.id, async_test_user.id
        )
        new_user = User(
            email='joiner@example.com',
            hashed_password=get_password_hash('pass123'),
            full_name='Joiner',
            role='user',
            is_active=True,
        )
        db.add(new_user)
        await db.flush()
        await db.refresh(new_user)

        result = await join_organization(db, code_result['code'], new_user.id)
        assert result.id == async_test_household.id
        await db.refresh(new_user)
        assert new_user.organization_id == async_test_household.id
        assert new_user.role == 'user'

    async def test_wrong_guesses_do_not_burn_a_valid_code(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        """guessing is capped by the rate limiter, not by a per-code
        strike counter — so a run of misses must leave the real invitation
        usable. A counter here would let anyone who guesses near someone's code
        cancel their invitation.
        """
        db = real_async_db_session
        code_result = await create_invitation_code(
            db, async_test_household.id, async_test_user.id
        )
        joiner = User(
            email='patient-joiner@example.com',
            hashed_password=get_password_hash('pass123'),
            full_name='Patient Joiner',
            role='user',
            is_active=True,
        )
        db.add(joiner)
        await db.flush()
        await db.refresh(joiner)

        for wrong in ('ZZZZZZZZ', 'YYYYYYYY', 'XXXXXXXX', 'WWWWWWWW'):
            with pytest.raises(ValueError, match='Invalid or expired'):
                await join_organization(db, wrong, joiner.id)

        result = await join_organization(db, code_result['code'], joiner.id)
        assert result.id == async_test_household.id

    async def test_join_with_invalid_code_raises(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        db = real_async_db_session
        with pytest.raises(ValueError, match='Invalid or expired'):
            await join_organization(db, '000000', async_test_user.id)

    async def test_join_with_expired_code_raises(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        db = real_async_db_session
        expired = OrganizationInvitation(
            organization_id=async_test_household.id,
            code='111111',
            created_by=async_test_user.id,
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
            is_used=False,
        )
        db.add(expired)
        await db.flush()

        with pytest.raises(ValueError, match='Invalid or expired'):
            await join_organization(db, '111111', async_test_user.id)

    async def test_join_nonexistent_user_raises(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        db = real_async_db_session
        code_result = await create_invitation_code(
            db, async_test_household.id, async_test_user.id
        )
        with pytest.raises(ValueError, match='User not found'):
            await join_organization(db, code_result['code'], uuid4())

    async def test_join_marks_invitation_used(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        """A successful join must mark the invitation is_used=True.

        Previously is_used was never set, so a single 6-digit code could admit
        unlimited users until its 15-minute expiry.
        """
        db = real_async_db_session
        code_result = await create_invitation_code(
            db, async_test_household.id, async_test_user.id
        )
        code = code_result['code']
        joiner = User(
            email='joiner-a3@example.com',
            hashed_password=get_password_hash('pass123'),
            full_name='Joiner A3',
            role='user',
            is_active=True,
        )
        db.add(joiner)
        await db.flush()

        await join_organization(db, code, joiner.id)

        invitation = await db.scalar(
            select(OrganizationInvitation).where(OrganizationInvitation.code == code)
        )
        assert invitation is not None
        assert invitation.is_used is True

    async def test_used_invitation_cannot_be_reused(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        """After one join, the same code must not admit a second user."""
        db = real_async_db_session
        code_result = await create_invitation_code(
            db, async_test_household.id, async_test_user.id
        )
        code = code_result['code']

        joiner1 = User(
            email='reuse-1@example.com',
            hashed_password=get_password_hash('pass123'),
            full_name='Reuse One',
            role='user',
            is_active=True,
        )
        joiner2 = User(
            email='reuse-2@example.com',
            hashed_password=get_password_hash('pass123'),
            full_name='Reuse Two',
            role='user',
            is_active=True,
        )
        db.add_all([joiner1, joiner2])
        await db.flush()

        await join_organization(db, code, joiner1.id)
        # Second join with the now-used code must be rejected.
        with pytest.raises(ValueError, match='Invalid or expired'):
            await join_organization(db, code, joiner2.id)

    async def test_a_member_opening_a_code_for_their_own_organization_keeps_their_role(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        """The invitation names the role of an arrival — nobody arrives here.

        An administrator minting a `role=user` code for their own organization
        and opening it used to be demoted by their own link: the role was
        written unconditionally, and the sole-administrator guard only runs
        when the organization changes.
        """
        db = real_async_db_session
        assert async_test_user.role == 'admin'
        assert async_test_user.organization_id == async_test_household.id
        code_result = await create_invitation_code(
            db, async_test_household.id, async_test_user.id, role='user'
        )

        result = await join_organization(db, code_result['code'], async_test_user.id)

        assert result.id == async_test_household.id
        await db.refresh(async_test_user)
        assert async_test_user.organization_id == async_test_household.id
        assert async_test_user.role == 'admin'

    async def test_a_redemption_that_admits_nobody_leaves_the_code_unspent(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        """Burning a code here would kill the invitation nobody has used yet.

        The link an administrator just clicked to look at it is usually the
        one meant for the person still to arrive; spending it on a member who
        was already in would leave that person with a dead code.
        """
        db = real_async_db_session
        code_result = await create_invitation_code(
            db, async_test_household.id, async_test_user.id, role='user'
        )
        code = code_result['code']

        await join_organization(db, code, async_test_user.id)

        invitation = await db.scalar(
            select(OrganizationInvitation).where(OrganizationInvitation.code == code)
        )
        assert invitation is not None
        assert invitation.is_used is False
        assert invitation.used_by_user_id is None
        assert invitation.used_at is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestLeaveOrganization:
    async def test_user_leaves_organization(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user2,
    ):
        db = real_async_db_session
        await leave_organization(db, async_test_user2.id, async_test_household.id)
        await db.refresh(async_test_user2)
        assert async_test_user2.organization_id is None
        assert async_test_user2.role == 'user'

    async def test_leave_nonexistent_user_raises(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        with pytest.raises(ValueError, match='User not found'):
            await leave_organization(db, uuid4(), async_test_household.id)

    async def test_sole_admin_cannot_leave(
        self, real_async_db_session: AsyncSession, async_test_household, async_test_user
    ):
        from app.core.exceptions import ConflictException

        db = real_async_db_session
        async_test_household.created_by = async_test_user.id
        await db.flush()
        await db.refresh(async_test_household)

        with pytest.raises(ConflictException):
            await leave_organization(db, async_test_user.id, async_test_household.id)


@pytest.mark.integration
@pytest.mark.asyncio
class TestRemoveMember:
    async def test_remove_member_clears_org(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_user2,
    ):
        db = real_async_db_session
        await remove_member(db, async_test_user2)
        await db.refresh(async_test_user2)
        assert async_test_user2.organization_id is None
        assert async_test_user2.role == 'user'


@pytest.mark.integration
@pytest.mark.asyncio
class TestListMissingShortId:
    async def test_returns_orgs_without_short_id(
        self, real_async_db_session: AsyncSession
    ):
        db = real_async_db_session
        org = Organization(name='No ShortId', enabled_modules=['core'], short_id=None)
        db.add(org)
        await db.flush()

        result = await list_missing_short_id(db)
        ids = {o.id for o in result}
        assert org.id in ids

    async def test_excludes_orgs_with_short_id(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        async_test_household.short_id = 'ORG-TEST1'
        await db.flush()
        await db.refresh(async_test_household)

        result = await list_missing_short_id(db)
        ids = {o.id for o in result}
        assert async_test_household.id not in ids


@pytest.mark.integration
@pytest.mark.asyncio
class TestListAllAsync:
    async def test_returns_all_orgs(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        result = await list_all_async(db)
        names = {o.name for o in result}
        assert 'Test Organization' in names


@pytest.mark.integration
@pytest.mark.asyncio
class TestCount:
    async def test_returns_count(
        self, real_async_db_session: AsyncSession, async_test_household
    ):
        db = real_async_db_session
        result = await count(db)
        assert result >= 1
