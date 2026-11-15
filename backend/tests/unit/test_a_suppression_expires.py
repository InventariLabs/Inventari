"""A green gate resting on a stale premise is worse than no gate.

Three suppressions in this repository were accepted on written reasoning that
nobody re-read. One of them excused a select-then-mutate site because "the
only true race is serialised by the advisory lock in _next_order_number()" --
true only after that lock stopped keying itself on Python's per-process
hash(), which it did not do until much later. The entry was green, reviewed,
and false for as long as it mattered.

So a suppression that stands for debt carries an owner and a date, and the
lint enforces both. The date warns once it passes; it refuses nothing. A date
in the code would refuse whoever commits that day, not whoever owns the
entry -- in a public repository an outside contributor who cannot fix the
file -- and every released version would turn red for good after it. An
exception that is right by design carries no date at all: it lives in an
allowlist, where adding one is a change with its reason in the diff.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.architecture_lint import _baselines
from app.core.architecture_lint._constants import VULTURE_WHITELIST_FILE
from app.core.architecture_lint._main import _fails_the_run
from app.core.architecture_lint._quality_checks_reserved_surface import (
    _check_reserved_surface,
)

pytestmark = pytest.mark.unit

_TODAY = date(2026, 8, 30)
#: Past every date a list in this repository carries.
_LONG_AFTER = date(2099, 12, 31)


class TestTheSelectThenMutateBaseline:
    @pytest.mark.parametrize(
        'line,expected',
        [
            ('app/x.py:1:create', 'malformed'),
            ('app/x.py:1:create | owner= | expires=2099-01-01 | why', 'names nobody'),
            ('app/x.py:1:create | owner=me | expires=soon | why', 'unreadable expiry'),
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
        assert errors[0].startswith('::error')
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

    def test_an_entry_past_its_date_warns_and_still_holds(
        self, tmp_path, monkeypatch
    ) -> None:
        path = tmp_path / 'toctou.txt'
        path.write_text(
            'app/x.py:1:create | owner=core | expires=2020-01-01 | why\n',
            encoding='utf-8',
        )
        monkeypatch.setattr(_baselines, 'TOCTOU_RISK_BASELINE_FILE', path)

        keys, findings = _baselines._load_toctou_risk_baseline(_TODAY)

        assert keys == {'app/x.py:1:create'}
        assert len(findings) == 1
        assert findings[0].startswith('::warning')
        assert 'expired on 2020-01-01' in findings[0]
        assert not _fails_the_run(findings)


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
        assert errors[0].startswith('::error')
        assert 'without an owner' in errors[0]
        assert 'maker_api' in errors[0]

    def test_a_name_past_its_date_warns(self, tmp_path) -> None:
        path = self._whitelist(
            tmp_path,
            'maker_api  # noqa: B018  # owner=core expires=2020-01-01 kept for modules',
        )

        findings = _check_reserved_surface(path, _TODAY)

        assert len(findings) == 1
        assert findings[0].startswith('::warning')
        assert 'expired' in findings[0]
        assert not _fails_the_run(findings)

    def test_a_dated_name_is_accepted(self, tmp_path) -> None:
        path = self._whitelist(
            tmp_path,
            'maker_api  # noqa: B018  # owner=core expires=2027-01-01 kept for modules',
        )

        assert _check_reserved_surface(path, _TODAY) == []


class TestTheAuditCoverageLists:
    """By design in an allowlist without a date; debt in a dated baseline."""

    def _lists(self, tmp_path, monkeypatch, *, allowlist: str, baseline: str = ''):
        allow = tmp_path / 'audit_coverage_allowlist.txt'
        allow.write_text(f'# header\n{allowlist}', encoding='utf-8')
        debt = tmp_path / 'audit_coverage_baseline.txt'
        debt.write_text(f'# header\n{baseline}', encoding='utf-8')
        monkeypatch.setattr(_baselines, 'AUDIT_COVERAGE_ALLOWLIST_FILE', allow)
        monkeypatch.setattr(_baselines, 'AUDIT_COVERAGE_BASELINE_FILE', debt)

    def test_a_by_design_entry_needs_no_date(self, tmp_path, monkeypatch) -> None:
        self._lists(
            tmp_path,
            monkeypatch,
            allowlist='api/auth.py::login | pre-session: there is no actor yet.\n',
        )

        keys, findings = _baselines._load_audit_coverage_baseline(_LONG_AFTER)

        assert keys == {'api/auth.py::login'}
        assert findings == []

    @pytest.mark.parametrize(
        'line,expected',
        [
            ('api/auth.py::login', 'malformed'),
            ('api/auth.py::login | ', 'malformed'),
            (
                'api/auth.py::login | owner=core | expires=2099-01-01 | why',
                'dated',
            ),
        ],
    )
    def test_a_by_design_entry_states_its_reason_and_no_date(
        self, tmp_path, monkeypatch, line: str, expected: str
    ) -> None:
        self._lists(tmp_path, monkeypatch, allowlist=f'{line}\n')

        keys, findings = _baselines._load_audit_coverage_baseline(_TODAY)

        assert keys == set()
        assert len(findings) == 1
        assert findings[0].startswith('::error')
        assert expected in findings[0]

    def test_a_debt_entry_past_its_date_warns_and_still_holds(
        self, tmp_path, monkeypatch
    ) -> None:
        self._lists(
            tmp_path,
            monkeypatch,
            allowlist='api/auth.py::login | pre-session: there is no actor yet.\n',
            baseline='api/x.py::cancel | owner=core | expires=2020-01-01 | lost its entry\n',
        )

        keys, findings = _baselines._load_audit_coverage_baseline(_TODAY)

        assert keys == {'api/auth.py::login', 'api/x.py::cancel'}
        assert len(findings) == 1
        assert findings[0].startswith('::warning')
        assert 'api/x.py::cancel' in findings[0]


class TestNoDateInTheRepositoryRefusesACommit:
    """Long after every date the lists carry, the lint still passes.

    Each list is read as it stands in the tree with "today" set past every
    date in it: an entry may warn, none may refuse, and none may drop out —
    a key that fell out of its list would turn the finding it covers red.
    """

    @pytest.mark.parametrize(
        'loader',
        [
            _baselines._load_toctou_risk_baseline,
            _baselines._load_audit_coverage_baseline,
            _baselines._load_escape_hatch_query_scope_baseline,
            _baselines._load_test_skip_baseline,
            _baselines._load_manifest_permission_deferrals,
        ],
    )
    def test_an_owned_list_only_warns(self, loader) -> None:
        keys_then, findings_then = loader(_TODAY)
        keys_later, findings_later = loader(_LONG_AFTER)

        assert not _fails_the_run(findings_then)
        assert not _fails_the_run(findings_later)
        assert keys_later == keys_then

    def test_the_module_surface_only_warns(self) -> None:
        modules_then, _ = _baselines._load_module_import_surface_baseline(_TODAY)
        modules_later, findings = _baselines._load_module_import_surface_baseline(
            _LONG_AFTER
        )

        assert not _fails_the_run(findings)
        assert modules_later == modules_then

    def test_the_reserved_surface_only_warns(self) -> None:
        assert _check_reserved_surface(VULTURE_WHITELIST_FILE, _TODAY) == []
        findings = _check_reserved_surface(VULTURE_WHITELIST_FILE, _LONG_AFTER)

        assert not _fails_the_run(findings)


class TestWhatFailsTheRun:
    def test_a_warning_alone_does_not(self) -> None:
        assert not _fails_the_run(['::warning file=x,title=t::passed its date'])

    def test_an_error_does(self) -> None:
        assert _fails_the_run(['::warning file=x::w', '::error file=x::e'])

    def test_a_finding_that_is_not_a_line_does(self) -> None:
        """The forbidden-import check hands back objects, not annotation lines."""
        assert _fails_the_run([object()])

    def test_nothing_does_not(self) -> None:
        assert not _fails_the_run([])
