"""A day ends where the organization is, not where the server is.

``Organization.timezone`` has been on the row since the beginning and
nothing in the backend ever read it — a grep for a reader came back empty.
Every report cut its days and months on the server's ``date.today()``, and
every window compared a timestamp column against a bare date, which Postgres
reads as midnight UTC. So a warehouse in Auckland saw its month close at
11am local, and an event at one in the morning on the local first landed in
the previous month's figures.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.analytics._common import (
    org_today_async,
    org_window_start_async,
)


@pytest.mark.integration
@pytest.mark.asyncio
class TestReportsUseTheOrganizationsClock:
    async def test_today_is_the_local_day_not_the_servers(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        db = real_async_db_session
        org = async_test_household

        # 22:30 UTC on the 14th is already the 15th in Auckland.
        instant = datetime(2026, 6, 14, 22, 30, tzinfo=UTC)

        org.timezone = 'UTC'
        await db.flush()
        assert await org_today_async(db, org.id, now=instant) == date(2026, 6, 14)

        org.timezone = 'Pacific/Auckland'
        await db.flush()
        assert await org_today_async(db, org.id, now=instant) == date(2026, 6, 15)

    async def test_a_window_starts_when_the_local_day_started(
        self, real_async_db_session: AsyncSession, async_test_household
    ) -> None:
        db = real_async_db_session
        org = async_test_household
        org.timezone = 'Pacific/Auckland'
        await db.flush()

        instant = datetime(2026, 6, 14, 22, 30, tzinfo=UTC)
        start = await org_window_start_async(db, org.id, 30, now=instant)

        # Thirty days back from the local 15th is the local 16th of May, and
        # the window opens when that day began there — 12:00 UTC on the 15th.
        assert start.astimezone(UTC) == datetime(2026, 5, 15, 12, 0, tzinfo=UTC)

    @pytest.mark.parametrize('zone', ['Not/AZone', 'Europe/'])
    async def test_an_unusable_zone_falls_back_instead_of_failing(
        self, real_async_db_session: AsyncSession, async_test_household, zone: str
    ) -> None:
        """One bad row must not take a dashboard down."""
        db = real_async_db_session
        org = async_test_household
        org.timezone = zone
        await db.flush()

        instant = datetime(2026, 6, 14, 22, 30, tzinfo=UTC)
        assert await org_today_async(db, org.id, now=instant) == date(2026, 6, 14)
