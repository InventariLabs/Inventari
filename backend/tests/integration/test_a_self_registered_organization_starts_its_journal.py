"""An organization founded by a registration an operator approved has a first entry.

Completing a self-registration creates a tenant and makes the newcomer its
administrator. The invitation branch of the same function journalled the
arrival; this branch founded a whole organization and left no entry, so the
new organization's journal could not say who let it exist.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.user import RegistrationRequest
from app.schemas.user import UserCreate
from app.services.auth_service import AuthService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_the_new_organizations_first_entry_names_the_approving_operator(
    real_async_db_session: AsyncSession,
):
    db = real_async_db_session
    host = Organization(name=f'Host {uuid.uuid4().hex[:6]}', enabled_modules=['core'])
    db.add(host)
    await db.flush()
    operator = await ModuleTestHelper.create_user_async(
        db, host, email=f'op_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    email = f'newcomer_{uuid.uuid4().hex[:8]}@test.com'
    request = RegistrationRequest(
        email=email,
        full_name='Newcomer',
        token=uuid.uuid4().hex,
        approved_by_id=operator.id,
    )
    db.add(request)
    await db.flush()

    user = await AuthService.register_user_async(
        db,
        UserCreate(email=email, full_name='Newcomer', password='Str0ng!passphrase'),
        registration_request=request,
    )
    new_org_id = user.organization_id
    assert new_org_id is not None and new_org_id != host.id

    (entry,) = (
        await db.scalars(select(AuditLog).where(AuditLog.organization_id == new_org_id))
    ).all()
    assert entry.action == 'CREATE'
    assert entry.target_type == 'organization'
    assert entry.target_id == new_org_id
    assert entry.user_id == user.id
    assert entry.snapshot is not None
    assert entry.snapshot['registration'] == 'approved'
    assert entry.snapshot['approved_by_id'] == str(operator.id)
