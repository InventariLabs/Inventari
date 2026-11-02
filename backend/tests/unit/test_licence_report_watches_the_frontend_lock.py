"""The licence gate reads the frontend lockfile, not only the backend's.

`THIRD_PARTY_LICENSES.md` carries a frontend table of what the production
bundle ships, and only the full generator could write it — while the
freshness hook's `files` pattern named `backend/uv.lock` and
`frontend/public/*` but not `frontend/package-lock.json`. A dependency added,
bumped or removed on the frontend side moved the lock and the report kept
quoting the old tree, with no gate at commit time in front of it: only
`make lint`, which AGENTS.md calls the gate that runs *after* the branch
leaves. So the pattern has to name the frontend manifest and lock, and the
check has to be able to fail on what they say — a pattern that fires and then
passes is the same hole with a door in it.

The header is here for the same reason: it promised a CI run on every pull
request while `.github/workflows/license-scan.yml` answers `workflow_dispatch`
only, so what actually checks the report is the pre-commit hook and
`make lint`, and that is what the wording — written by the generator, so
regeneration keeps it — has to say.
"""

import json
import os
import re
from pathlib import Path

import pytest
import yaml

from app.cli._deps_licenses_report import _HEADER as GENERATED_HEADER
from scripts.check_licences_fresh import (
    _locked_frontend_packages,
    _reported_frontend_rows,
    frontend_coverage_gaps,
    frontend_row_problems,
    frontend_table_complaints,
)

pytestmark = pytest.mark.unit

#: The checkout root, wherever this test runs: on the host three parents above
#: this file, in the container the read-only mount docker-compose.yml names
#: with ``INVENTARI_REPO_ROOT``.
_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)


def _report(tmp_path: Path, body: str) -> Path:
    report = tmp_path / 'THIRD_PARTY_LICENSES.md'
    report.write_text('# Third-party licences\n\n' + body, encoding='utf-8')
    return report


def _lock(tmp_path: Path, packages: dict) -> Path:
    lock = tmp_path / 'package-lock.json'
    lock.write_text(
        json.dumps({'lockfileVersion': 3, 'packages': packages}), encoding='utf-8'
    )
    return lock


class TestTheFrontendTableIsRead:
    def test_rows_are_pairs_so_two_versions_of_one_name_both_stand(
        self, tmp_path: Path
    ) -> None:
        """npm ships two versions of one package at different depths; both ship."""
        report = _report(
            tmp_path,
            '## Frontend production bundle (3 packages)\n\n'
            '| Package | Version | Licence | Note |\n|---|---|---|---|\n'
            '| `glob-parent` | 7.0.0 | MIT |  |\n'
            '| `glob-parent` | 6.0.0 | MIT |  |\n'
            '| `react` | 18.2.0 | MIT |  |\n',
        )

        assert _reported_frontend_rows(report) == {
            ('glob-parent', '7.0.0'),
            ('glob-parent', '6.0.0'),
            ('react', '18.2.0'),
        }

    def test_rows_of_the_backend_table_do_not_count(self, tmp_path: Path) -> None:
        report = _report(
            tmp_path,
            '## Backend runtime (1 packages)\n\n'
            '| Package | Version | Licence | Note |\n|---|---|---|---|\n'
            '| `fastapi` | 0.1.0 | MIT |  |\n',
        )

        assert _reported_frontend_rows(report) == set()

    def test_a_missing_section_is_nothing_to_check_not_a_crash(
        self, tmp_path: Path
    ) -> None:
        assert _reported_frontend_rows(_report(tmp_path, '')) == set()


