"""Logo, settings and member-role rules live in the service layer.

Everything here calls the services directly — no HTTP client — and pins that
the write and its journal entry share one transaction.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.exceptions import ValidationException
from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.user import User
from app.schemas.organization import OrganizationUpdate
from app.services import _org_membership, _org_writes
from app.services._org_membership import change_member_role_audited
from app.services._org_writes import (
    set_organization_logo,
    update_organization_audited,
)


async def _org_with_admin(db, name='Svc Org', logo=None):
    org = Organization(name=name, logo_url=logo)
    db.add(org)
    await db.flush()
    admin = await ModuleTestHelper.create_user_async(
        db, org, email=f'{uuid4().hex[:8]}@example.com', role='admin'
    )
    return org, admin


class TestLogoAndItsAuditEntryShareATransaction:
    async def test_audit_failure_takes_the_logo_change_back(
        self, real_async_db_session
    ):
        db = real_async_db_session
        org, admin = await _org_with_admin(db, logo='old/logo.png')
        org_id, admin_id = org.id, admin.id
        await db.commit()

        with (
            patch.object(_org_writes, 'log_action_async', side_effect=RuntimeError),
            patch.object(_org_writes, 'FileStorageService') as storage,
            pytest.raises(RuntimeError),
        ):
            await set_organization_logo(
                db, org_id, 'new/logo.png', actor_user_id=admin_id
            )
        # The request session rolls back when the handler raises.
        await db.rollback()

        row = await db.scalar(select(Organization).where(Organization.id == org_id))
        assert row.logo_url == 'old/logo.png'
        storage.return_value.delete.assert_not_called()

    async def test_logo_and_entry_land_together(self, real_async_db_session):
        db = real_async_db_session
        org, admin = await _org_with_admin(db, logo='old/logo.png')

        with patch.object(_org_writes, 'FileStorageService') as storage:
            storage.return_value.delete = AsyncMock()
            await set_organization_logo(
                db, org.id, 'new/logo.png', actor_user_id=admin.id
            )

        assert org.logo_url == 'new/logo.png'
        storage.return_value.delete.assert_awaited_once_with('old/logo.png')
        entry = await db.scalar(select(AuditLog).where(AuditLog.target_id == org.id))
        assert entry.snapshot == {'logo': 'uploaded'}


class TestSettingsUpdate:
    async def test_names_only_what_changed(self, real_async_db_session):
        db = real_async_db_session
        org, admin = await _org_with_admin(db)

        await update_organization_audited(
            db, org.id, OrganizationUpdate(name='Renamed'), actor_user_id=admin.id
        )

        entry = await db.scalar(select(AuditLog).where(AuditLog.target_id == org.id))
        assert entry.snapshot['before'] == {'name': 'Svc Org'}
        assert entry.snapshot['after'] == {'name': 'Renamed'}

    async def test_bad_smtp_block_is_refused_before_anything_is_written(
        self, real_async_db_session
    ):
        db = real_async_db_session
        org, admin = await _org_with_admin(db)

        with pytest.raises(ValidationException):
            await update_organization_audited(
                db,
                org.id,
                OrganizationUpdate(settings={'smtp': {'port': 'not-a-port'}}),
                actor_user_id=admin.id,
            )


class TestMemberRoleRules:
    async def test_unknown_level_is_refused(self, real_async_db_session):
        db = real_async_db_session
        org, admin = await _org_with_admin(db)
        member = await ModuleTestHelper.create_user_async(
            db, org, email='m1@example.com', role='user'
        )
        with pytest.raises(ValidationException):
            await change_member_role_audited(
                db,
                organization_id=org.id,
                actor_user_id=admin.id,
                member_id=member.id,
                role='superuser',
                role_id=None,
            )

    async def test_actor_cannot_change_their_own_role(self, real_async_db_session):
        db = real_async_db_session
        org, admin = await _org_with_admin(db)
        with pytest.raises(ValidationException):
            await change_member_role_audited(
                db,
                organization_id=org.id,
                actor_user_id=admin.id,
                member_id=admin.id,
                role='user',
                role_id=None,
            )

    async def test_change_is_journalled_with_both_sides(self, real_async_db_session):
        db = real_async_db_session
        org, admin = await _org_with_admin(db)
        member = await ModuleTestHelper.create_user_async(
            db, org, email='m2@example.com', role='user'
        )
        await change_member_role_audited(
            db,
            organization_id=org.id,
            actor_user_id=admin.id,
            member_id=member.id,
            role='manager',
            role_id=None,
        )
        entry = await db.scalar(select(AuditLog).where(AuditLog.target_id == member.id))
        assert entry.snapshot['before'] == {'role': 'user'}
        assert entry.snapshot['after'] == {'role': 'manager'}

    async def test_audit_failure_leaves_the_role_unwritten(self, real_async_db_session):
        db = real_async_db_session
        org, admin = await _org_with_admin(db)
        member = await ModuleTestHelper.create_user_async(
            db, org, email='m3@example.com', role='user'
        )
        org_id, admin_id, member_id = org.id, admin.id, member.id
        await db.commit()
        with (
            patch.object(_org_membership, 'log_action_async', side_effect=RuntimeError),
            pytest.raises(RuntimeError),
        ):
            await change_member_role_audited(
                db,
                organization_id=org_id,
                actor_user_id=admin_id,
                member_id=member_id,
                role='manager',
                role_id=None,
            )
        await db.rollback()
        member = await db.get(User, member_id)
        await db.refresh(member)
        assert member.role == 'user'
