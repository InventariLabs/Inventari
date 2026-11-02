"""Unit tests for app.core.async_utils."""

import asyncio
from datetime import date

import pytest

from app.core.async_utils import run_sync_in_thread
from app.core.datetimes import format_date_for, set_request_country


@pytest.mark.unit
def test_the_thread_reads_the_callers_request_country() -> None:
    """A document rendered off the loop still writes the organization's date order."""

    async def scenario() -> str:
        set_request_country('GB')
        return await run_sync_in_thread(lambda: format_date_for('en', date(2026, 4, 3)))

    assert asyncio.run(scenario()) == '3 Apr 2026'
