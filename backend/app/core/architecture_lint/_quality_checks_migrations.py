"""Module-migrations check + table-name extraction helpers.

Two checks live here:

- ``_check_module_migrations_exist`` — modules with tables in
  ``models.py`` / ``models/`` must have a non-empty ``migrations/versions/``
  directory (both gaps found when module migrations were extracted from the
  core baseline: an empty ``versions/`` and an unscanned ``models/``).
- Table-name extraction helpers (``_extract_tablenames``,
  ``_collect_module_tablenames``, ``_list_version_files``) — AST-based
  Core-Base-aware table discovery used only by the migration check.

The helpers live with the check because they are tightly coupled: the
``__tablename__`` discovery is only meaningful in service of detecting
modules that need migrations.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

from ._constants import _rel

_CORE_BASE_MODULES = {
    'app.database',
    'app.core.db_facade',
    'app.core.db',
}

#: Calls whose first string argument names a table the migration makes:
#: plain ``op.create_table`` and the helper this repository's own
#: migrations reach for, ``create_table_if_absent`` — as a bare import or
#: off any object.
_CREATE_TABLE_CALLS = frozenset({'create_table', 'create_table_if_absent'})

#: The one way a raw SQL string still names a table: a CREATE TABLE
#: statement in a literal passed to ``execute``. Dynamic SQL built at
#: runtime stays invisible — there is no name in the file to read.
_CREATE_TABLE_SQL = re.compile(
    r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["\']?([A-Za-z_][A-Za-z0-9_]*)',
    re.IGNORECASE,
)

#: The same for the opposite move: a table the history RETIRES
#: (``op.drop_table`` or a DROP TABLE literal) must not stay in the
#: module's owned set — the migrations are the only record of ownership,
#: and a name created in one revision and dropped in a later one is not
#: the module's table at head.
_DROP_TABLE_SQL = re.compile(
    r'DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?["\']?([A-Za-z_][A-Za-z0-9_]*)',
    re.IGNORECASE,
)


def _extract_tablenames(file_path: Path) -> set[str]:
    """Every table name the file states, by any of the three ways.

    ``__tablename__ = 'x'`` on any model class; ``op.create_table('x')``
    and ``create_table_if_absent('x', …)`` in a migration — the helper is
    how this repository's own migrations create tables, and a walk that
    missed it named an incomplete set, which is how an uninstall summary
    came to claim a drop the database never made; and a CREATE TABLE
    statement inside a string literal given to ``execute``. Deliberately
    blind to which ``DeclarativeBase`` the model inherits: a community
    module may not import ``app.database`` at all (the safety validator
    forbids it), so every community model sits on a base of its own — the
    old walk skipped exactly those files, reported zero tables for the one
    kind of module this check exists for, and the gate read green while
    blind. Modules whose own-Base tables really live on a separate
    database are excluded one level up, by inheriting the separate-database
    base (:func:`_separate_database_classes`), not by the base itself.
    """
    try:
        source = file_path.read_text(encoding='utf-8')
    except OSError:
        return set()
    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return set()

    tables: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == '__tablename__'
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            tables.add(node.value.value)
        elif (
            isinstance(node, ast.Call)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and (
                (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in _CREATE_TABLE_CALLS
                )
                or (
                    isinstance(node.func, ast.Name)
                    and node.func.id in _CREATE_TABLE_CALLS
                )
            )
        ):
            tables.add(node.args[0].value)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'execute'
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            tables.update(
                match.group(1)
                for match in _CREATE_TABLE_SQL.finditer(node.args[0].value)
            )
    return tables


def _file_string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level ``NAME = 'literal'`` bindings of one file.

    Migration files name a table once at the top (``_TABLE = 'x'``) and
    reuse the name through upgrade and downgrade — a call read without
    resolving those constants sees the upgrade's literal create but not
    the downgrade's drop of the very same table.
    """
    constants: dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            constants[node.targets[0].id] = node.value.value
    return constants


def _dropped_tablenames(file_path: Path) -> set[str]:
    """Tables the file's FORWARD history retires, by either of the two ways.

    ``op.drop_table('x')`` inside ``def upgrade()`` — with the name
    literal or through a module-level constant — and a DROP TABLE
    statement inside a string given to ``execute`` there. Only the
    forward move retires a table: a drop inside ``downgrade()`` is the
    mirror of a create, exactly what a well-formed migration pair does,
    and the table it names still exists at head.
    """
    try:
        source = file_path.read_text(encoding='utf-8')
    except OSError:
        return set()
    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return set()

    constants = _file_string_constants(tree)
    dropped: set[str] = set()
    for function in (n for n in tree.body if isinstance(n, ast.FunctionDef)):
        if function.name != 'upgrade':
            continue
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'drop_table'
                and node.args
            ):
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    dropped.add(first.value)
                elif isinstance(first, ast.Name) and first.id in constants:
                    dropped.add(constants[first.id])
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'execute'
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                dropped.update(
                    match.group(1)
                    for match in _DROP_TABLE_SQL.finditer(node.args[0].value)
                )
    return dropped


