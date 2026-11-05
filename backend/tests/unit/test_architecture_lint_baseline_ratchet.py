"""The suppression lists may shrink on their own; growing one takes an act.

Before this, every architecture gate could be silenced by appending a line
to a ``.txt`` file — in the same commit as the code that caused the finding,
with the build still green. These tests pin the three outcomes: unchanged
passes, larger fails, smaller fails too (a ratchet that drifts down without
being written back leaves room for the next addition to spend unseen).
"""

from types import SimpleNamespace

import pytest

from app.core.architecture_lint._quality_checks_baseline_ratchet import (
    _check_baseline_sizes,
    current_sizes,
    read_recorded_sizes,
    write_baseline_sizes,
)

from ._scaffolded_lint_copy import STALE_ENTRY


def _core(tmp_path, **files):
    for name, lines in files.items():
        (tmp_path / f'{name}.txt').write_text(
            '# a comment, and a blank line, neither of which is an entry\n\n'
            + ''.join(f'{line}\n' for line in lines),
            encoding='utf-8',
        )
    return tmp_path


class TestBaselineRatchet:
    def test_recorded_sizes_pass(self, tmp_path):
        core = _core(tmp_path, one_baseline=['a', 'b'])
        sizes = tmp_path / 'baseline_sizes.txt'
        write_baseline_sizes(core, sizes)

        assert _check_baseline_sizes(core, sizes) == []

    def test_appending_an_entry_fails(self, tmp_path):
        core = _core(tmp_path, one_baseline=['a', 'b'])
        sizes = tmp_path / 'baseline_sizes.txt'
        write_baseline_sizes(core, sizes)

        with (core / 'one_baseline.txt').open('a', encoding='utf-8') as handle:
            handle.write('c\n')

        errors = _check_baseline_sizes(core, sizes)

        assert len(errors) == 1
        assert errors[0].startswith('::error')
        assert 'went from 2 to 3 entries' in errors[0]

    def test_paying_a_debt_fails_until_the_ratchet_is_lowered(self, tmp_path):
        core = _core(tmp_path, one_baseline=['a', 'b'])
        sizes = tmp_path / 'baseline_sizes.txt'
        write_baseline_sizes(core, sizes)

        (core / 'one_baseline.txt').write_text('a\n', encoding='utf-8')

        errors = _check_baseline_sizes(core, sizes)
        assert len(errors) == 1
        assert 'ratchet has slack' in errors[0]

        write_baseline_sizes(core, sizes)
        assert _check_baseline_sizes(core, sizes) == []

    def test_a_new_suppression_list_is_not_silently_covered(self, tmp_path):
        core = _core(tmp_path, one_baseline=['a'])
        sizes = tmp_path / 'baseline_sizes.txt'
        write_baseline_sizes(core, sizes)

        (core / 'second_baseline.txt').write_text('x\ny\n', encoding='utf-8')

        errors = _check_baseline_sizes(core, sizes)

        assert len(errors) == 1
        assert 'not in the ratchet' in errors[0]

    def test_deleting_a_list_is_reported(self, tmp_path):
        core = _core(tmp_path, one_baseline=['a'])
        sizes = tmp_path / 'baseline_sizes.txt'
        write_baseline_sizes(core, sizes)

        (core / 'one_baseline.txt').unlink()

        errors = _check_baseline_sizes(core, sizes)

        assert len(errors) == 1
        assert 'no longer exists' in errors[0]

    def test_comments_and_blank_lines_are_not_entries(self, tmp_path):
        core = _core(tmp_path, one_baseline=[])

        assert current_sizes(core) == {'one_baseline.txt': 0}

    def test_deferral_lists_are_covered_too(self, tmp_path):
        core = tmp_path
        (core / 'some_deferrals.txt').write_text('a\nb\n', encoding='utf-8')

        assert current_sizes(core) == {'some_deferrals.txt': 2}

    def test_missing_sizes_file_reads_as_nothing_recorded(self, tmp_path):
        assert read_recorded_sizes(tmp_path / 'absent.txt') == {}


