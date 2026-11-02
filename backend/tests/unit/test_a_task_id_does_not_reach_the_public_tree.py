"""The backlog is private, so its identifiers cannot explain anything here.

A comment that cites a backlog task by its number points a reader of this
repository at something they cannot open, and it stands in for the reason
instead of giving it. AGENTS.md already says a task id appears nowhere in this
repository; this is the part that keeps it true for the tree, because the rule
had drifted to 135 references before anybody counted. The history has its own
check (test_a_commit_message_is_prose.py).

The distinction the checker has to get right is between an identifier and a
citation. "AGENTS.md §3" and "ADR-004" name documents a reader can open and
must keep working; a task number or a plan step does not.

Test files are in the public tree exactly like production ones, so they are
read too. The references that predate that decision sit in the baseline,
each with an owner and an expiry, and the entry list only ever gets shorter.

This file is read too, with no exemption by name. So none of the identifiers
it plants sits here as written: a task number is built by ``_id`` and every
other fixture is split with ``+`` where the pattern would match, which keeps
the file clean while each assertion still sees the whole identifier.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_internal_ids import (
    hit_key,
    load_baseline,
    load_prefixes,
    new_findings,
    public_tree_roots,
    scan,
    stale_entries,
    ticket_pattern,
)

pytestmark = pytest.mark.unit

#: The checkout root, wherever this test runs: on the host three parents
#: above this file, in the container the read-only mount docker-compose.yml
#: names with ``INVENTARI_REPO_ROOT``.
_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

#: The roots ``make lint`` passes: one function builds them for both, so the
#: Makefile and this suite cannot measure different trees.
_REPO_SCAN_ROOTS = public_tree_roots(_REPO_ROOT)


def _id(number: int) -> str:
    """A task identifier under the public prefix, assembled at run time."""
    return f'INV-{number}'


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')
    return tmp_path


def _key_of(root: Path) -> str:
    hits = scan([root])
    assert hits, 'nothing was scanned, so there is no key to build'
    return hit_key(hits[0])


class TestWhatItCatches:
    @pytest.mark.parametrize(
        'line',
        [
            f'# the usage default ({_id(1208)}).',
            f'# {_id(6)}: same fix as the sync version',
            '# the label check (Wave' + ' 9 S7)',
            '# QA' + ' S47 — an invited user keeps their role',
            '# Opcja' + ' K: the conditional bridge',
            '# See plans/' + 'ROLLOUT_PLAN.md',
        ],
    )
    def test_an_identifier_is_reported(self, tmp_path: Path, line: str) -> None:
        root = _write(tmp_path, 'thing.py', f'{line}\nx = 1\n')
        assert scan([root]), f'not caught: {line}'

    def test_a_module_test_file_is_read_too(self, tmp_path: Path) -> None:
        """A test docstring is read by the same outsider as production code."""
        root = _write(tmp_path, 'tests/test_thing.py', f'# ({_id(1234)})\n')
        assert scan([root]), 'a test file was skipped'

    def test_a_frontend_test_file_is_read_too(self, tmp_path: Path) -> None:
        root = _write(tmp_path, 'thing.test.tsx', f'// who may switch ({_id(9)})\n')
        assert scan([root]), 'a .test.tsx file was skipped'

    def test_a_hit_carries_its_own_line_number(self, tmp_path: Path) -> None:
        """The scan looks for places in the whole text first; the row it
        reports is still the line the identifier is on, whichever line break
        the file uses."""
        body = 'a = 1\r\nb = 2\n\n' + f'# ({_id(77)})\n' + 'c = 3\n'
        root = _write(tmp_path, 'thing.py', body)
        assert [(hit[1], hit[2], hit[3]) for hit in scan([root])] == [
            (4, _id(77), f'# ({_id(77)})')
        ]

    def test_the_coverage_report_is_not_read(self, tmp_path: Path) -> None:
        """A coverage run leaves a gitignored report of ten megabytes in one
        line; no hand wrote it, and the plan pattern needed seconds for it."""
        root = _write(tmp_path, 'coverage.json', f'{{"note": "{_id(88)}"}}\n')
        assert not scan([root])

    def test_a_markdown_file_is_read(self, tmp_path: Path) -> None:
        """A task id in a README line reaches the same outsider as one in
        a comment — AGENTS.md carried exactly one for months because the
        gate could not see a .md file."""
        root = _write(
            tmp_path, 'README.md', f'A tracked cleanup owns the move ({_id(2305)}).\n'
        )
        assert scan([root]), 'a Markdown file was skipped'

    def test_a_plain_text_file_is_read(self, tmp_path: Path) -> None:
        """And the plan path in any case — a .txt header carried
        a lowercase plan path for months because the pattern
        demanded capitals in the file name."""
        root = _write(
            tmp_path,
            'baseline.txt',
            '# Tracked in plans/' + 'a-plan.md.\n',
        )
        assert scan([root]), 'a .txt file was skipped'

    def test_a_makefile_is_read_too(self, tmp_path: Path) -> None:
        """The Makefile is suffixless prose and it carried two ids while
        the suffix filter skipped it. This is the positive control: a new
        id in a Makefile is a red scan, not a silent one."""
        root = _write(tmp_path, 'Makefile', f'# the cleanup ({_id(2305)})\n')
        hits = scan([root])
        assert [ident for _, _, ident, _ in hits] == [_id(2305)]

    def test_a_github_workflow_is_read_too(self, tmp_path: Path) -> None:
        """A task id in ``.github/workflows/ci.yml`` reaches the same
        outsider as one in a .py comment: the repository is public, the
        comment is not. The .yml suffix joined on this measured finding."""
        root = _write(
            tmp_path,
            '.github/workflows/ci.yml',
            f'# the changed lines gate ({_id(2305)})\n',
        )
        assert scan([root]), 'a .github workflow was skipped'

    def test_a_private_lessons_citation_is_reported(self, tmp_path: Path) -> None:
        root = _write(
            tmp_path,
            'doctor.py',
            '"""The failure this exists for (``tasks/lessons' + '.md``)."""\n',
        )
        assert scan([root]), 'a citation of the private lessons file was skipped'

    def test_the_gate_reads_a_file_passed_as_the_root(self, tmp_path: Path) -> None:
        """The public documents are passed as files, not directories."""
        doc = _write(tmp_path, 'AGENTS.md', f'the cleanup ({_id(2305)})\n')
        hits = scan([doc])
        assert [ident for _, _, ident, _ in hits] == [_id(2305)]

    def test_the_gates_own_baseline_file_is_not_scanned(self, tmp_path: Path) -> None:
        """The suppression list is a .txt file whose lines ARE identifiers
        by design — it sits under a scanned root and must not report
        itself."""
        root = _write(
            tmp_path,
            'core/internal_id_baseline.txt',
            f'thing.py:{_id(1208)}:# the default ({_id(1208)}). | owner=x | expires=2999-01-01 | r\n',
        )
        _write(tmp_path, 'core/thing.py', 'x = 1\n')
        assert not scan([root]), 'the gate reported its own baseline'

    def test_a_missing_root_is_an_error_not_an_empty_scan(self, tmp_path: Path) -> None:
        """A checkout the gate cannot see must fail the run, not report a
        smaller tree clean — the docs-paths gate stayed green that way for
        a long stretch."""
        with pytest.raises(FileNotFoundError):
            scan([tmp_path / 'does-not-exist.md'])

    def test_a_gitignored_docs_directory_is_not_scanned(self, tmp_path: Path) -> None:
        """docs/business, docs/plans and their siblings never reach
        publication; they are absent from a fresh clone but present in a
        working tree, and the gate must not change colour with them."""
        root = _write(
            tmp_path, 'docs/plans' + '/private.md', f'the plan ({_id(9999)})\n'
        )
        _write(tmp_path, 'docs/guide.md', 'public prose\n')
        assert not scan([root]), 'a gitignored docs directory was scanned'

    @pytest.mark.parametrize(
        'name, body',
        [
            ('pyproject.toml', '# rollout step (see tasks/lessons' + '.md)\n'),
            ('data.json', f'{{"note": "closes {_id(1208)}"}}\n'),
            ('check.mjs', f'// the budget ({_id(1979)})\n'),
            ('run.sh', f'# the backup ({_id(54)})\n'),
            ('Dockerfile.dev', f'# fixed one ({_id(13)})\n'),
            ('.gitignore', 'plans/\n'),
        ],
    )
    def test_data_scripts_and_dotfiles_are_read_too(
        self, tmp_path: Path, name: str, body: str
    ) -> None:
        """The first audit's ids lived in a TOML, a JSON, build scripts and an
        ignore file, none of which a prose-only suffix list opened."""
        root = _write(tmp_path, name, body)
        assert scan([root]), f'{name} was skipped'

    @pytest.mark.parametrize(
        'line',
        [
            f'# {_id(4)}: where the original happened',
            f'# {_id(2)}: explicit whitelist',
            f'# {_id(3)} measured this link',
            '// FALA' + ' 8.4: the aggregate',
            '# Wave' + ' 7.6 of the rollout',
            '# the criterion (AC' + '#3)',
            '# App Store - Phase' + ' 2.1',
            '# the field library, Phase' + ' 2 F4',
            '# Phase' + ' 1 step 9',
            '# see docs/' + 'superpowers/specs/design.md',
            '# see docs/' + 'reviews/a-review.md',
            '# see tasks/' + 'a-plan.md',
            '# Faza' + ' Q of the rollout',
            'plans' + '/',
            '# what lessons' + '.md #36 asks for',
        ],
    )
    def test_the_vocabulary_the_first_gate_missed_is_reported(
        self, tmp_path: Path, line: str
    ) -> None:
        root = _write(tmp_path, 'thing.py', f'{line}\nx = 1\n')
        assert scan([root]), f'not caught: {line}'

    @pytest.mark.parametrize(
        'name',
        [
            'Page.eq9.test.tsx',
            'DynamicFieldsCard.phase2.test.tsx',
            'clusterEErrorStates.test.tsx',
            'test_phase_c.py',
            'test_production_phase_a.py',
        ],
    )
    def test_a_plan_step_in_a_file_name_is_reported(
        self, tmp_path: Path, name: str
    ) -> None:
        """A name is read by the outsider like a line is."""
        root = _write(tmp_path, name, 'x = 1\n')
        hits = scan([root])
        assert hits and hits[0][1] == 0, f'file name not caught: {name}'

    def test_the_public_tree_roots_cover_tests_migrations_and_root_files(
        self, tmp_path: Path
    ) -> None:
        for name in ('backend/tests', 'backend/migrations', 'frontend/scripts', 'docs'):
            (tmp_path / name).mkdir(parents=True)
        (tmp_path / 'README.md').write_text('x\n')
        (tmp_path / 'CLAUDE.md').write_text('x\n')
        roots = {
            path.relative_to(tmp_path).as_posix()
            for path in public_tree_roots(tmp_path)
        }
        assert {'backend', 'frontend', 'docs', 'README.md'} <= roots
        assert 'CLAUDE.md' not in roots, 'a local agent entry point was scanned'

    def test_a_checkout_without_the_frontend_is_an_error(self, tmp_path: Path) -> None:
        """The container once held no ``frontend/`` and the scan of it came back
        empty and green; a missing required root must stop the run."""
        for name in ('backend', 'docs'):
            (tmp_path / name).mkdir()
        with pytest.raises(FileNotFoundError, match='frontend'):
            public_tree_roots(tmp_path)

    @pytest.mark.parametrize(
        'relative', ['backend/app/x.py', 'frontend/src/x.ts', 'backend/scripts/x.py']
    )
    def test_a_planted_id_is_found_in_each_root(
        self, tmp_path: Path, relative: str
    ) -> None:
        """Measured, not assumed: one planted identifier per root, each found
        through the roots ``make lint`` passes."""
        for name in ('backend', 'frontend', 'docs'):
            (tmp_path / name).mkdir()
        _write(tmp_path, relative, f'# the cleanup ({_id(2305)})\n')
        found = scan(public_tree_roots(tmp_path))
        assert [ident for _, _, ident, _ in found] == [_id(2305)]


class TestWhatItLeavesAlone:
    @pytest.mark.parametrize(
        'line',
        [
            '# The Golden Path, AGENTS.md §3.',
            '# One control scale (UI_GUIDELINES §2.10).',
            '# Disposal is not consumption (ADR-004).',
            '# emails are case-insensitive (RFC 5321)',
            '# Phase 1 claims the batch; phase 2 makes the call.',
            "# 'PR/2026/0001' — the year comes from created_at",
            "short_code = 'INV-0001'  # a label code, not a ticket",
            "barcode = 'EQ-90210'",
            '# Phase 2 of the import writes the rows.',
            '# the generated asset code EQ-20260918-A0A94455',
        ],
    )
    def test_a_citation_is_not_an_identifier(self, tmp_path: Path, line: str) -> None:
        root = _write(tmp_path, 'thing.py', f'{line}\nx = 1\n')
        assert not scan([root]), f'false positive: {line}'


class TestTheBaseline:
    def _entry(self, tmp_path: Path, body: str) -> Path:
        path = tmp_path / 'internal_id_baseline.txt'
        path.write_text(body, encoding='utf-8')
        return path

    def test_an_owned_entry_with_a_date_suppresses_its_line(
        self, tmp_path: Path
    ) -> None:
        root = _write(tmp_path, 'thing.py', f'# the default ({_id(1208)}).\n')
        key = _key_of(root)
        baseline = self._entry(
            tmp_path, f'{key} | owner=core | expires=2999-01-01 | pre-dates the gate\n'
        )

        keys, errors = load_baseline(baseline)

        assert not errors
        assert not new_findings([root], keys)

    def test_an_entry_without_an_owner_is_reported(self, tmp_path: Path) -> None:
        root = _write(tmp_path, 'thing.py', f'# the default ({_id(1208)}).\n')
        key = _key_of(root)
        baseline = self._entry(
            tmp_path, f'{key} | | expires=2999-01-01 | pre-dates the gate\n'
        )

        keys, errors = load_baseline(baseline)

        assert errors and 'has no owner' in errors[0]
        assert new_findings([root], keys), 'an unowned entry still suppressed the line'

    def test_an_expired_entry_is_reported_with_its_owner(self, tmp_path: Path) -> None:
        root = _write(tmp_path, 'thing.py', f'# the default ({_id(1208)}).\n')
        key = _key_of(root)
        baseline = self._entry(
            tmp_path, f'{key} | owner=core | expires=2020-01-01 | pre-dates the gate\n'
        )

        keys, errors = load_baseline(baseline)

        assert errors and 'expired on 2020-01-01' in errors[0] and 'core' in errors[0]
        assert new_findings([root], keys), 'an expired entry still suppressed the line'


class TestTheDriftClass:
    """A baseline keyed by line number is a treadmill: any edit above a
    baselined identifier shifts its address, the entry points at the wrong
    line, and the gate resurrects the finding it already owns. Measured
    2026-09-17: one dev commit moved an entry's identifier from :243 to
    :284 and make lint went red again — the third time for one cause."""

    def _baseline_file(self, tmp_path: Path, key: str) -> Path:
        path = tmp_path / 'internal_id_baseline.txt'
        path.write_text(
            f'{key} | owner=core | expires=2999-01-01 | pre-dates the gate\n',
            encoding='utf-8',
        )
        return path

    def test_a_line_that_moved_stays_suppressed(self, tmp_path: Path) -> None:
        root = _write(tmp_path, 'thing.py', f'# the default ({_id(1208)}).\n')
        keys, errors = load_baseline(self._baseline_file(tmp_path, _key_of(root)))
        assert not errors

        shifted = _write(
            tmp_path,
            'thing.py',
            '# forty-one lines of new code above\n' * 41
            + f'# the default ({_id(1208)}).\n',
        )

        assert not new_findings([shifted], keys), (
            'an edit above a baselined identifier resurrected it as a new finding'
        )

    def test_an_entry_whose_line_is_gone_is_an_error(self, tmp_path: Path) -> None:
        root = _write(tmp_path, 'thing.py', f'# the default ({_id(1208)}).\n')
        keys, _ = load_baseline(self._baseline_file(tmp_path, _key_of(root)))

        gone = _write(tmp_path, 'thing.py', '# the default, said in words.\n')

        stale = stale_entries([gone], keys)
        assert stale, (
            'an entry over a line that no longer carries the identifier went unnoticed'
        )
        assert all(_id(1208) in entry for entry in stale)

    def test_an_identifier_added_below_a_baselined_line_is_still_reported(
        self, tmp_path: Path
    ) -> None:
        root = _write(tmp_path, 'thing.py', f'# the default ({_id(1208)}).\n')
        keys, _ = load_baseline(self._baseline_file(tmp_path, _key_of(root)))

        grown = _write(
            tmp_path,
            'thing.py',
            f'# the default ({_id(1208)}).\n# a new one ({_id(9999)}).\n',
        )

        found = new_findings([grown], keys)
        assert [ident for _, _, ident, _ in found] == [_id(9999)]


class TestThePrefixList:
    def test_a_prefix_from_the_private_file_is_caught(self, tmp_path: Path) -> None:
        private = tmp_path / 'prefixes.local'
        private.write_text('# comment\nZZQ\n\nWWK  # trailing\n', encoding='utf-8')
        pattern = ticket_pattern(load_prefixes(private))
        assert pattern.search('# see ZZQ-12 for why')
        assert pattern.search('# see WWK-7 for why')
        assert pattern.search(f'# see {_id(5)} for why')
        assert not pattern.search('# see QQX-12 for why')

    def test_a_prefix_can_carry_a_shorter_number_limit(self, tmp_path: Path) -> None:
        private = tmp_path / 'prefixes.local'
        private.write_text('ZZQ 3\n', encoding='utf-8')
        pattern = ticket_pattern(load_prefixes(private))
        assert pattern.search('# see ZZQ-123 for why')
        assert not pattern.search('# the code ZZQ-1234 is data')
        assert pattern.search(f'# see {_id(1234)} for why')

    def test_a_checkout_without_the_private_file_still_catches_the_public_prefix(
        self, tmp_path: Path
    ) -> None:
        prefixes = load_prefixes(tmp_path / 'absent.local')
        assert list(prefixes) == ['INV']
        assert ticket_pattern(prefixes).search(f'# see {_id(12)} for why')

    def test_the_file_named_by_the_environment_is_read_first(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        private = tmp_path / 'ids.txt'
        private.write_text('ZZQ\n', encoding='utf-8')
        monkeypatch.setenv('INVENTARI_ID_PREFIXES', str(private))
        assert 'ZZQ' in load_prefixes()

    def test_the_public_file_names_no_private_prefix(self) -> None:
        source = (
            Path(__file__).resolve().parents[2] / 'scripts' / 'check_internal_ids.py'
        ).read_text(encoding='utf-8')
        for word in load_prefixes():
            if word != 'INV':
                assert not re.search(rf'\b{word}\b', source), word


class TestACheckoutWithAPrivateListScansWithIt:
    """The suite runs in the backend container, so the list has to reach it.

    A maintainer's checkout may hold the private list as the gitignored
    ``internal_id_prefixes.local`` link. Inside the container such a link can
    lead nowhere, and the checker would read no list: a scan that looks green
    would stop looking for every prefix but the public one. The container is
    given the list through ``INVENTARI_ID_PREFIXES``; this is what notices one
    that was not. A public checkout has no such file and keeps the documented
    fallback, which the clean-tree tests cover.
    """

    @staticmethod
    def _skip_unless_a_private_list_is_linked() -> None:
        local = _REPO_ROOT / 'backend' / 'scripts' / 'internal_id_prefixes.local'
        if not local.is_symlink():
            pytest.skip('this checkout does not link a private prefix list')

    def test_the_default_configuration_reads_more_than_the_public_prefix(
        self,
    ) -> None:
        self._skip_unless_a_private_list_is_linked()
        assert list(load_prefixes()) != ['INV'], (
            'this checkout links a private prefix list but the id gate read none: '
            'hand the list to the backend container through INVENTARI_ID_PREFIXES '
            'and recreate it (docker compose up -d)'
        )

    def test_a_scan_started_the_default_way_fails_on_a_configured_prefix(
        self, tmp_path: Path
    ) -> None:
        self._skip_unless_a_private_list_is_linked()
        configured = [word for word in load_prefixes() if word != 'INV']
        assert configured, 'no private prefix is configured in this checkout'
        planted = tmp_path / 'planted.py'
        planted.write_text(f'# see {configured[0]}-12 for why\n', encoding='utf-8')

        result = subprocess.run(
            [
                sys.executable,
                str(
                    Path(__file__).resolve().parents[2]
                    / 'scripts'
                    / 'check_internal_ids.py'
                ),
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 1, result.stdout + result.stderr


class TestTheRepositoryItself:
    def test_every_baselined_entry_is_owned_and_dated(self) -> None:
        _, errors = load_baseline()
        assert not errors, '\n'.join(errors)

    def test_the_scan_reaches_the_frontend_and_the_scripts(self) -> None:
        """Where the checkout is missing a root the scan raises; where it is
        present it must be among the roots actually walked."""
        names = {path.relative_to(_REPO_ROOT).parts[0] for path in _REPO_SCAN_ROOTS}
        assert {'backend', 'frontend', 'docs'} <= names
        assert (_REPO_ROOT / 'frontend' / 'src').is_dir()
        assert (_REPO_ROOT / 'backend' / 'scripts').is_dir()

    def test_no_baseline_entry_is_dead(self) -> None:
        keys, _ = load_baseline()
        stale = stale_entries(_REPO_SCAN_ROOTS, keys)
        assert not stale, '\n'.join(stale)

    def test_no_unlisted_identifier_is_left(self) -> None:
        keys, _ = load_baseline()
        found = new_findings(_REPO_SCAN_ROOTS, keys)
        assert not found, '\n'.join(f'{p}:{n}: {line}' for p, n, _, line in found)
