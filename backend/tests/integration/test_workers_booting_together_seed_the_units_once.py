"""Every worker of a fresh install seeds the units at the same moment."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.database
from app.seed_data import seed_all_async

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

WORKERS = 4


async def test_four_workers_seeding_an_empty_catalogue_write_it_once(
    real_async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Pack reference unit once broke ``uq_uom_category_reference``.

    Each worker counted an empty ``uoms`` table before any of them had
    written, then all inserted the same reference units.
    """
    engine = real_async_db_session.bind
    await real_async_db_session.execute(text('DELETE FROM uoms'))
    await real_async_db_session.commit()
    monkeypatch.setattr(
        app.database,
        'AsyncSessionLocal',
        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
    )

    results = await asyncio.gather(
        *(seed_all_async() for _ in range(WORKERS)), return_exceptions=True
    )

    assert [r for r in results if r is not None] == []
    duplicated = (
        await real_async_db_session.execute(
            text(
                'SELECT category_id FROM uoms WHERE is_reference '
                'GROUP BY category_id HAVING COUNT(*) > 1'
            )
        )
    ).all()
    assert duplicated == []
    assert (await real_async_db_session.scalar(text('SELECT COUNT(*) FROM uoms'))) > 0
