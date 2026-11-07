"""Two first postings of one organization leave one document profile.

``get_or_create_profile`` read, found nothing and inserted, with nothing
handling a second caller doing the same for the same organization between
the read and the insert. Two stock takes closed together on a fresh
organization (or a receipt and an issue) both reached the insert, and the
second one answered 500 on ``uq_document_profile_org``.

The race window is a few microseconds wide, so the test closes it by hand:
both callers wait at the first read until each has seen "no profile", and
only then go on to create one.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.modules.warehouse import document_profile_service as profiles
from app.modules.warehouse.models import DocumentProfile


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


@pytest.mark.integration
@pytest.mark.asyncio
class TestTwoFirstPostings:
    async def test_both_get_the_one_profile(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        monkeypatch: pytest.MonkeyPatch,
    ):
        org_id = async_test_household.id
        # The two postings run on sessions of their own: the organization has
        # to be committed for them to see it.
        await real_async_db_session.commit()
        engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )

        real_get_profile = profiles.get_profile
        both_have_looked = asyncio.Barrier(2)
        reads = 0

        async def get_profile_after_both_looked(db, org):
            nonlocal reads
            reads += 1
            first_read = reads <= 2
            found = await real_get_profile(db, org)
            if first_read:
                await both_have_looked.wait()
            return found

        monkeypatch.setattr(profiles, 'get_profile', get_profile_after_both_looked)

        async def first_posting() -> str:
            async with factory() as session:
                profile = await profiles.get_or_create_profile(session, org_id)
                await session.commit()
                return str(profile.id)

        try:
            ids = await asyncio.gather(first_posting(), first_posting())
            async with factory() as verify:
                count = await verify.scalar(
                    select(func.count())
                    .select_from(DocumentProfile)
                    .where(DocumentProfile.organization_id == org_id)
                )
        finally:
            await engine.dispose()

        assert count == 1
        assert ids[0] == ids[1]