class TestTheLockfileIsRead:
    def test_dev_only_entries_are_left_out(self, tmp_path: Path) -> None:
        """The table is `npm ls --omit=dev`; the dev half of the lock is not."""
        lock = _lock(
            tmp_path,
            {
                '': {'name': 'inventari-frontend', 'version': '0.10.0'},
                'node_modules/react': {'version': '18.2.0'},
                'node_modules/vite': {'version': '8.3.1', 'dev': True},
            },
        )

        packages, conditional = _locked_frontend_packages(lock)

        assert packages == {('react', '18.2.0')}
        assert conditional == set()

    def test_the_name_comes_from_the_path_when_the_entry_carries_none(
        self, tmp_path: Path
    ) -> None:
        """A nested path names its last segment; the report spells it the same way."""
        lock = _lock(
            tmp_path,
            {'node_modules/@alloc/quick-lru': {'version': '5.3.0'}},
        )

        assert _locked_frontend_packages(lock)[0] == {('@alloc/quick-lru', '5.3.0')}

    def test_a_platform_conditional_package_is_marked_as_such(
        self, tmp_path: Path
    ) -> None:
        """fsevents only installs on macOS, so a Linux report never names it."""
        lock = _lock(
            tmp_path,
            {
                'node_modules/fsevents': {'version': '2.3.3', 'optional': True},
                'node_modules/clsx': {'version': '2.1.1'},
            },
        )

        packages, conditional = _locked_frontend_packages(lock)

        assert packages == {('fsevents', '2.3.3'), ('clsx', '2.1.1')}
        assert conditional == {('fsevents', '2.3.3')}


class TestRowProblems:
    def test_a_bumped_version_is_named_with_both_numbers(self) -> None:
        """One complaint quoting the row the reader sees and the lock's answer."""
        problems = frontend_row_problems(
            {('react-dom', '18.2.0')}, {('react-dom', '18.3.1')}
        )

        assert problems == [
            'react-dom: report says 18.2.0, package-lock.json says 18.3.1'
        ]

    def test_a_package_the_lock_does_not_hold_is_named_as_gone(self) -> None:
        problems = frontend_row_problems({('removed', '1.0.0')}, set())

        assert problems == [
            'removed: report says 1.0.0, package-lock.json lists no such package'
        ]

    def test_two_locked_versions_of_one_name_report_as_one_drift(self) -> None:
        problems = frontend_row_problems(
            {('glob-parent', '5.0.0')},
            {('glob-parent', '6.0.0'), ('glob-parent', '7.0.0')},
        )

        assert problems == [
            'glob-parent: report says 5.0.0, package-lock.json says 6.0.0 or 7.0.0'
        ]

    def test_rows_the_lock_resolves_leave_nothing_to_say(self) -> None:
        reported = {('react', '18.2.0'), ('glob-parent', '7.0.0')}
        locked = {('react', '18.2.0'), ('glob-parent', '7.0.0'), ('clsx', '2.1.1')}

        assert frontend_row_problems(reported, locked) == []

    def test_a_second_locked_version_does_not_disturb_a_standing_row(self) -> None:
        """The name having another version is not a complaint about this row."""
        reported = {('glob-parent', '7.0.0')}
        locked = {('glob-parent', '7.0.0'), ('glob-parent', '6.0.0')}

        assert frontend_row_problems(reported, locked) == []


class TestCoverageGaps:
    def test_a_production_package_with_no_row_is_named(self) -> None:
        gaps = frontend_coverage_gaps(set(), {('new-dep', '1.2.3')})

        assert gaps == ['new-dep@1.2.3']

    def test_a_platform_conditional_package_is_not_demanded(self) -> None:
        """The report is generated where the deployment runs; fsevents is not."""
        gaps = frontend_coverage_gaps(
            set(),
            {('clsx', '2.1.1'), ('fsevents', '2.3.3')},
            {('fsevents', '2.3.3')},
        )

        assert gaps == ['clsx@2.1.1']

    def test_full_coverage_says_nothing(self) -> None:
        reported = {('react', '18.2.0'), ('clsx', '2.1.1')}
        locked = {('react', '18.2.0'), ('clsx', '2.1.1')}

        assert frontend_coverage_gaps(reported, locked) == []


