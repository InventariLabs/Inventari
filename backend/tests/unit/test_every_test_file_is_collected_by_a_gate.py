"""A test file outside the selection runs in no gate, however green it is.

``pytest.ini``'s ``testpaths`` is the one selection the full-suite gates use:
the Makefile and CI run pytest without paths of their own. When a tests
directory appears beside that selection instead of inside it, the file is
collected by no run anybody watches — ``app/core/tests`` did exactly that,
23 green tests invisible to ``make test-coverage`` until the tree was counted.

This test counts the tree the same way: every ``test_*.py`` under the backend
root has to sit inside one of the configured testpaths, and the ones that do
not are named in the failure so the reader who moves a directory learns it
here rather than from a coverage report that never saw the file.
"""

from __future__ import annotations

import configparser
import glob
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

#: The tree the gates run in — ``backend/`` on the host, ``/app`` in the
#: container. Both are two parents above this file.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _testpaths() -> list[str]:
    config = configparser.ConfigParser(interpolation=None)
    config.read(_BACKEND_ROOT / 'pytest.ini', encoding='utf-8')
    return config['pytest']['testpaths'].split()


def _selected() -> list[Path]:
    """Expand the configured testpaths, globs included, the way pytest does."""
    return [
        Path(match)
        for pattern in _testpaths()
        for match in glob.glob(str(_BACKEND_ROOT / pattern))
    ]


def _test_files() -> list[Path]:
    return sorted(
        path
        for path in _BACKEND_ROOT.rglob('test_*.py')
        if not any(
            # ``mutants/`` is mutmut's working copy of this tree (`make
            # mutate-stock`): every test in it is a copy of one inside the
            # selected paths, and the copy is gitignored. Counting it would
            # fail this guard for having run the tool the report describes.
            part.startswith('.') or part in ('node_modules', 'mutants')
            for part in path.relative_to(_BACKEND_ROOT).parts
        )
    )


def test_every_test_file_sits_inside_the_testpaths() -> None:
    selected = _selected()

    orphans = [
        path.relative_to(_BACKEND_ROOT).as_posix()
        for path in _test_files()
        if not any(path == root or path.is_relative_to(root) for root in selected)
    ]

    assert not orphans, (
        'these test files no gate collects — no testpath reaches them: '
        + ', '.join(orphans)
    )
