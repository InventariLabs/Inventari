"""The monthly cost trend walks whole calendar months.

Subtracting 30-day chunks from the first of a month drifts across short
months: from March 1, one "30 days back" lands on January 30, so the trend
never shows February and labels January twice.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.analytics.cost import _compute_monthly_trend_async


@pytest.mark.integration
@pytest.mark.asyncio
class TestCostTrendMonthBuckets:
    async def test_six_buckets_from_march_first_are_distinct_consecutive_months(
        self,
        real_async_db_session: AsyncSession,
        async_test_household,
        async_test_storage_location,
    ) -> None:
        trend = await _compute_monthly_trend_async(
            real_async_db_session,
            async_test_household.id,
            'PLN',
            datetime(2025, 10, 1),
            date(2026, 3, 1),
        )

        assert [row.month for row in trend] == [
            '2025-10',
            '2025-11',
            '2025-12',
            '2026-01',
            '2026-02',
            '2026-03',
        ]