#: The separate-database base: defined once, inherited by the models whose
#: tables the products engine runtime-manages. Inheritance of THIS base —
#: not any import — is what marks a module as living on the other database.
_SEPARATE_DB_BASE_MODULE = 'app.modules.nutrition.models'
_SEPARATE_DB_BASE_NAME = 'OFFBase'

#: Where the defining file lives, by structure: the nutrition module's own
#: top-level ``models.py``, in a directory actually named ``nutrition``.
#: Identity by directory structure, not by the path's segments — a module
#: can nest a directory shaped like the package path and produce any dotted
#: name from it, but it cannot sit where ``nutrition`` sits.
_SEPARATE_DB_BASE_MODULE_DIR = 'nutrition'
_SEPARATE_DB_DEFINING_PATH = 'models.py'


def _separate_database_classes(module_dir: Path) -> Iterator[ast.ClassDef]:
    """Yield every class that inherits the separate-database base.

    The one place that reads the seam: a module is on the other database
    when this yields anything, and the tables it covers
    (:func:`_separate_database_tablenames`) come from the same walk, so the
    two cannot disagree about which classes sit on the other database.

    The verdict reads INHERITANCE of the separate-database base, not import
    names. ``OFFBase`` (``app.modules.nutrition.models``) is a
    DeclarativeBase whose metadata the products engine creates at runtime,
    and a table joins that metadata only through a class inheriting the base
    — importing the products engine (``app.core.db_facade``) by itself
    proves nothing about where any table lives. Trusting that import name
    made the gate blind on demand: one line in any file switched the whole
    module off, which is how a module with tables and no migrations read as
    green. The defining module counts through its local subclasses; every
    other module must show the import from the defining path AND a class
    that inherits the base — naming a local class ``OFFBase`` does not
    travel.

    What makes a file THE defining one is its address in the tree, not its
    name: ``models.py`` directly inside a module directory named
    ``nutrition``. The first version of this verdict read a dotted name
    out of the absolute path instead, anchored at the last ``app`` segment
    — and any module could nest a directory shaped like the package path
    (``app/modules/nutrition/models.py`` inside itself), produce that name
    from its own folders, define a local ``OFFBase`` in the file, and
    switch the whole module to the separate-database reading with its real
    tables left unreported. Directory structure cannot be counterfeited
    that way: a nested catalog is still inside a differently named module,
    and there is only one ``nutrition`` under the modules root. The
    layout-independence the dotted name pursued comes free — this
    predicate never looks above ``module_dir``, so the checkout or mount
    root is irrelevant to it.

    Why not a manifest declaration of the seam instead of this AST read:
    a declared seam is a second source to keep in sync with the models
    that actually run, it widens the module schema for one consumer, and
    a stale declaration would silence the gate in exactly the way the
    trusted import name did — the code a table really sits on is the one
    witness that cannot drift from the tables.
    """
    for py_file in sorted(module_dir.rglob('*.py')):
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        class_defs: list[ast.ClassDef] = []
        defines_base = False
        imports_base = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_defs.append(node)
                if node.name == _SEPARATE_DB_BASE_NAME and any(
                    isinstance(base, ast.Name) and base.id == 'DeclarativeBase'
                    for base in node.bases
                ):
                    defines_base = True
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module == _SEPARATE_DB_BASE_MODULE
                and any(alias.name == _SEPARATE_DB_BASE_NAME for alias in node.names)
            ):
                imports_base = True
        is_defining_file = (
            module_dir.name == _SEPARATE_DB_BASE_MODULE_DIR
            and py_file == module_dir / _SEPARATE_DB_DEFINING_PATH
        )
        if imports_base or (defines_base and is_defining_file):
            for cls in class_defs:
                if is_defining_file and cls.name == _SEPARATE_DB_BASE_NAME:
                    continue  # the base itself is not a table owner
                for base in cls.bases:
                    base_name = (
                        base.id
                        if isinstance(base, ast.Name)
                        else (base.attr if isinstance(base, ast.Attribute) else None)
                    )
                    if base_name == _SEPARATE_DB_BASE_NAME:
                        yield cls
                        break


