"""The date a record is judged by: the earlier of its batch and its use-by."""

from datetime import date

from app.core.open_package import effective_expiry, use_by_of

BATCH = date(2026, 12, 1)


def _opened(**extra: str) -> dict[str, dict[str, str]]:
    return {'opened': {'at': '2026-10-01T09:00:00+00:00', **extra}}


class TestEffectiveExpiry:
    def test_without_a_use_by_it_is_the_batch_date(self) -> None:
        assert effective_expiry(BATCH, None) == BATCH
        assert effective_expiry(BATCH, _opened()) == BATCH

    def test_an_earlier_use_by_wins(self) -> None:
        meta = _opened(use_by='2026-10-20')
        assert effective_expiry(BATCH, meta) == date(2026, 10, 20)

    def test_a_later_use_by_changes_nothing(self) -> None:
        assert effective_expiry(BATCH, _opened(use_by='2027-03-01')) == BATCH

    def test_a_use_by_stands_alone_when_the_batch_has_no_date(self) -> None:
        assert effective_expiry(None, _opened(use_by='2026-10-20')) == date(
            2026, 10, 20
        )

    def test_neither_date_is_no_date(self) -> None:
        assert effective_expiry(None, _opened()) is None

    def test_a_use_by_that_is_not_a_date_is_ignored(self) -> None:
        assert use_by_of(_opened(use_by='soon')) is None
        assert effective_expiry(BATCH, _opened(use_by='soon')) == BATCH
