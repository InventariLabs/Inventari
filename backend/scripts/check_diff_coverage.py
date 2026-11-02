#!/usr/bin/env python3
"""Gate: lines this branch changed must be covered by the test suite.

The line is drawn at changed lines, not at the global percentage: a global floor
lets whole modules land untested because an old, heavily covered half of the
tree pays for them. CI enforced this with

    uv run diff-cover coverage.xml --compare-branch=origin/dev --fail-under=80

and nothing enforced it locally. ``diff-cover`` is still a dev dependency
(``backend/pyproject.toml``), but it cannot run where the coverage report is
produced: the backend container mounts ``./backend`` at ``/app`` and holds no
``.git`` — and in a checkout made by ``git worktree``, ``.git`` is a file
naming an absolute *host* path — while
``diff_cover.git_path.GitPathTool.set_cwd`` shells out to
``git rev-parse --show-toplevel`` unconditionally. It dies before it
reads the report, even when handed a ready-made diff with ``--diff-file``. The
host has git but no usable uv or diff-cover. So the work is split: the container
writes the report, this script reads it where git is, and both halves see the
same tree through the ``./backend:/app`` mount.

The report is the JSON one (``--cov-report=json``) rather than the XML one CI
used, for a reason worth naming: it is read with the standard library alone,
needs no XML parser, and its file keys are already relative to the tree the
suite ran in — where the XML report's paths are stated against a ``<source>``
directory that then has to be mapped back.

WHY NOT MOUNT THE GIT DIRECTORY INSTEAD. That would mean giving the container a
repository whose paths answer ``git diff`` the way the report's keys do: either
mounting a worktree pointer file that names a host path, or hard-coding a
sibling-directory layout into ``docker-compose.yml``.

WHAT IS COMPARED. Deliberately faithful to ``diff-cover``:

- Three-dot diff — ``git merge-base <base> HEAD``, then ``git diff`` from there
  — matching diff-cover's default ``--diff-range-notation=...`` and CI's
  ``--compare-branch``. The far end is the working tree rather than HEAD, so an
  edit made since the last commit is judged against a report that describes the
  same bytes; on a clean checkout the two are identical.
- Only *added* lines count. Removed lines are not the author's debt.
- An added line whose code — the line without its trailing comment — equals a
  line its hunk removed is a comment edit, not new code, and carries no
  verdict, the way a comment line carries none. Without this, rewording the
  ``noqa`` reason on an ``except`` line no test reaches reads as an uncovered
  change. Each removed line excuses one added line, so a statement duplicated
  under a new comment still counts.
- A changed line counts only when the report lists it. A line the report does
  not mention — a comment, a blank line, a branch that never executes — carries
  no verdict either way.
- No measurable changed line is not a failure; it is a run with nothing to say.

WHERE IT IS STRICTER. A changed Python file under the covered source tree that
the report does not describe at all is an error, not silence. ``--cov=app``
makes coverage.py list every file under ``app/``, imported or not, so a changed
``app/*.py`` missing from the report means the report predates the change — and
reading a stale report would let exactly the new, untested code this gate
exists for pass unseen. A changed Python file newer than the report itself is
refused for the same reason. A missing report is likewise an error, never a
pass. Non-Python files under ``app/`` (baseline lists, snapshots) are exempt:
coverage never describes them, so demanding a verdict for one would make every
change to a data file look like a stale report.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tokenize
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _ROOT / 'backend'
_BACKEND_PREFIX = 'backend/'

DEFAULT_COMPARE_BRANCH = 'origin/dev'
DEFAULT_FAIL_UNDER = 80.0

# `@@ -old_start,old_count +new_start,new_count @@` — a count is omitted when
# it is 1, so both are optional.
_HUNK_HEADER = re.compile(r'^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')
_DIFF_TARGET = re.compile(r'^\+\+\+ (?:b/)?(.+)$')


class GateError(Exception):
    """The gate could not reach a verdict (as opposed to reaching "red")."""


def git(*args: str) -> str:
    try:
        result = subprocess.run(
            ['git', *args], cwd=_ROOT, capture_output=True, text=True, check=False
        )
    except FileNotFoundError as exc:  # pragma: no cover - no git on PATH
        raise GateError(f'git is not on PATH — run this on the host: {exc}') from exc
    if result.returncode != 0:
        raise GateError(f'git {" ".join(args)} failed:\n{result.stderr.strip()}')
    return result.stdout


def changed_lines(compare_branch: str) -> dict[str, set[int]]:
    """Lines added on this branch, per path relative to ``backend/``.

    The range is the merge base to the *working tree*, not to HEAD: the
    coverage report describes the files on disk, and comparing it against lines
    committed somewhere else would judge a change and a report that describe
    different bytes — an edit made after the last commit would be invisible.
    On a clean checkout this is exactly the commit range CI compared. Untracked
    files are not in the diff; `git add` them first.

    Only the backend tree is returned: the coverage report describes that tree,
    and a diff path it cannot name is not its business.
    """
    base = git('merge-base', compare_branch, 'HEAD').strip()
    if not base:
        raise GateError(
            f'no merge base between {compare_branch} and HEAD — fetch it first '
            f'(`git fetch origin`) and try again.'
        )
    return added_lines(git('diff', '--no-ext-diff', '--no-color', '-U0', base))


def added_lines(diff: str) -> dict[str, set[int]]:
    """New-file line numbers of the lines a ``-U0`` diff adds, minus comment edits.

    A hunk is read by the counts its header declares, so a removed line that
    starts with ``--`` or an added one that starts with ``++`` is never taken
    for a file header.
    """
    changed: dict[str, set[int]] = {}
    current: set[int] | None = None
    removed: Counter[str] = Counter()
    added: list[tuple[int, str]] = []
    old_left = new_left = cursor = 0

    def close_hunk() -> None:
        for number, text in added:
            code = _code(text)
            if removed[code]:
                removed[code] -= 1  # the same statement, only its comment changed
            elif current is not None:
                current.add(number)
        removed.clear()
        added.clear()

    for line in diff.splitlines():
        if old_left or new_left:
            if line.startswith('-') and old_left:
                old_left -= 1
                removed[_code(line[1:])] += 1
            elif line.startswith('+') and new_left:
                new_left -= 1
                added.append((cursor, line[1:]))
                cursor += 1
            # anything else here is `\ No newline at end of file`
            continue

        close_hunk()
        header = _HUNK_HEADER.match(line)
        if header:
            old_count, new_start, new_count = header.groups()
            old_left = 1 if old_count is None else int(old_count)
            new_left = 1 if new_count is None else int(new_count)
            cursor = int(new_start)
            continue

        target = _DIFF_TARGET.match(line)
        if target:
            path = target.group(1).strip()
            # `/dev/null` is a deletion: nothing was added to judge.
            if path == '/dev/null' or not path.startswith(_BACKEND_PREFIX):
                current = None
            else:
                current = changed.setdefault(path[len(_BACKEND_PREFIX) :], set())

    close_hunk()
    return changed


def _code(line: str) -> str:
    """The line without its trailing comment, as Python's tokenizer sees it.

    A ``#`` inside a string literal is code. A line the tokenizer cannot read
    on its own — one that opens a bracket or a multi-line string — is returned
    whole, so it is excused only by an identical removed line: such a comment
    edit is still judged, as it was before comments were set aside.
    """
    try:
        for token in tokenize.generate_tokens(iter([line]).__next__):
            if token.type == tokenize.COMMENT:
                return line[: token.start[1]].rstrip()
    except (tokenize.TokenError, SyntaxError):
        return line
    return line.rstrip()


def read_coverage(path: Path) -> tuple[dict[str, dict[str, set[int]]], tuple[str, ...]]:
    """Return ``(measured lines under backend/, described top-level roots)``.

    ``measured`` is ``{path relative to backend/: {'covered': set, 'missed':
    set}}``, read from the JSON report ``--cov-report=json`` writes. Its file
    keys are already relative to the directory the suite ran in — the backend
    tree — so they line up with the diff paths directly.

    The roots are the top-level directories the report describes (``app/`` for
    ``--cov=app``). A changed file beneath one of them has to appear in the
    report, which is how a report written before the change is caught.
    """
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f'{path} is not readable as coverage JSON: {exc}') from exc

    measured: dict[str, dict[str, set[int]]] = {}
    for filename, entry in (data.get('files') or {}).items():
        if not isinstance(entry, dict):
            continue
        measured[_normalise(filename)] = {
            'covered': {int(n) for n in entry.get('executed_lines') or ()},
            'missed': {int(n) for n in entry.get('missing_lines') or ()},
        }

    roots = tuple(
        sorted({f'{key.split("/", 1)[0]}/' for key in measured if '/' in key})
    )
    return measured, roots


def _normalise(filename: str) -> str:
    filename = filename.replace('\\', '/')
    while filename.startswith('./'):
        filename = filename[2:]
    if filename.startswith(_BACKEND_PREFIX):
        filename = filename[len(_BACKEND_PREFIX) :]
    return filename


def _coverage_measures(path: str) -> bool:
    """Whether the report could have described this file at all.

    Coverage measures Python. ``app/`` also holds data — ``baseline_sizes.txt``,
    ``vulture-baseline.txt``, snapshot JSON — which never appears in a report,
    so a change to one of those must not be read as a missing report.
    """
    return path.endswith('.py')


def judge(
    changed: dict[str, set[int]],
    measured: dict[str, dict[str, set[int]]],
    roots: tuple[str, ...],
) -> tuple[list[str], int, int]:
    """Return ``(uncovered, covered_count, missed_count)``.

    Raises when a changed *Python* file under a described top-level root is
    absent from the report: the report cannot judge a change it does not
    describe.
    """
    uncovered: list[str] = []
    covered = missed = 0

    for path in sorted(changed):
        file_lines = measured.get(path)
        if (
            file_lines is None
            and roots
            and path.startswith(roots)
            and _coverage_measures(path)
        ):
            raise GateError(
                f'the coverage report does not describe {_BACKEND_PREFIX}{path}, '
                f'which this branch changed. The report predates the change — '
                f're-run the suite with coverage and read it again.'
            )
        if not file_lines:
            continue
        for number in sorted(changed[path]):
            if number in file_lines['covered']:
                covered += 1
            elif number in file_lines['missed']:
                missed += 1
                uncovered.append(f'{path}:{number}')
            # else: not an executable line — no verdict either way
    return uncovered, covered, missed


def check_freshness(
    changed: dict[str, set[int]], roots: tuple[str, ...], report: Path
) -> None:
    """Refuse to judge a change with a report written before it.

    The report is line-numbered data, so a report from before the edit simply
    does not mention the new lines — and lines it does not mention carry no
    verdict. Reading it anyway would answer green for the one thing this gate
    exists to catch. The report is written after the suite; a changed source
    file newer than it means the order was broken.

    Only files the report has something to say about are checked — Python under
    a described root. Editing a backend script, or a data file beside one, is
    not a reason to re-run the suite.
    """
    if not roots:
        return
    report_time = report.stat().st_mtime
    stale = [
        f'{_BACKEND_PREFIX}{path}'
        for path in sorted(changed)
        if path.startswith(roots)
        and _coverage_measures(path)
        and (_BACKEND_DIR / path).is_file()
        and (_BACKEND_DIR / path).stat().st_mtime > report_time
    ]
    if stale:
        raise GateError(
            f'{report} was written before these changed files: '
            + ', '.join(stale)
            + '. It cannot judge them — run `make test-coverage`, which runs '
            'the suite and this check in that order.'
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        'coverage_json',
        nargs='?',
        default=str(_BACKEND_DIR / 'coverage.json'),
        help='coverage report to read (default: backend/coverage.json)',
    )
    parser.add_argument(
        '--compare-branch',
        default=os.environ.get('DIFF_BASE_REF', DEFAULT_COMPARE_BRANCH),
        help=f'branch to diff against '
        f'(default: $DIFF_BASE_REF or {DEFAULT_COMPARE_BRANCH})',
    )
    parser.add_argument(
        '--fail-under',
        type=float,
        default=DEFAULT_FAIL_UNDER,
        help=f'minimum percentage on changed lines (default: {DEFAULT_FAIL_UNDER:g})',
    )
    args = parser.parse_args(argv)

    report = Path(args.coverage_json)
    try:
        if not report.exists():
            raise GateError(
                f'{report} not found — this gate reads the report a coverage run '
                f'writes. Run `make test-coverage`, which runs the suite and then '
                f'this check, or point this script at another report.'
            )
        changed = changed_lines(args.compare_branch)
        measured, roots = read_coverage(report)
        check_freshness(changed, roots, report)
        uncovered, covered, missed = judge(changed, measured, roots)
    except GateError as exc:
        print(f'check_diff_coverage: {exc}', file=sys.stderr)
        return 2

    total = covered + missed
    if total == 0:
        print(
            f'check_diff_coverage: no changed line carries coverage information '
            f'(against {args.compare_branch}) — nothing to measure.'
        )
        return 0

    percent = covered / total * 100
    verdict = (
        f'{percent:.1f}% of changed lines covered ({covered}/{total}), '
        f'threshold {args.fail_under:g}%'
    )

    if percent >= args.fail_under:
        print(f'check_diff_coverage: {verdict} — ok.')
        return 0

    print(f'check_diff_coverage: {verdict} — FAILED.', file=sys.stderr)
    print('Uncovered changed lines:', file=sys.stderr)
    for item in uncovered:
        print(f'  {item}', file=sys.stderr)
    print(
        'Cover them with a test, or take them out of the change. The global '
        'floor does not answer for this: it is the changed lines the gate holds.',
        file=sys.stderr,
    )
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
