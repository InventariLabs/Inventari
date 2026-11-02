"""Unit tests for ``equipment.notification_worker._as_date``.

Regression: ``datetime < date`` raises ``TypeError`` because ``datetime``
is a subclass of ``date``. The worker uses ``date.today()`` and the
``expected_return_at`` column is ``DateTime(timezone=True)``, so any
production deployment with overdue assignments crashed on the
``isinstance(expected, date) and expected < now`` check.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.modules.equipment.notification_worker import _as_date

pytestmark = pytest.mark.unit


class TestAsDate:
    def test_passthrough_plain_date(self) -> None:
        d = date(2026, 1, 15)
        assert _as_date(d) is d

    def test_datetime_to_date_strips_time(self) -> None:
        moment = datetime(2026, 1, 15, 14, 30, 45, tzinfo=UTC)
        result = _as_date(moment)
        assert result == date(2026, 1, 15)
        assert isinstance(result, date)

    def test_naive_datetime_to_date(self) -> None:
        moment = datetime(2026, 7, 1, 23, 59, 59)
        assert _as_date(moment) == date(2026, 7, 1)

    def test_datetime_reads_the_org_day_when_a_zone_is_given(self) -> None:
        # The return day is pinned to the end of its day on the org's clock
        # (review 2026-09-23): the last microsecond of Sep 30 in Los Angeles
        # is already Oct 1 in UTC, and the worker compares org days.
        moment = datetime(2026, 10, 1, 6, 59, 59, 999999, tzinfo=UTC)
        assert _as_date(moment, ZoneInfo('America/Los_Angeles')) == date(2026, 9, 30)
        # Without a zone the old callers keep the day their own clock read.
        assert _as_date(moment) == date(2026, 10, 1)

    def test_compare_with_date_today_no_typeerror(self) -> None:
        """Regression: the original crash was a ``TypeError`` here."""
        moment = datetime.now(tz=UTC) - timedelta(days=5)
        result = _as_date(moment)
        # This would raise TypeError if _as_date returned the datetime untouched.
        assert result < date.today() + timedelta(days=1)
