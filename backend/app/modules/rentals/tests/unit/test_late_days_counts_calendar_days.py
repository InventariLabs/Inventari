"""How late a loan reads: calendar days behind the promised return."""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.rentals.service import _late_days


class TestLateDays:
    def test_a_loan_not_due_yet_is_not_late(self) -> None:
        now = datetime(2024, 11, 26, 10, 0, tzinfo=UTC)
        assert _late_days(datetime(2024, 11, 26, 11, 0, tzinfo=UTC), now) == 0

    def test_a_loan_counts_nothing_at_the_minute_it_is_due(self) -> None:
        now = datetime(2024, 11, 26, 10, 0, tzinfo=UTC)
        assert _late_days(now, now) == 0

    def test_the_day_after_the_due_date_is_one_day_late(self) -> None:
        now = datetime(2024, 11, 26, 20, 0, tzinfo=UTC)
        due = datetime(2024, 11, 25, 17, 0, tzinfo=UTC)
        assert _late_days(due, now) == 1

    def test_late_on_the_same_evening_counts_one_day(self) -> None:
        now = datetime(2024, 11, 26, 20, 0, tzinfo=UTC)
        due = datetime(2024, 11, 26, 17, 0, tzinfo=UTC)
        assert _late_days(due, now) == 1

    def test_two_days_behind_reads_two_not_three(self) -> None:
        now = datetime(2024, 11, 26, 9, 0, tzinfo=UTC)
        due = datetime(2024, 11, 24, 17, 0, tzinfo=UTC)
        assert _late_days(due, now) == 2