def _whitelist(tmp_path, names, reserved=(), after=()):
    path = tmp_path / 'vulture_whitelist.py'
    body = 'from x import y\n\n' + ''.join(f'{n}  # noqa: B018\n' for n in names)
    body += '# --- begin reserved surface ---\n'
    body += ''.join(
        f'{n}  # noqa: B018  # owner=core expires=2099-01-01 r\n' for n in reserved
    )
    body += '# --- end reserved surface ---\n'
    body += ''.join(f'{n}  # noqa: B018\n' for n in after)
    path.write_text(body, encoding='utf-8')
    return path


class TestWhitelistRatchet:
    def test_entries_after_the_reserved_section_are_counted(self, tmp_path):
        wl = _whitelist(tmp_path, ['a'], reserved=['r1'], after=['b', 'c'])
        assert current_sizes(tmp_path, wl) == {'vulture_whitelist.py': 3}

    @pytest.mark.parametrize(
        'tag', ['# noqa', '# noqa: F821, B018', '# noqa: B018, F821', '']
    )
    def test_the_comment_spelling_does_not_hide_an_entry(self, tmp_path, tag):
        wl = _whitelist(tmp_path, ['a'], after=['b'])
        wl.write_text(wl.read_text() + f'sneaky  {tag}\n', encoding='utf-8')

        assert current_sizes(tmp_path, wl) == {'vulture_whitelist.py': 3}

    def test_an_assignment_that_uses_a_name_is_an_entry_too(self, tmp_path):
        wl = _whitelist(tmp_path, ['a'], after=['b'])
        wl.write_text(wl.read_text() + '_ = sneaky\n', encoding='utf-8')

        assert current_sizes(tmp_path, wl) == {'vulture_whitelist.py': 3}

    @pytest.mark.parametrize(
        'statement',
        [
            'assert sneaky',
            'if sneaky:\n    pass',
            '(other, sneaky)',
            'print(sneaky)',
            'x = [sneaky]',
            'sneaky.attr.deeper',
            'del sneaky',
            '__all__ = ["sneaky"]',
            'from elsewhere import sneaky as sneaky',
            'import sneaky as other_alias',
        ],
    )
    @pytest.mark.parametrize('where', ['before', 'after'])
    def test_no_statement_shape_hides_a_loaded_name(self, tmp_path, statement, where):
        # vulture counts a name loaded anywhere in the file as used, so the
        # ratchet counts loaded names, not the forms people usually write.
        wl = _whitelist(tmp_path, ['a'], reserved=['r1'], after=['b'])
        before = current_sizes(tmp_path, wl)['vulture_whitelist.py']
        text = wl.read_text()
        marker = '# --- begin reserved surface ---\n'
        if where == 'before':
            text = text.replace(marker, f'{statement}\n{marker}')
        else:
            text += f'{statement}\n'
        wl.write_text(text, encoding='utf-8')

        assert current_sizes(tmp_path, wl)['vulture_whitelist.py'] > before

    def test_a_plain_import_is_not_an_entry(self, tmp_path):
        wl = _whitelist(tmp_path, ['a'])
        wl.write_text(wl.read_text() + 'from m import n\nimport q\n', encoding='utf-8')

        assert current_sizes(tmp_path, wl) == {'vulture_whitelist.py': 1}

    def test_extending_an_existing_entry_is_growth(self, tmp_path):
        # A whitelist entry `a` becoming `a.sneaky` adds no line and no statement,
        # but it silences one more name.
        wl = _whitelist(tmp_path, ['a'])
        before = current_sizes(tmp_path, wl)['vulture_whitelist.py']
        wl.write_text(wl.read_text().replace('a  # noqa', 'a.sneaky  # noqa'))

        assert current_sizes(tmp_path, wl)['vulture_whitelist.py'] == before + 1

    def test_the_same_name_twice_is_one_name(self, tmp_path):
        wl = _whitelist(tmp_path, ['a', 'a'])

        assert current_sizes(tmp_path, wl) == {'vulture_whitelist.py': 1}

    def test_a_silenced_name_outside_the_reserved_section_is_refused(self, tmp_path):
        core = tmp_path
        wl = _whitelist(tmp_path, ['a', 'b'])
        sizes = tmp_path / 'baseline_sizes.txt'
        write_baseline_sizes(core, sizes, wl)
        assert _check_baseline_sizes(core, sizes, wl) == []

        wl = _whitelist(tmp_path, ['a', 'b', 'dead_function'])
        errors = _check_baseline_sizes(core, sizes, wl)

        assert len(errors) == 1
        assert 'vulture_whitelist.py' in errors[0]
        assert 'grew' in errors[0]

    def test_the_reserved_section_is_not_counted(self, tmp_path):
        wl = _whitelist(tmp_path, ['a'], reserved=['r1', 'r2'])

        assert current_sizes(tmp_path, wl) == {'vulture_whitelist.py': 1}

    def test_a_paid_off_name_asks_for_the_ratchet_to_be_lowered(self, tmp_path):
        sizes = tmp_path / 'baseline_sizes.txt'
        write_baseline_sizes(tmp_path, sizes, _whitelist(tmp_path, ['a', 'b']))

        errors = _check_baseline_sizes(tmp_path, sizes, _whitelist(tmp_path, ['a']))

        assert len(errors) == 1
        assert 'slack' in errors[0]


