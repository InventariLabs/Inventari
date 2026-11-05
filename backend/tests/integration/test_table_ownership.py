"""Regression guard: module-owned tables must NOT be in core baseline_002.

Since the module migration extraction,
every module's tables are created by that module's own
``migrations/versions/001_initial.py``, NOT by the core
``baseline_002_full_schema.py``.

This test catches regressions where someone adds a new table to a module's
``models.py`` and (by habit or accident) puts the ``create_table`` in the
core baseline instead of the module's ``versions/`` directory.
"""

import ast
from pathlib import Path

import pytest

from app.core.architecture_lint._quality_checks import _collect_module_tablenames

MODULES_ROOT = Path(__file__).resolve().parents[2] / 'app' / 'modules'
BASELINE_FILE = (
    Path(__file__).resolve().parents[2]
    / 'migrations'
    / 'versions'
    / 'baseline_002_full_schema.py'
)


def _parse_baseline_create_table_calls(baseline_path: Path) -> set[str]:
    """Return table names from ``op.create_table('...', ...)`` calls."""
    tree = ast.parse(baseline_path.read_text(encoding='utf-8'))
    tables: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'create_table'
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            tables.add(node.args[0].value)
    return tables


def _collect_all_module_tablenames() -> dict[str, set[str]]:
    """Return ``{module_name: {table_names}}`` for all modules with tables."""
    result: dict[str, set[str]] = {}
    for module_dir in sorted(MODULES_ROOT.iterdir()):
        if not module_dir.is_dir() or module_dir.name.startswith('_'):
            continue
        tables = _collect_module_tablenames(module_dir)
        if tables:
            result[module_dir.name] = tables
    return result


class TestTableOwnership:
    """Ensure no module table is created by the core baseline migration."""

    @pytest.mark.integration
    def test_no_module_tables_in_core_baseline(self) -> None:
        """Module tables must only appear in module migrations, not baseline."""
        module_tables = _collect_all_module_tablenames()
        baseline_tables = _parse_baseline_create_table_calls(BASELINE_FILE)

        all_module_tables: set[str] = set()
        for tables in module_tables.values():
            all_module_tables |= tables

        overlap = all_module_tables & baseline_tables
        assert overlap == set(), (
            f'Tables {sorted(overlap)} are defined in module models but also '
            f'created by core baseline_002_full_schema.py. Module tables must '
            f'be created ONLY by their module migration '
            f'(app/modules/<M>/migrations/versions/001_initial.py). '
            f'Remove the create_table + indexes from baseline and ensure the '
            f'module has versions/001_initial.py.'
        )

    @pytest.mark.integration
    def test_every_module_with_tables_has_versions(self) -> None:
        """Every module with Core Base tables must have versions/001_initial.py.

        Exceptions are recorded in ``module_migrations_baseline.txt``
        (e.g. ``example_widgets`` — demo module).
        """
        baseline_path = MODULES_ROOT.parent / 'core' / 'module_migrations_baseline.txt'
        baselined_modules: set[str] = set()
        if baseline_path.exists():
            for line in baseline_path.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    baselined_modules.add(line)

        module_tables = _collect_all_module_tablenames()
        missing: list[str] = []
        for module_name, tables in sorted(module_tables.items()):
            if module_name in baselined_modules:
                continue
            versions_dir = MODULES_ROOT / module_name / 'migrations' / 'versions'
            if not versions_dir.is_dir():
                missing.append(
                    f'{module_name} ({len(tables)} tables, no migrations/versions/ dir)'
                )
                continue
            version_files = [
                f for f in versions_dir.glob('*.py') if f.name != '__init__.py'
            ]
            if not version_files:
                missing.append(f'{module_name} ({len(tables)} tables, empty versions/)')

        assert missing == [], (
            f'Modules with tables but no migrations: {missing}. '
            f'Create versions/001_initial.py or add to '
            f'module_migrations_baseline.txt if intentionally deferred.'
        )
