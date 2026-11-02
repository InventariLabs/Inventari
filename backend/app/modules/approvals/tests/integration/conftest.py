import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.user import User


@pytest.fixture
def h(db_session: Session) -> ModuleTestHelper:
    return ModuleTestHelper(db_session)


@pytest.fixture
def approval_org(h: ModuleTestHelper) -> Organization:
    return h.create_org(
        'Approvals Test Org',
        ['core', 'approvals'],
    )


@pytest.fixture
def approver(h: ModuleTestHelper, approval_org: Organization) -> User:
    return h.create_user(approval_org, email='approver@example.com', role='manager')


@pytest.fixture
def approver2(h: ModuleTestHelper, approval_org: Organization) -> User:
    return h.create_user(approval_org, email='approver2@example.com', role='admin')


@pytest.fixture
def requester(h: ModuleTestHelper, approval_org: Organization) -> User:
    return h.create_user(approval_org, email='requester@example.com', role='user')


@pytest.fixture
def approval_auth(h: ModuleTestHelper, approver: User) -> dict[str, str]:
    return h.get_auth_headers(approver)


@pytest.fixture
def approval_auth2(h: ModuleTestHelper, approver2: User) -> dict[str, str]:
    return h.get_auth_headers(approver2)


@pytest.fixture
def requester_auth(h: ModuleTestHelper, requester: User) -> dict[str, str]:
    return h.get_auth_headers(requester)


@pytest.fixture
def single_stage_workflow_payload() -> dict[str, Any]:
    return {
        'target_type': 'document',
        'requester_scope': {'everyone': True},
        'is_active': True,
        'expected_scope': {'holds': 'all'},
        'name': 'Single Stage Approval',
        'stages': [
            {
                'order': 1,
                'role': 'manager',
                'label': 'Manager Approval',
                'approver_user_ids': [],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Async fixtures (the approvals services are async-only)
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_approval_org(real_async_db_session: AsyncSession) -> Organization:
    """Test organization on the async session (all approvals enabled)."""
    org = Organization(
        name=f'Approvals Async Test Org {uuid.uuid4().hex[:8]}',
        enabled_modules=['core', 'approvals'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(org)
    return org


async def _async_create_user(
    db: AsyncSession,
    org: Organization,
    *,
    email: str,
    role: str,
) -> User:
    """Create a user row on the async session via the shared helper."""
    return await ModuleTestHelper.create_user_async(db, org, email=email, role=role)


@pytest.fixture
async def async_make_user(
    real_async_db_session: AsyncSession, async_approval_org: Organization
) -> Any:
    """Factory: create a user on the async session for this test's org."""

    async def _make(*, email: str, role: str = 'admin') -> User:
        return await _async_create_user(
            real_async_db_session, async_approval_org, email=email, role=role
        )

    return _make


@pytest.fixture
async def async_approver(
    real_async_db_session: AsyncSession, async_approval_org: Organization
) -> User:
    return await _async_create_user(
        real_async_db_session,
        async_approval_org,
        email=f'async_approver_{uuid.uuid4().hex[:8]}@example.com',
        role='manager',
    )


@pytest.fixture
async def async_approver2(
    real_async_db_session: AsyncSession, async_approval_org: Organization
) -> User:
    return await _async_create_user(
        real_async_db_session,
        async_approval_org,
        email=f'async_approver2_{uuid.uuid4().hex[:8]}@example.com',
        role='admin',
    )


@pytest.fixture
async def async_requester(
    real_async_db_session: AsyncSession, async_approval_org: Organization
) -> User:
    return await _async_create_user(
        real_async_db_session,
        async_approval_org,
        email=f'async_requester_{uuid.uuid4().hex[:8]}@example.com',
        role='user',
    )


@pytest.fixture
def multi_stage_workflow_payload() -> dict[str, Any]:
    return {
        'target_type': 'document',
        'requester_scope': {'everyone': True},
        'is_active': True,
        'expected_scope': {'holds': 'all'},
        'name': 'Multi Stage Approval',
        'stages': [
            {
                'order': 1,
                'role': 'manager',
                'label': 'Manager Approval',
                'approver_user_ids': [],
            },
            {
                'order': 2,
                'role': 'admin',
                'label': 'Director Confirmation',
                'approver_user_ids': [],
            },
        ],
    }
