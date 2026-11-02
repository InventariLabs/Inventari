"""Joining and registering with an invitation ride the request's transaction.

Both used to commit halfway. Joining committed the move, the spent code and
the journal entries before it gave the newcomer the custom role the
invitation named; registering committed the new account the same way, one
step before the same role. A failure after that point -- the role step
itself, or anything else the request did once the service returned -- found
the person already moved, the account already created and the code already
spent, with nothing left to roll back. The invitation could not be used
again, and the role it promised was never given.

The services flush instead, and the request-scoped session commits once. A
failure after the former commit point takes the membership, the account,
the spent code and the journal entries back together, and the code still
opens for the next attempt.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.organization import Organization, OrganizationInvitation
from app.models.role import Role
from app.models.user import User
from app.schemas.user import UserCreate
from app.services import permissions_service
from app.services._org_membership import join_organization
from app.services.auth_service import AuthService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class _RoleStepError(RuntimeError):
    """The step after the former commit point, failing."""


class _Door:
    """A host organisation and an invitation that names a custom role."""

    host_id: uuid.UUID
    code: str
    invited_email: str
    guest_id: uuid.UUID
    guest_org_id: uuid.UUID


async def _door(db: AsyncSession) -> _Door:
    door = _Door()
    host = Organization(name=f'Host {uuid.uuid4().hex[:6]}', enabled_modules=['core'])
    db.add(host)
    await db.flush()
    owner = await ModuleTestHelper.create_user_async(
        db, host, email=f'owner_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    role = Role(organization_id=host.id, name='Receiving clerk', permissions=[])
    db.add(role)
    await db.flush()

    # The guest is the sole member of an organisation of their own, so
    # joining is a switch and nothing refuses it.
    their_org = Organization(
        name=f'Guest {uuid.uuid4().hex[:6]}', enabled_modules=['core']
    )
    db.add(their_org)
    await db.flush()
    guest = await ModuleTestHelper.create_user_async(
        db, their_org, email=f'guest_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    their_org.created_by = guest.id

    door.code = uuid.uuid4().hex[:8].upper()
    db.add(
        OrganizationInvitation(
            organization_id=host.id,
            code=door.code,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            created_by=owner.id,
            role='user',
            role_id=role.id,
            # A bearer code, so the guest and a newcomer can both hold it.
            invited_email=None,
        )
    )
    await db.commit()
    door.host_id, door.guest_id, door.guest_org_id = host.id, guest.id, their_org.id
    return door


@pytest.fixture
def the_role_step_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(*args: object, **kwargs: object) -> bool:
        raise _RoleStepError('the role could not be given')

    monkeypatch.setattr(permissions_service, 'assign_role_async', fail)


async def _the_request_fails(db: AsyncSession) -> None:
    """What the request-scoped session does when the endpoint raises."""
    await db.rollback()
    db.expire_all()


async def _code_is_spent(db: AsyncSession, code: str) -> bool:
    return bool(
        await db.scalar(
            select(OrganizationInvitation.is_used).where(
                OrganizationInvitation.code == code
            )
        )
    )


async def _journal_entries(db: AsyncSession, organization_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.organization_id == organization_id)
        )
        or 0
    )


async def test_a_join_that_fails_after_the_move_leaves_the_guest_where_they_were(
    real_async_db_session: AsyncSession, the_role_step_fails: None
) -> None:
    db = real_async_db_session
    door = await _door(db)

    with pytest.raises(_RoleStepError):
        await join_organization(db, door.code, door.guest_id)
    await _the_request_fails(db)

    guest = await db.get(User, door.guest_id)
    assert guest is not None
    assert guest.organization_id == door.guest_org_id
    assert guest.role == 'admin'
    assert not await _code_is_spent(db, door.code)
    # Neither the arrival nor the departure the switch journals.
    assert await _journal_entries(db, door.host_id) == 0
    assert await _journal_entries(db, door.guest_org_id) == 0


async def test_a_registration_that_fails_after_the_account_creates_nobody(
    real_async_db_session: AsyncSession, the_role_step_fails: None
) -> None:
    db = real_async_db_session
    door = await _door(db)
    email = f'newcomer_{uuid.uuid4().hex[:8]}@test.com'

    with pytest.raises(_RoleStepError):
        await AuthService.register_user_async(
            db,
            UserCreate(
                email=email,
                full_name='Newcomer',
                password='Str0ng!passphrase',
                invite_code=door.code,
            ),
        )
    await _the_request_fails(db)

    assert await db.scalar(select(User.id).where(User.email == email)) is None
    assert not await _code_is_spent(db, door.code)
    assert await _journal_entries(db, door.host_id) == 0
