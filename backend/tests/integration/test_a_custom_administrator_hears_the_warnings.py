"""A warning for the administrators reaches the custom roles that administer.

An organization that builds a custom role instead of handing out full
administrator accounts used to get silence in return: the query behind every
"tell the admins" notice asked for the literal ``role == 'admin'`` level, so a
member whose custom role carries ``admin:access`` — or ``system:config:write``,
which docs/subsystems/ROLES.md calls administrator access in all but name —
never heard that the books and the shelves had stopped agreeing. Nothing told
them they were missing it.

The measurement this pins is the one that found it: five members, and the
warning is checked person by person, not counted.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.role import Role, UserRole
from app.models.user import User
from app.services.reconciliation_job import _record_pass_and_alert_admins_async
from app.services.token_service import get_password_hash
from app.services.user_service import UserService

pytestmark = pytest.mark.asyncio

_DRIFT = {
    'quant_move_drift_count': 2,
    'quant_move_drift_total': Decimal('5.000'),
    'layer_quant_drift_count': 0,
    'layer_quant_drift_total': Decimal('0.000'),
}


async def _member(
    db: AsyncSession,
    org_id,
    *,
    role: str = 'user',
    grants: list[str] | None = None,
    active: bool = True,
) -> User:
    user = User(
        email=f'warn_{uuid.uuid4().hex[:8]}@example.com',
        hashed_password=get_password_hash('testpassword123'),
        organization_id=org_id,
        role=role,
        is_active=active,
    )
    db.add(user)
    await db.flush()
    if grants is not None:
        custom = Role(
            name=f'custom_{uuid.uuid4().hex[:6]}',
            permissions=grants,
            is_system=False,
            organization_id=org_id,
        )
        db.add(custom)
        await db.flush()
        db.add(UserRole(user_id=user.id, role_id=custom.id))
        await db.flush()
    return user


async def _warned(db: AsyncSession, org_id) -> set:
    rows = await db.scalars(
        select(Notification.user_id)
        .join(User, User.id == Notification.user_id)
        .where(
            User.organization_id == org_id,
            Notification.title == 'Stock drift detected',
        )
    )
    return set(rows.all())


async def test_the_stock_drift_warning_reaches_every_administrator(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_user,
) -> None:
    db = real_async_db_session
    org_id = async_test_household.id
    admin = async_test_user  # the built-in level
    config_role = await _member(
        db, org_id, role='manager', grants=['system:config:write', 'items:read']
    )
    admin_access_role = await _member(db, org_id, grants=['admin:access'])
    plain = await _member(db, org_id)
    narrowed = await _member(db, org_id, role='manager', grants=['items:write'])
    switched_off = await _member(db, org_id, grants=['admin:access'], active=False)
    switched_off_admin = await _member(db, org_id, role='admin', active=False)

    await _record_pass_and_alert_admins_async(db, org_id, _DRIFT, datetime.now(UTC))
    await db.commit()

    warned = await _warned(db, org_id)
    assert config_role.id in warned, 'the custom configuration role heard nothing'
    assert admin_access_role.id in warned
    assert admin.id in warned
    for silent in (plain, narrowed, switched_off, switched_off_admin):
        assert silent.id not in warned


async def test_a_built_in_administrator_narrowed_by_a_role_still_hears(
    real_async_db_session: AsyncSession,
    async_test_household,
) -> None:
    # The built-in level bypasses every permission check whatever rows it
    # carries, so it is an administrator for the warnings as well.
    db = real_async_db_session
    org_id = async_test_household.id
    admin = await _member(db, org_id, role='admin', grants=['items:read'])

    admins = await UserService.get_organization_admins_async(db, org_id)

    assert [user.id for user in admins] == [admin.id]


async def test_an_administrator_of_another_organization_hears_nothing(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_user,
) -> None:
    db = real_async_db_session
    org_id = async_test_household.id
    custom = await _member(db, org_id, grants=['admin:access'])

    admins = await UserService.get_organization_admins_async(db, uuid.uuid4())

    assert admins == []
    assert {
        u.id for u in await UserService.get_organization_admins_async(db, org_id)
    } == {async_test_user.id, custom.id}
