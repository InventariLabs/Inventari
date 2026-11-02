"""Registering through an invitation leaves a name, a moment and a log entry.

The join path set ``used_by_user_id`` and ``used_at``; the register path —
the one a newcomer takes by definition, since they have no account yet —
burned the code with ``is_used = True`` and stopped there. The invitation
record could say only that someone had come in, the audit log said nothing
at all, and neither could answer "who, and when, got access to this
organization".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.organization import Organization, OrganizationInvitation
from app.schemas.user import UserCreate
from app.services.auth_service import AuthService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _door(db: AsyncSession):
    """One host organization, one invitation addressed to a newcomer."""
    host = Organization(name=f'Host {uuid.uuid4().hex[:6]}', enabled_modules=['core'])
    db.add(host)
    await db.flush()
    owner = await ModuleTestHelper.create_user_async(
        db, host, email=f'owner_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    code = uuid.uuid4().hex[:8].upper()
    email = f'newcomer_{uuid.uuid4().hex[:8]}@test.com'
    db.add(
        OrganizationInvitation(
            organization_id=host.id,
            code=code,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            created_by=owner.id,
            role='viewer',
            invited_email=email,
        )
    )
    await db.flush()
    return host, code, email


@pytest.mark.integration
@pytest.mark.asyncio
class TestRegisteringThroughAnInvitation:
    async def test_the_invitation_names_who_came_and_when(
        self, real_async_db_session: AsyncSession
    ):
        host, code, email = await _door(real_async_db_session)

        user = await AuthService.register_user_async(
            real_async_db_session,
            UserCreate(
                email=email,
                full_name='Newcomer',
                password='Str0ng!passphrase',
                invite_code=code,
            ),
        )
        await real_async_db_session.commit()
        # Captured before the expiry below: touching a lapsed attribute on an
        # async session is a lazy load, not a query.
        newcomer_id = user.id

        real_async_db_session.expire_all()
        invitation = await real_async_db_session.scalar(
            select(OrganizationInvitation).where(OrganizationInvitation.code == code)
        )
        assert invitation is not None
        assert invitation.is_used is True
        assert invitation.used_by_user_id == newcomer_id
        assert invitation.used_at is not None

    async def test_the_organization_log_records_the_entry(
        self, real_async_db_session: AsyncSession
    ):
        host, code, email = await _door(real_async_db_session)

        user = await AuthService.register_user_async(
            real_async_db_session,
            UserCreate(
                email=email,
                full_name='Newcomer',
                password='Str0ng!passphrase',
                invite_code=code,
            ),
        )
        await real_async_db_session.commit()

        entries = list(
            (
                await real_async_db_session.scalars(
                    select(AuditLog).where(
                        AuditLog.organization_id == host.id,
                        AuditLog.target_type == 'invitation',
                    )
                )
            ).all()
        )
        assert len(entries) == 1
        entry = entries[0]
        assert entry.action == 'USE'
        assert entry.user_id == user.id
        assert entry.snapshot.get('invited_email') == email
