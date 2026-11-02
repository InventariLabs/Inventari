"""Fixtures several unit-test files share."""

from __future__ import annotations

import fcntl
import json
from dataclasses import asdict

import pytest

from ._scaffolded_lint_copy import LintRun, lint_a_scaffolded_copy


@pytest.fixture(scope='session')
def lint_of_a_scaffolded_copy(tmp_path_factory: pytest.TempPathFactory) -> LintRun:
    """The lint's verdict on the copy ``_scaffolded_lint_copy`` builds.

    The lint runs once per test run, not once per worker: the first worker to
    ask runs it and writes the answer where the others read it. A worker's
    base temporary directory is a child of the one the whole run shares.
    """
    shared = tmp_path_factory.getbasetemp()
    if shared.name.startswith('popen-gw'):
        shared = shared.parent
    answer = shared / 'lint_of_a_scaffolded_copy.json'
    with (shared / 'lint_of_a_scaffolded_copy.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not answer.exists():
            run = lint_a_scaffolded_copy(tmp_path_factory)
            answer.write_text(
                json.dumps(
                    {**asdict(run), 'removed_modules': sorted(run.removed_modules)}
                ),
                encoding='utf-8',
            )
    saved = json.loads(answer.read_text(encoding='utf-8'))
    return LintRun(
        saved['returncode'], saved['output'], frozenset(saved['removed_modules'])
    )
