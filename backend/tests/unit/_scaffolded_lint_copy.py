"""A copy of ``app/`` with a scaffolded module, linted once for the tests that ask about it."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.cli import module_generator

_APP = Path(module_generator.__file__).resolve().parents[1]

#: The module the scaffold generates into the copy.
SCAFFOLDED_MODULE = 'warranty_tracker'

#: A baseline entry for a route that does not exist, planted in the copy.
STALE_ENTRY = 'app/api/a_route_that_was_deleted.py::gone'

# Import the copy rather than the installed tree — the guard is what keeps a
# green run from meaning "linted the real tree, where the module is not".
#
# Everything the lint prints is kept, but only a stale baseline entry may reach
# the exit code. The copy trips other checks of its own (no ``tests/`` beside
# it, a ratchet planted entries move), so an exit status of 1 would be true
# with or without the stale check; with this filter it is true only if a stale
# entry blocks the run.
_RUN_THE_COPYS_LINT = """
import runpy, sys
from app.core.architecture_lint import _main
from app.core.architecture_lint._constants import APP_ROOT
assert str(APP_ROOT).startswith(sys.argv[1]), APP_ROOT

def only_stale(entries):
    return [entry for entry in entries if 'stale baseline entry' in entry]

emit, emit_baselined = _main._emit, _main._emit_baselined
_main._emit = lambda entries: only_stale(emit(entries))

def emit_baselined_stale(*args, **kwargs):
    errors, notices = emit_baselined(*args, **kwargs)
    return only_stale(errors), notices

_main._emit_baselined = emit_baselined_stale
sys.argv = ['architecture_lint', '--quiet']
runpy.run_module('app.core.architecture_lint', run_name='__main__')
"""


@dataclass(frozen=True)
class LintRun:
    """What the architecture lint said about the scaffolded copy."""

    #: 1 when a stale baseline entry blocked the run, whatever else it found.
    returncode: int
    output: str
    #: The shipped modules left out of the copy: the lint reads every module
    #: it finds, and the reference module is all the scaffold needs.
    removed_modules: frozenset[str]

    @property
    def errors(self) -> list[str]:
        return [line for line in self.output.splitlines() if line.startswith('::error')]


def lint_a_scaffolded_copy(tmp_path_factory: pytest.TempPathFactory) -> LintRun:
    """Lint a copy of ``app/`` that holds a freshly generated module.

    The lint reads the tree it lives in, so the copy gets a module of its own
    and a lint run in a process of its own. One run answers every test that
    asks about it: it takes seconds, and a run per test took most of a minute.
    The copy keeps only the reference module of the shipped ones — each
    further module is a few hundred files read by every check — which leaves
    the baseline entries of the removed modules stale, and that is for the
    tests to account for. The copy also carries one stale baseline entry.
    """
    backend = tmp_path_factory.mktemp('architecture_lint_copy') / 'backend'
    modules = _APP / 'modules'
    removed = frozenset(
        path.name
        for path in modules.iterdir()
        if path.is_dir()
        and path.name not in {module_generator.REFERENCE_MODULE, '__pycache__'}
    )

    def ignore(directory: str, names: list[str]) -> set[str]:
        skipped = set(shutil.ignore_patterns('__pycache__', '*.pyc')(directory, names))
        if Path(directory) == modules:
            skipped |= removed
        return skipped

    shutil.copytree(_APP, backend / 'app', ignore=ignore)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module_generator, 'MODULES_DIR', backend / 'app' / 'modules')
        module_generator.create_module(SCAFFOLDED_MODULE)
    assert (backend / 'app' / 'modules' / SCAFFOLDED_MODULE / 'router.py').exists()
    with (backend / 'app' / 'core' / 'request_scope_baseline.txt').open(
        'a', encoding='utf-8'
    ) as handle:
        handle.write(f'{STALE_ENTRY}\n')

    result = subprocess.run(
        [sys.executable, '-c', _RUN_THE_COPYS_LINT, str(backend)],
        cwd=backend,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert 'Traceback' not in result.stderr, result.stderr
    return LintRun(result.returncode, result.stdout + result.stderr, removed)