class TestRealTreeIsRatcheted:
    def test_every_suppression_list_is_recorded_and_unchanged(self):
        from app.core.architecture_lint._constants import (
            BASELINE_SIZES_FILE,
            CORE_DIR,
            VULTURE_WHITELIST_FILE,
        )

        assert (
            _check_baseline_sizes(CORE_DIR, BASELINE_SIZES_FILE, VULTURE_WHITELIST_FILE)
            == []
        )


class TestStaleCheckRunsForEveryKeyMatchedBaseline:
    def test_each_list_is_checked_against_its_own_collector(self, monkeypatch):
        from app.core.architecture_lint import _main

        def found(**fields):
            return SimpleNamespace(owner_key='', **fields)

        # Every collector answers with a finding of its own, so a list
        # handed another collector's answer shows in what it was checked against.
        collectors = {
            'collect_toctou_risks': {'toctou': ()},
            'collect_bare_emits': {'bare_emit': ()},
            'collect_audit_gaps': {'audit': ()},
            '_collect_raw_http_exceptions': [found(key='raw_http', op='')],
            'collect_unscoped_endpoints': {'request_scope': ()},
            '_collect_transaction_sites': [
                found(key='commit', op='commit'),
                found(key='rollback', op='rollback'),
            ],
            'collect_twin_keys': {'twin'},
            '_collect_public_api_missing_org_keys': {'missing_org'},
        }
        for name, answer in collectors.items():
            monkeypatch.setattr(_main, name, lambda *args, answer=answer: answer)
        seen: dict[str, set[str]] = {}

        def record(baseline, live, name):
            seen[name] = set(live)
            return []

        monkeypatch.setattr(_main, '_check_stale_entries', record)

        assert _main._stale_baseline_errors() == []
        assert seen == {
            'toctou_risk_baseline.txt': {'toctou'},
            'bare_emit_baseline.txt': {'bare_emit'},
            'audit_coverage_baseline.txt': {'audit'},
            'raw_http_exception_baseline.txt': {'raw_http'},
            'request_scope_baseline.txt': {'request_scope'},
            'transaction_ownership_baseline.txt': {'commit'},
            'transaction_rollback_baseline.txt': {'rollback'},
            'sync_async_twin_baseline.txt': {'twin'},
            'public_api_missing_org_baseline.txt': {'missing_org'},
        }

    def test_a_stale_entry_fails_the_lint_run(self, lint_of_a_scaffolded_copy):
        run = lint_of_a_scaffolded_copy

        assert run.returncode == 1
        assert any(
            'request_scope_baseline.txt' in line
            and 'stale baseline entry' in line
            and STALE_ENTRY in line
            for line in run.errors
        )

    def test_a_baseline_entry_with_a_live_finding_is_not_stale(
        self, lint_of_a_scaffolded_copy
    ):
        # The copy left out most modules, so their entries are stale there on
        # purpose. Every other entry names code the copy still has.
        stale = [
            line.split('::', 2)[2].split("' matches", 1)[0].lstrip("'")
            for line in lint_of_a_scaffolded_copy.errors
            if 'stale baseline entry' in line
        ]
        removed = lint_of_a_scaffolded_copy.removed_modules

        unexpected = [
            entry
            for entry in stale
            if entry != STALE_ENTRY
            and not removed.intersection(entry.split('::')[0].split('/')[:-1])
        ]
        assert unexpected == []