class TestTheShippedReport:
    def test_the_frontend_table_agrees_with_the_lockfile(self) -> None:
        """The real files: every row stands, every production package is listed.

        Reads what the gate reads, so a lockfile changed without regenerating
        the report fails here as well as at the commit hook. Both files are
        tracked, so there is nothing to wait for and nothing to skip.
        """
        locked, conditional = _locked_frontend_packages(
            _REPO_ROOT / 'frontend' / 'package-lock.json'
        )
        rows = _reported_frontend_rows(_REPO_ROOT / 'THIRD_PARTY_LICENSES.md')

        assert rows, 'no "## Frontend production bundle" rows parsed'
        assert frontend_row_problems(rows, locked) == []
        assert frontend_coverage_gaps(rows, locked, conditional) == []

    def test_the_table_carries_a_version_column(self) -> None:
        """The row shape the version comparison is built on still holds."""
        rows = _reported_frontend_rows(_REPO_ROOT / 'THIRD_PARTY_LICENSES.md')

        assert all(version for _, version in rows), (
            'a row with an empty version cell is a version the gate cannot compare'
        )


class TestTheComplaintsAreGrouped:
    def test_the_standing_table_produces_nothing_to_print(self) -> None:
        rows = _reported_frontend_rows(_REPO_ROOT / 'THIRD_PARTY_LICENSES.md')
        lock = _REPO_ROOT / 'frontend' / 'package-lock.json'

        assert frontend_table_complaints(rows, lock) == []

    def test_a_row_the_real_lock_does_not_resolve_is_one_refusal(self) -> None:
        """One stale row on an otherwise current table is one refusal."""
        report = _REPO_ROOT / 'THIRD_PARTY_LICENSES.md'
        lock = _REPO_ROOT / 'frontend' / 'package-lock.json'
        rows = _reported_frontend_rows(report) | {('not-in-the-lock', '1.0.0')}

        assert frontend_table_complaints(rows, lock) == [
            (
                'these frontend rows are not packages package-lock.json '
                'resolves for production',
                [
                    'not-in-the-lock: report says 1.0.0, package-lock.json '
                    'lists no such package'
                ],
            )
        ]


class TestTheHookWatchesTheFrontendFiles:
    def test_the_files_pattern_names_the_frontend_manifest_and_lock(self) -> None:
        """Without these two, a lockfile change never runs the check at all."""
        config = yaml.safe_load(
            (_REPO_ROOT / '.pre-commit-config.yaml').read_text(encoding='utf-8')
        )
        pattern = next(
            hook['files']
            for repo in config['repos']
            for hook in repo['hooks']
            if hook['id'] == 'licences-fresh'
        )

        for filename in (
            'frontend/package.json',
            'frontend/package-lock.json',
            'backend/pyproject.toml',
            'backend/uv.lock',
            'THIRD_PARTY_LICENSES.md',
            'frontend/public/emoji/logo.svg',
        ):
            assert re.search(pattern, filename), (
                f'{pattern!r} does not fire on {filename}'
            )


class TestWhatTheHeaderPromises:
    def test_the_generator_writes_the_header_the_report_carries(self) -> None:
        """Regeneration must not revert a corrected header to the old claim."""
        report = (_REPO_ROOT / 'THIRD_PARTY_LICENSES.md').read_text(encoding='utf-8')

        assert report.startswith(GENERATED_HEADER.rstrip())

    def test_the_header_names_the_gates_that_actually_run(self) -> None:
        assert 'licences-fresh' in GENERATED_HEADER
        assert 'make lint' in GENERATED_HEADER

    def test_the_header_no_longer_claims_a_ci_run_that_is_switched_off(self) -> None:
        """The wording it replaced promised a pull-request CI run nobody runs."""
        assert 'CI does this on every' not in GENERATED_HEADER
        assert 'every pull request' not in GENERATED_HEADER
