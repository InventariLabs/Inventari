"""A migration replays against an old schema, so it may not run live application code.

A fresh installation applies every revision from the first. A revision that
imports a model, a service or a seed list therefore runs today's code against
yesterday's tables, and the first refactor of that code breaks every install
that has nothing to do with the refactor. The one door in is
``app.core.migration_helpers``, which is frozen (see its docstring): a revision
that needs more than that carries its own copy of the data and logic.

A module's revision reaches the same helpers through ``app.core.module_sdk``,
which re-exports them: that is the only Core path the architecture lint and
the install-time scan allow a module, and the one the module scaffolds write.
From there a revision may import the frozen helpers and nothing else.

``env.py`` is not a revision — it runs once per command and needs the models to
describe the metadata — so only ``versions/`` is checked.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import app.core.migration_helpers as migration_helpers
from app.core import module_sdk
from app.core.module_migrations import MODULES_ROOT

_BACKEND = Path(__file__).resolve().parents[2]
_ALLOWED = 'app.core.migration_helpers'
_SDK = 'app.core.module_sdk'

#: The public surface of ``migration_helpers``. Revisions already committed call
#: these by name, so a name may be added here but never renamed or removed.
_FROZEN_NAMES = {
    'convert_naive_timestamps_to_utc',
    'create_index_if_absent',
    'create_table_if_absent',
    'encrypt_secret',
    'relation_exists',
}


def _revision_files() -> list[Path]:
    core = sorted((_BACKEND / 'migrations' / 'versions').glob('*.py'))
    modules = sorted(MODULES_ROOT.glob('*/migrations/versions/*.py'))
    return [path for path in (*core, *modules) if path.name != '__init__.py']


def _application_imports(path: Path) -> list[str]:
    """Every ``app`` module the file imports, at any depth (function bodies too).

    An import of frozen helpers from the module SDK is reported as the helpers'
    own module: it is the same objects through the door a module must use.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            frozen_through_the_sdk = node.module == _SDK and all(
                alias.name in _FROZEN_NAMES for alias in node.names
            )
            names = [_ALLOWED if frozen_through_the_sdk else node.module]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        else:
            continue
        found.extend(name for name in names if name == 'app' or name.startswith('app.'))
    return found


def test_the_sdk_hands_out_the_frozen_helpers_themselves():
    for name in _FROZEN_NAMES & set(module_sdk.__all__):
        assert getattr(module_sdk, name) is getattr(migration_helpers, name), name


@pytest.mark.parametrize(
    ('line', 'expected'),
    [
        ('from app.core.module_sdk import create_table_if_absent', [_ALLOWED]),
        ('from app.core.module_sdk import CoreModelBase', [_SDK]),
        (
            'from app.core.module_sdk import create_table_if_absent, get_logger',
            [_SDK],
        ),
        ('import app.core.module_sdk', [_SDK]),
    ],
)
def test_only_the_frozen_helpers_pass_through_the_sdk(tmp_path, line, expected):
    revision = tmp_path / '001_initial.py'
    revision.write_text(line + '\n', encoding='utf-8')

    assert _application_imports(revision) == expected


def test_there_are_revisions_to_check():
    assert len(_revision_files()) > 50


@pytest.mark.parametrize(
    'path', _revision_files(), ids=lambda path: str(path.relative_to(_BACKEND))
)
def test_a_revision_imports_no_application_code(path):
    offenders = [name for name in _application_imports(path) if name != _ALLOWED]

    assert offenders == [], (
        f'{path.relative_to(_BACKEND)} imports {offenders}: a revision replays '
        f'against an old schema, so it carries a frozen copy of what it needs and '
        f'imports only {_ALLOWED}'
    )


def test_migration_helpers_keeps_its_public_names():
    public = {
        name
        for name, member in vars(migration_helpers).items()
        if not name.startswith('_')
        and inspect.isfunction(member)
        and member.__module__ == migration_helpers.__name__
    }

    missing = _FROZEN_NAMES - public
    assert not missing, (
        f'migration_helpers lost {sorted(missing)}: committed revisions call them'
    )
    assert not public - _FROZEN_NAMES, (
        f'migration_helpers gained {sorted(public - _FROZEN_NAMES)}: '
        f'add the name to _FROZEN_NAMES once it is meant to be frozen'
    )
