"""The changed-line coverage gate judges code, not the comment beside it.

``scripts/check_diff_coverage.py`` took every added line of the diff that the
coverage report lists as executable. Rewriting only the trailing comment of an
executable line — a ``noqa`` reason on an ``except`` line on an error path no
test runs — shows in the diff as the same statement removed and added, and was
judged as new, uncovered code. A sweep that touched nothing but comments could
not pass the gate.

The container the suite runs in has no git, so ``git`` is replaced with the
diff it would have printed.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

_GATE = Path(__file__).resolve().parents[2] / 'scripts' / 'check_diff_coverage.py'


def _gate() -> Any:
    spec = importlib.util.spec_from_file_location('check_diff_coverage', _GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _diff(*hunks: str) -> str:
    return (
        'diff --git a/backend/app/thing.py b/backend/app/thing.py\n'
        'index 1111111..2222222 100644\n'
        '--- a/backend/app/thing.py\n'
        '+++ b/backend/app/thing.py\n' + ''.join(hunks)
    )


def _run_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, diff: str, missed: list[int]
) -> int:
    gate = _gate()

    def fake_git(*args: str) -> str:
        return 'base\n' if args[0] == 'merge-base' else diff

    monkeypatch.setattr(gate, 'git', fake_git)
    report = tmp_path / 'coverage.json'
    report.write_text(
        json.dumps(
            {
                'files': {
                    'app/thing.py': {
                        'executed_lines': [1, 2, 3],
                        'missing_lines': missed,
                    }
                }
            }
        ),
        encoding='utf-8',
    )
    return int(gate.main([str(report)]))


def test_a_rewritten_trailing_comment_on_an_uncovered_line_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    diff = _diff(
        '@@ -10 +10 @@\n'
        '-    except Exception:  # noqa: BLE001\n'
        '+    except Exception:  # noqa: BLE001 - the caller logs and retries\n'
    )

    assert _run_gate(monkeypatch, tmp_path, diff, missed=[10]) == 0


def test_a_changed_statement_on_an_uncovered_line_still_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    diff = _diff(
        '@@ -10 +10 @@\n'
        '-    except Exception:  # noqa: BLE001\n'
        '+    except (OSError, ValueError):  # the two the parser raises\n'
    )

    assert _run_gate(monkeypatch, tmp_path, diff, missed=[10]) == 1


def test_a_comment_rewrite_excuses_one_line_not_every_copy_of_it() -> None:
    gate = _gate()
    diff = _diff(
        '@@ -10 +10,2 @@\n'
        '-    except Exception:  # noqa: BLE001\n'
        '+    except Exception:  # broad on purpose\n'
        '+    except Exception:  # a second handler is new code\n'
    )

    assert gate.added_lines(diff) == {'app/thing.py': {11}}


def test_the_match_stays_within_its_hunk() -> None:
    gate = _gate()
    diff = _diff(
        '@@ -10 +9,0 @@\n',
        '-    return value  # old\n',
        '@@ -30,0 +30 @@\n',
        '+    return value  # moved here\n',
    )

    assert gate.added_lines(diff) == {'app/thing.py': {30}}


def test_a_hash_inside_a_string_is_code_not_a_comment() -> None:
    gate = _gate()
    diff = _diff(
        '@@ -10 +10 @@\n',
        "-    colour = '#fff'  # white\n",
        "+    colour = '#000'  # white\n",
    )

    assert gate.added_lines(diff) == {'app/thing.py': {10}}


def test_an_added_line_that_looks_like_a_file_header_is_still_an_added_line() -> None:
    gate = _gate()
    diff = _diff('@@ -0,0 +1 @@\n', '+++ value\n')

    assert gate.added_lines(diff) == {'app/thing.py': {1}}


def test_a_file_that_only_lost_lines_needs_no_place_in_the_report() -> None:
    """Dropping a marker comment from a file the suite never imports adds
    nothing to judge; it must not read as a report older than the change."""
    gate = _gate()

    uncovered, covered, missed = gate.judge(
        {'app/modules/x/migrations/env.py': set()}, {}, ('app/',)
    )

    assert (uncovered, covered, missed) == ([], 0, 0)

    with pytest.raises(gate.GateError):
        gate.judge({'app/modules/x/migrations/env.py': {3}}, {}, ('app/',))
