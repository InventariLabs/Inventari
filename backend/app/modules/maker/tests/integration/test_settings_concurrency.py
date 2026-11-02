"""Regression: concurrent first ``get_settings`` calls must not 500.

Two parallel requests that both find no settings row used to race the
get-or-create INSERT and one died on the ``maker_module_settings_pkey``
unique constraint (observed as an Internal Server Error while parallel E2E
specs created the first production order for an org).
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.modules.maker.recipe_service import get_settings

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_concurrent_get_settings_creates_row_once(
    real_async_db_session: AsyncSession,
) -> None:
    org = Organization(name='Maker Settings Race Org', enabled_modules=['maker'])
    real_async_db_session.add(org)
    await real_async_db_session.commit()
    org_id = org.id

    engine = real_async_db_session.bind  # the AsyncEngine the fixture uses
    session_a = AsyncSession(bind=engine)
    session_b = AsyncSession(bind=engine)
    try:

        async def _first_get(session: AsyncSession) -> None:
            await get_settings(session, org_id, for_update=True)
            # The advisory lock is transaction-scoped: committing is what
            # releases it, exactly like a real request ending.
            await session.commit()

        await asyncio.gather(_first_get(session_a), _first_get(session_b))
    finally:
        await session_a.close()
        await session_b.close()

    # Both callers ended up with the same persisted row, created once.
    settings = await get_settings(real_async_db_session, org_id)
    assert settings.organization_id == org_id
    assert settings.availability_check_scope == 'GLOBAL'