def _separate_database_tablenames(module_dir: Path) -> set[str]:
    """Tables of the classes that live on the separate database.

    The exclusion is per TABLE, not per module: one class inheriting the
    separate-database base used to switch the whole module to the
    Core-Base-only reading, hiding every other table the module owns. Now
    only the tables of the inheriting classes leave the module's set.
    """
    tables: set[str] = set()
    for cls in _separate_database_classes(module_dir):
        for child in ast.walk(cls):
            if (
                isinstance(child, ast.Assign)
                and len(child.targets) == 1
                and getattr(child.targets[0], 'id', None) == '__tablename__'
                and isinstance(child.value, ast.Constant)
                and isinstance(child.value.value, str)
            ):
                tables.add(child.value.value)
    return tables


def _collect_module_tablenames(module_dir: Path) -> set[str]:
    """Tables the module owns, named by its models or its migrations.

    Both, because neither alone is complete: a model can exist before the
    migration that creates it, and a migration can create a table no model
    maps. What the FORWARD history retires leaves the set — the answer is
    what the module owns at head, not everything its history ever named
    (equipment's document templates are created in 001 and dropped in 008's
    upgrade; a set that kept the name would send every consumer hunting for
    a table nobody owns anymore). A drop inside a ``downgrade()`` is the
    mirror of a create and retires nothing — the table it names is still
    owned. Tables that live on a separate database (classes inheriting
    the separate-database base) are runtime-managed there and core Alembic
    will never track them; they leave the set one by one, so a module with
    both kinds still reports its own tables.
    """
    tables: set[str] = set()
    scan = [p for p in (module_dir / 'models.py',) if p.exists()]
    models_pkg = module_dir / 'models'
    if models_pkg.is_dir():
        scan.extend(
            py_file
            for py_file in sorted(models_pkg.rglob('*.py'))
            if py_file.name != '__init__.py'
        )
    for py_file in scan:
        tables |= _extract_tablenames(py_file)
    version_files = _list_version_files(module_dir / 'migrations' / 'versions')
    dropped: set[str] = set()
    for py_file in version_files:
        tables |= _extract_tablenames(py_file)
        dropped |= _dropped_tablenames(py_file)
    return tables - dropped - _separate_database_tablenames(module_dir)


def _list_version_files(versions_dir: Path) -> list[Path]:
    """List migration ``.py`` files in ``versions/``, excluding ``__init__.py``."""
    if not versions_dir.is_dir():
        return []
    return sorted(
        py_file
        for py_file in versions_dir.glob('*.py')
        if py_file.name != '__init__.py'
    )


def _check_module_migrations_exist(
    modules_root: Path,
    baseline_modules: set[str] | None = None,
) -> list[str]:
    """Emit ``::error`` for modules with tables but missing or empty migrations.

    Catches two violation kinds:

    1. Module defines tables (in ``models.py`` OR ``models/`` package) but has
       no ``migrations/`` directory.
    2. Module has ``migrations/`` but ``versions/`` contains no ``.py`` files
       besides ``__init__.py``.

    Baselined modules emit ``::notice`` so they stay visible in PR review
    without blocking CI. Entries are removed from the baseline as each module
    gets its migrations.
    """
    baseline_modules = baseline_modules or set()
    errors: list[str] = []
    for module_dir in sorted(modules_root.iterdir()):
        if not module_dir.is_dir() or module_dir.name.startswith('_'):
            continue
        tables = _collect_module_tablenames(module_dir)
        if not tables:
            continue
        module_name = module_dir.name
        is_baselined = module_name in baseline_modules
        severity = 'notice' if is_baselined else 'error'
        migrations_dir = module_dir / 'migrations'
        if not migrations_dir.exists():
            # Point the annotation at models.py (or the package) for navigation.
            annotation_path = module_dir / 'models.py'
            if not annotation_path.exists():
                annotation_path = module_dir / 'models'
            rel = _rel(annotation_path)
            errors.append(
                f'::{severity} file={rel},title=Architecture: Module tables without migrations::'
                f"Module '{module_name}' defines {len(tables)} table(s) "
                f'({", ".join(sorted(tables))}) but has no migrations/ directory. '
                f'Run: module create {module_name} '
                f'or create app/modules/{module_name}/migrations/ manually.'
            )
            continue
        versions_dir = migrations_dir / 'versions'
        version_files = _list_version_files(versions_dir)
        if not version_files:
            rel = _rel(versions_dir)
            errors.append(
                f'::{severity} file={rel},title=Architecture: Empty module migrations::'
                f"Module '{module_name}' has migrations/ but versions/ is empty "
                f'({len(tables)} table(s) unmanaged: {", ".join(sorted(tables))}). '
                f'Add versions/001_initial.py — see api_keys/migrations/versions/001_initial.py '
                f'for the reference pattern.'
            )
    return errors
