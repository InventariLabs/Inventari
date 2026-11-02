"""A green gate resting on a stale premise is worse than no gate.

Three suppressions in this repository were accepted on written reasoning that
nobody re-read. One of them excused a select-then-mutate site because "the
only true race is serialised by the advisory lock in _next_order_number()" --
true only after that lock stopped keying itself on Python's per-process
hash(), which it did not do until much later. The entry was green, reviewed,
and false for as long as it mattered.

So a suppression now carries an owner and a date, and the lint enforces both.
The convention was already in the repository for manifest permissions; these
tests hold the two lists that had drifted out of it to the same rule.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.architecture_lint import _baselines
from app.core.architecture_lint._quality_checks_reserved_surface import (
    _check_reserved_surface,
)

pytestmark = pytest.mark.unit

_TODAY = date(2026, 8, 30)


class TestTheSelectThenMutateBaseline:
    @pytest.mark.parametrize(
        'line,expected',
        [
            ('app/x.py:1:create', 'malformed'),
            ('app/x.py:1:create | owner= | expires=2099-01-01 | why', 'names nobody'),
            ('app/x.py:1:create | owner=me | expires=soon | why', 'unreadable expiry'),
            ('app/x.py:1:create | owner=me | expires=2020-01-01 | why', 'expired'),
            ('app/x.py:1:create | owner=me | expires=2099-01-01 |', 'malformed'),
        ],
    )
    def test_it_refuses_an_entry_nobody_owns(
        self, tmp_path, monkeypatch, line: str, expected: str
    ) -> None:
        path = tmp_path / 'toctou.txt'
        path.write_text(f'# header\n{line}\n', encoding='utf-8')
        monkeypatch.setattr(_baselines, 'TOCTOU_RISK_BASELINE_FILE', path)

        keys, errors = _baselines._load_toctou_risk_baseline(_TODAY)

        assert keys == set()
        assert len(errors) == 1
        assert expected in errors[0]

    def test_a_dated_entry_is_accepted(self, tmp_path, monkeypatch) -> None:
        path = tmp_path / 'toctou.txt'
        path.write_text(
            'app/x.py:1:create | owner=core | expires=2027-01-01 | '
            'Serialised by the unique index; verify by dropping it.\n',
            encoding='utf-8',
        )
        monkeypatch.setattr(_baselines, 'TOCTOU_RISK_BASELINE_FILE', path)

        keys, errors = _baselines._load_toctou_risk_baseline(_TODAY)

        assert keys == {'app/x.py:1:create'}
        assert errors == []


class TestTheDeadCodeWhitelist:
    def _whitelist(self, tmp_path, body: str):
        path = tmp_path / 'vulture_whitelist.py'
        path.write_text(
            '# --- Callers the scan reaches ---\n'
            'something_used  # noqa: B018\n'
            '# --- begin reserved surface ---\n'
            f'{body}\n'
            '# --- end reserved surface ---\n'
            'another_used  # noqa: B018\n',
            encoding='utf-8',
        )
        return path

    def test_a_name_with_no_owner_is_refused(self, tmp_path) -> None:
        path = self._whitelist(tmp_path, 'maker_api  # noqa: B018')

        errors = _check_reserved_surface(path, _TODAY)

        assert len(errors) == 1
        assert 'without an owner' in errors[0]
        assert 'maker_api' in errors[0]

    def test_a_name_past_its_date_is_refused(self, tmp_path) -> None:
        path = self._whitelist(
            tmp_path,
            'maker_api  # noqa: B018  # owner=core expires=2020-01-01 kept for modules',
        )

        errors = _check_reserved_surface(path, _TODAY)

        assert len(errors) == 1
        assert 'expired' in errors[0]

    def test_a_dated_name_is_accepted(self, tmp_path) -> None:
        path = self._whitelist(
            tmp_path,
            'maker_api  # noqa: B018  # owner=core expires=2027-01-01 kept for modules',
        )

        assert _check_reserved_surface(path, _TODAY) == []

    def test_names_outside_the_section_are_left_alone(self, tmp_path) -> None:
        """The rest of the file claims a caller exists, which a grep settles."""
        path = self._whitelist(
            tmp_path,
            'maker_api  # noqa: B018  # owner=core expires=2027-01-01 kept for modules',
        )

        assert _check_reserved_surface(path, _TODAY) == []


class TestTheListsInTheRepository:
    def test_the_select_then_mutate_baseline_is_clean(self) -> None:
        _keys, errors = _baselines._load_toctou_risk_baseline(_TODAY)
        assert errors == []

    def test_the_reserved_surface_is_clean(self) -> None:
        from app.core.architecture_lint._constants import VULTURE_WHITELIST_FILE

        assert _check_reserved_surface(VULTURE_WHITELIST_FILE, _TODAY) == []
