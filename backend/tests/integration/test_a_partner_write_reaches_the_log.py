"""A partner is catalogue: the supplier a delivery is written against.

Creating one, editing it, switching it off and on, and deleting it all
changed the organization's records and wrote nothing into its journal, so
"who turned off our supplier" had no answer. The entry is written in
``partner_service``, the one door the form, the sheet import and the
modules' ``core_api.partners`` all go through.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction, AuditLog, AuditTargetType
from app.models.organization import Organization
from app.models.user import User
from app.schemas.partner import PartnerCreate, PartnerUpdate
from app.services import partner_service

pytestmark = pytest.mark.integration


async def _entries(db: AsyncSession, partner_id: uuid.UUID) -> list[AuditLog]:
    rows = await db.scalars(
        select(AuditLog)
        .where(
            AuditLog.target_type == AuditTargetType.PARTNER,
            AuditLog.target_id == partner_id,
        )
        .order_by(AuditLog.created_at.asc(), AuditLog.id)
    )
    return list(rows.all())


async def _supplier(
    db: AsyncSession, org: Organization, user: User, name: str = 'Acme'
):
    return await partner_service.create_async(
        db, org.id, PartnerCreate(name=name, type='SUPPLIER', code='ACM'), user.id
    )


async def test_creating_a_partner_names_it(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    partner = await _supplier(
        real_async_db_session, async_test_household, async_test_user
    )

    (entry,) = await _entries(real_async_db_session, partner.id)
    assert entry.action == AuditAction.CREATE
    assert entry.organization_id == async_test_household.id
    assert entry.user_id == async_test_user.id
    assert entry.snapshot == {'name': 'Acme', 'type': 'SUPPLIER', 'code': 'ACM'}


async def test_an_edit_says_what_changed_and_nothing_else(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    partner = await _supplier(
        real_async_db_session, async_test_household, async_test_user
    )

    await partner_service.update_async(
        real_async_db_session,
        async_test_household.id,
        partner.id,
        PartnerUpdate(name='Acme', email='orders@acme.test'),
        user_id=async_test_user.id,
    )

    _created, edited = await _entries(real_async_db_session, partner.id)
    assert edited.action == AuditAction.UPDATE
    assert edited.user_id == async_test_user.id
    assert edited.snapshot == {
        'name': 'Acme',
        'before': {'email': None},
        'after': {'email': 'orders@acme.test'},
    }


async def test_an_edit_that_changes_nothing_writes_nothing(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    partner = await _supplier(
        real_async_db_session, async_test_household, async_test_user
    )

    await partner_service.update_async(
        real_async_db_session,
        async_test_household.id,
        partner.id,
        PartnerUpdate(name='Acme'),
        user_id=async_test_user.id,
    )

    assert len(await _entries(real_async_db_session, partner.id)) == 1


async def test_switching_a_partner_off_and_on_is_two_entries(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    partner = await _supplier(
        real_async_db_session, async_test_household, async_test_user
    )

    await partner_service.deactivate_async(
        real_async_db_session,
        async_test_household.id,
        partner.id,
        user_id=async_test_user.id,
    )
    await partner_service.activate_async(
        real_async_db_session,
        async_test_household.id,
        partner.id,
        user_id=async_test_user.id,
    )

    _created, off, on = await _entries(real_async_db_session, partner.id)
    assert off.action == on.action == AuditAction.UPDATE
    assert off.snapshot == {
        'name': 'Acme',
        'before': {'is_active': True},
        'after': {'is_active': False},
    }
    assert on.snapshot == {
        'name': 'Acme',
        'before': {'is_active': False},
        'after': {'is_active': True},
    }


async def test_deleting_a_partner_keeps_its_name_in_the_journal(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    async_test_user: User,
) -> None:
    partner = await _supplier(
        real_async_db_session, async_test_household, async_test_user
    )
    partner_id = partner.id

    assert await partner_service.delete_async(
        real_async_db_session,
        async_test_household.id,
        partner_id,
        user_id=async_test_user.id,
    )

    _created, deleted = await _entries(real_async_db_session, partner_id)
    assert deleted.action == AuditAction.HARD_DELETE
    assert deleted.user_id == async_test_user.id
    assert deleted.snapshot == {'name': 'Acme', 'type': 'SUPPLIER', 'code': 'ACM'}
