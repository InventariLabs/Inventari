"""Two first reads of an organization's order settings leave one row.

A fresh organization has no settings row. Two requests that open the order
list together both find none and both create one; the second hit
``uq_po_settings_org`` and answered 500. The first side here inserts and
holds its transaction open, the second arrives while the row is still
uncommitted, and both must come away with the one row that stands.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models.organization import Organization
from app.modules.purchase_orders._service_settings import get_or_create_po_settings
from app.modules.purchase_orders.models import POSettings

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class TestTwoFirstReadsOfTheSettingsMakeOneRow:
    async def test_the_second_reader_gets_the_row_the_first_made(
        self, real_async_db_session: AsyncSession
    ) -> None:
        org = Organization(name=f'First read {uuid.uuid4().hex[:6]}')
        real_async_db_session.add(org)
        await real_async_db_session.commit()

        url = settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)
        engine = create_async_engine(url, echo=False, poolclass=NullPool)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        first = factory()
        second = factory()
        try:
            made = await get_or_create_po_settings(first, org.id)
            waiting = asyncio.create_task(get_or_create_po_settings(second, org.id))
            await asyncio.sleep(0.3)
            # Not failed and not answered: it waits on the row the first made.
            assert not waiting.done()

            await first.commit()
            found = await waiting
            await second.commit()
            assert found.id == made.id
        finally:
            await first.close()
            await second.close()
            await engine.dispose()

        count = await real_async_db_session.scalar(
            select(func.count(POSettings.id)).where(POSettings.organization_id == org.id)
        )
        assert count == 1
