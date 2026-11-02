"""Creating a cycle-count schedule is not durable until the caller commits.

The service used to commit inside the call, so a request that failed after
it left a schedule (and its log entry) behind. The caller owns the commit
now: a rollback after the call leaves nothing.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User
from app.modules.stock_takes.cycle_count_service import create_schedule
from app.modules.stock_takes.models import CycleCountSchedule


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_rollback_after_the_call_leaves_no_schedule(
    real_async_db_session: AsyncSession,
) -> None:
    org = Organization(
        name=f'Schedule Org {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'stock_takes'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    user = User(
        email=f'schedule_{uuid.uuid4().hex[:8]}@test.com',
        hashed_password='x',
        full_name='Schedule User',
        organization_id=org.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.commit()
    org_id, user_id = org.id, user.id

    await create_schedule(real_async_db_session, org_id, user_id, name='Weekly')
    await real_async_db_session.rollback()

    count = await real_async_db_session.scalar(
        select(func.count())
        .select_from(CycleCountSchedule)
        .where(CycleCountSchedule.organization_id == org_id)
    )
    assert count == 0
