"""Compare each module's ``alembic_version_<module>`` table against its code head.

The failure this exists for: a module's schema gets ahead
of its version table — tables or columns from revisions the version table has not
reached already exist, because they were created out-of-band or by the old core
baseline. The next restart runs those migrations, hits
``relation already exists`` / ``column already exists``, and under
``restart: unless-stopped`` the container loops. The documented recovery was
``UPDATE alembic_version_<module> ...`` in psql on the customer's database, one
crash at a time.

The doctor turns that into a pre-flight check: it names the module, says which
DDL is already there, and prints the ``db stamp-module`` command that fixes it.

What is deliberately *not* drift, because reporting it would block ordinary
deploys:

* an empty database — a fresh install has no version tables and no module tables,
  and the doctor runs before the first migration in the instance's life;
* a version behind head with no sign of the pending DDL — that is exactly what
  the migration about to run is for;
* an empty version table whose module tables all come from the core baseline —
  ``db upgrade-modules`` already stamps that case at the base revision by itself
  (status ``reconcilable``). The doctor only fails when that automatic
  reconciliation would land on the wrong revision.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from alembic.runtime.migration import MigrationContext
from alembic.script import Script, ScriptDirectory
from sqlalchemy import Column, Connection, Engine, MetaData, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.architecture_lint._quality_checks import _collect_module_tablenames
from app.core.module_migrations import (
    MODULES_ROOT,
    discover_modules_with_migrations,
    get_version_table_name,
    module_migrations_dir,
)

DoctorStatus = Literal[
    'ok',
    'pending',
    'fresh',
    'reconcilable',
    'schema_ahead',
    'partial_schema',
    'unknown_revision',
]

#: Statuses that must stop a deploy. Everything else is a state the migration
#: about to run handles on its own.
DRIFT_STATUSES: frozenset[str] = frozenset(
    {'schema_ahead', 'partial_schema', 'unknown_revision'}
)


class DoctorInfrastructureError(RuntimeError):
    """The database could not be inspected at all (down, unreachable, no perms).

    Separate from drift on purpose: the caller fails *open* on this one. A
    database that cannot be reached will stop the migration a second later
    anyway, and blocking the boot here would replace a clear error with a
    confusing one.
    """


@dataclass(frozen=True)
class SchemaState:
    """What the database actually contains, read once and passed around."""

    tables: frozenset[str] = field(default_factory=frozenset)
    columns: frozenset[tuple[str, str]] = field(default_factory=frozenset)

    def contains(self, ddl: RevisionDDL) -> bool:
        """True if any of this revision's DDL is already in the database."""
        return bool(ddl.tables & self.tables) or bool(ddl.columns & self.columns)

    def covers(self, ddl: RevisionDDL) -> bool:
        """True if all of this revision's DDL is already in the database."""
        return ddl.tables <= self.tables and ddl.columns <= self.columns


@dataclass(frozen=True)
class RevisionDDL:
    """The part of a migration the database can be asked about afterwards."""

    tables: frozenset[str] = field(default_factory=frozenset)
    columns: frozenset[tuple[str, str]] = field(default_factory=frozenset)

    def __bool__(self) -> bool:
        return bool(self.tables or self.columns)

    def __or__(self, other: RevisionDDL) -> RevisionDDL:
        return RevisionDDL(self.tables | other.tables, self.columns | other.columns)

    def describe(self) -> str:
        parts = [f'table {name}' for name in sorted(self.tables)]
        parts += [f'{table}.{column}' for table, column in sorted(self.columns)]
        return ', '.join(parts)


@dataclass(frozen=True)
class ModuleDiagnosis:
    """One module's migration state."""

    module: str
    status: DoctorStatus
    db_revisions: frozenset[str]
    head_revisions: frozenset[str]
    detail: str
    fix_command: str | None = None

    @property
    def is_drift(self) -> bool:
        return self.status in DRIFT_STATUSES

    @property
    def db_revision_display(self) -> str:
        return ', '.join(sorted(self.db_revisions)) if self.db_revisions else '—'

    @property
    def head_revision_display(self) -> str:
        return ', '.join(sorted(self.head_revisions)) if self.head_revisions else '—'


def _script_directory(module_name: str) -> ScriptDirectory:
    return ScriptDirectory(str(module_migrations_dir(module_name)))


def ordered_revisions(module_name: str) -> list[Script]:
    """The module's revisions from base to head."""
    return list(reversed(list(_script_directory(module_name).walk_revisions())))


def _literal_str(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return getattr(func, 'id', '')


def revision_ddl(revision_path: str) -> RevisionDDL:
    """DDL a migration applies, read from ``create_table`` / ``add_column`` calls
       in its ``upgrade()``.

       AST rather than execution: the doctor must not import migration modules. Only
       literal arguments count — a table name built from a variable is skipped,
       because under-reporting costs a missed warning while guessing would block a
       deploy over a table that does not exist.

       Only ``upgrade()`` is scanned. ``downgrade()`` typically re-creates whatever
       the upgrade drops, and reading it reported a pending drop-column migration as
    "column already exists" drift — the boot loop, where following the
       suggested stamp would have skipped the migration entirely.
    """
    tree = ast.parse(Path(revision_path).read_text(encoding='utf-8'))
    tables: set[str] = set()
    columns: set[tuple[str, str]] = set()

    upgrade = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == 'upgrade'
        ),
        None,
    )
    if upgrade is None:
        return RevisionDDL()

    for node in ast.walk(upgrade):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)

        # `create_table_if_absent` is the guarded form baseline migrations use
        # (app/core/migration_helpers.py) — same DDL, so the doctor must see it.
        if name in ('create_table', 'create_table_if_absent') and node.args:
            table = _literal_str(node.args[0])
            if table:
                tables.add(table)

        elif name == 'add_column' and len(node.args) >= 2:
            table = _literal_str(node.args[0])
            column_call = node.args[1]
            if not table or not isinstance(column_call, ast.Call):
                continue
            if _call_name(column_call) != 'Column' or not column_call.args:
                continue
            column = _literal_str(column_call.args[0])
            if column:
                columns.add((table, column))

    return RevisionDDL(frozenset(tables), frozenset(columns))


#: ``ALTER TABLE`` written as SQL — ``op.execute`` with a literal, which a
#: migration uses for ``IF [NOT] EXISTS`` — and the columns its clauses name.
_SQL_ALTER_TABLE = re.compile(
    r'ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(?:\w+\.)?"?(\w+)"?([^;]*)',
    re.IGNORECASE,
)
_SQL_COLUMN_CLAUSE = re.compile(
    r'(ADD|DROP|ALTER)\s+COLUMN\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?"?(\w+)"?',
    re.IGNORECASE,
)
_SQL_INDEX = re.compile(
    r'(?:CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?'
    r'|DROP\s+INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+EXISTS\s+)?)"?(\w+)"?',
    re.IGNORECASE,
)

#: ``op`` calls whose first argument is the index or constraint name.
_NAMED_FIRST = (
    'create_index',
    'drop_index',
    'create_foreign_key',
    'create_unique_constraint',
    'create_check_constraint',
    'drop_constraint',
)


@dataclass(frozen=True)
class RevisionChanges:
    """What a migration changes, as the schema comparison will name it.

    Wider than :class:`RevisionDDL`, which keeps only what a database can be
    asked about afterwards: a column dropped or altered counts here too, and
    so do indexes and constraints, by name. The three column sets stay apart
    because they close different gaps — a revision that alters a column the
    database lost does not bring it back.
    """

    added: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    dropped: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    altered: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    names: frozenset[str] = field(default_factory=frozenset)

    @property
    def columns(self) -> frozenset[tuple[str, str]]:
        """Every column a revision touches, whatever it does to it."""
        return self.added | self.dropped | self.altered

    def __or__(self, other: RevisionChanges) -> RevisionChanges:
        return RevisionChanges(
            self.added | other.added,
            self.dropped | other.dropped,
            self.altered | other.altered,
            self.names | other.names,
        )


def revision_changes(revision_path: str) -> RevisionChanges:
    """The columns, indexes and constraints a migration's ``upgrade()`` touches.

    Read as :func:`revision_ddl` reads, from literal arguments only, plus the
    literal SQL a migration hands to ``op.execute``.
    """
    tree = ast.parse(Path(revision_path).read_text(encoding='utf-8'))
    upgrade = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == 'upgrade'
        ),
        None,
    )
    if upgrade is None:
        return RevisionChanges()

    columns = {
        'ADD': set(revision_ddl(revision_path).columns),
        'DROP': set(),
        'ALTER': set(),
    }
    names: set[str] = set()
    for node in ast.walk(upgrade):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            args = [_literal_str(arg) for arg in node.args]
            if name in ('drop_column', 'alter_column') and len(args) >= 2:
                if args[0] and args[1]:
                    columns['DROP' if name == 'drop_column' else 'ALTER'].add(
                        (args[0], args[1])
                    )
            elif name in _NAMED_FIRST and args and args[0]:
                names.add(args[0])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            sql = node.value
            for table, clauses in _SQL_ALTER_TABLE.findall(sql):
                for verb, column in _SQL_COLUMN_CLAUSE.findall(clauses):
                    columns[verb.upper()].add((table, column))
            names |= set(_SQL_INDEX.findall(sql))
    return RevisionChanges(
        frozenset(columns['ADD']),
        frozenset(columns['DROP']),
        frozenset(columns['ALTER']),
        frozenset(names),
    )


def tables_created_through(module_name: str, revision: str) -> set[str]:
    """Every table created by the chain from base up to and including *revision*."""
    script = _script_directory(module_name)
    tables: set[str] = set()
    for rev in script.walk_revisions('base', revision):
        tables |= revision_ddl(rev.path).tables
    return tables


def suggest_stamp_revision(module_name: str, schema: SchemaState) -> str | None:
    """Highest revision whose DDL is fully present — the safe stamp target.

    Walks base → head and advances only on revisions that add DDL the database
    can testify about. A revision that only creates an index or backfills data
    leaves no evidence either way, so the suggestion stays on the last one that
    does, and the operator can always pass an explicit revision.

    Returns ``None`` when not even the first revision's DDL exists — there is
    nothing to reconcile and the migrations should simply run.
    """
    candidate: str | None = None
    accumulated = RevisionDDL()
    for rev in ordered_revisions(module_name):
        ddl = revision_ddl(rev.path)
        if not ddl:
            continue
        accumulated = accumulated | ddl
        if not schema.covers(accumulated):
            break
        candidate = rev.revision
    return candidate


def _read_version_rows(
    conn: Connection, version_table: str, existing_tables: Iterable[str]
) -> frozenset[str]:
    if version_table not in set(existing_tables):
        return frozenset()
    rows = conn.execute(
        text(f'SELECT version_num FROM "{version_table}"')  # noqa: S608 — name built from a module directory name, never user input
    ).fetchall()
    return frozenset(row[0] for row in rows)


def read_schema_state(conn: Connection) -> SchemaState:
    """Tables and columns currently in the database, in two round trips."""
    tables = frozenset(inspect(conn).get_table_names())
    rows = conn.execute(
        text(
            'SELECT table_name, column_name FROM information_schema.columns '
            'WHERE table_schema = current_schema()'
        )
    ).fetchall()
    return SchemaState(tables, frozenset((row[0], row[1]) for row in rows))


def _diagnose_stampless(
    module_name: str, schema: SchemaState, heads: frozenset[str]
) -> ModuleDiagnosis:
    """No version row: fresh module, baseline leftovers, or a real mess."""
    module_tables = _collect_module_tablenames(MODULES_ROOT / module_name)
    present = module_tables & schema.tables
    revisions = ordered_revisions(module_name)
    base_revision = revisions[0].revision if revisions else 'base'

    def diagnosis(
        status: DoctorStatus, detail: str, fix: str | None
    ) -> ModuleDiagnosis:
        return ModuleDiagnosis(
            module=module_name,
            status=status,
            db_revisions=frozenset(),
            head_revisions=heads,
            detail=detail,
            fix_command=fix,
        )

    if not module_tables or not present:
        return diagnosis(
            'fresh', 'no version row and no tables — migrations will create them', None
        )

    if present != module_tables:
        missing = ', '.join(sorted(module_tables - present))
        return diagnosis(
            'partial_schema',
            f'some tables exist, some do not (missing: {missing})',
            f'python manage.py db stamp-module {module_name} <revision>',
        )

    stamp_at = suggest_stamp_revision(module_name, schema) or base_revision
    if stamp_at == base_revision:
        # Exactly what `db upgrade-modules` already stamps by itself.
        return diagnosis(
            'reconcilable',
            f'tables from the core baseline, no version row — '
            f'upgrade-modules will stamp {base_revision}',
            None,
        )

    return diagnosis(
        'schema_ahead',
        f'schema reaches {stamp_at} but the version table is empty — '
        f'upgrade-modules would stamp {base_revision} and then re-apply DDL '
        f'that already exists',
        f'python manage.py db stamp-module {module_name} {stamp_at}',
    )


def _pending_revisions(module_name: str, db_revisions: frozenset[str]) -> list[Script]:
    """The module's revisions after the last one the version table records."""
    revisions = ordered_revisions(module_name)
    applied_upto = max(
        (index for index, rev in enumerate(revisions) if rev.revision in db_revisions),
        default=-1,
    )
    return revisions[applied_upto + 1 :]


def pending_module_changes(conn: Connection) -> RevisionChanges:
    """What every module chain still has to change in this database.

    The revisions past the one each module's version table records — what
    ``db upgrade-modules`` is about to run. A module with no version row has
    every revision pending.
    """
    existing = inspect(conn).get_table_names()
    pending = RevisionChanges()
    for module_name in discover_modules_with_migrations():
        db_revisions = _read_version_rows(
            conn, get_version_table_name(module_name), existing
        )
        for rev in _pending_revisions(module_name, db_revisions):
            pending = pending | revision_changes(rev.path)
    return pending


def _diagnose_pending(
    module_name: str,
    schema: SchemaState,
    db_revisions: frozenset[str],
    heads: frozenset[str],
) -> ModuleDiagnosis:
    """Behind head — normal, unless the pending DDL is already in the database."""
    already_there = RevisionDDL()
    for rev in _pending_revisions(module_name, db_revisions):
        ddl = revision_ddl(rev.path)
        if schema.contains(ddl):
            already_there = already_there | RevisionDDL(
                ddl.tables & schema.tables, ddl.columns & schema.columns
            )

    if not already_there:
        return ModuleDiagnosis(
            module=module_name,
            status='pending',
            db_revisions=db_revisions,
            head_revisions=heads,
            detail='behind head — the upgrade about to run will apply the rest',
        )

    stamp_at = suggest_stamp_revision(module_name, schema)
    fix = (
        f'python manage.py db stamp-module {module_name} {stamp_at}'
        if stamp_at
        else f'python manage.py db stamp-module {module_name} <revision>'
    )
    return ModuleDiagnosis(
        module=module_name,
        status='schema_ahead',
        db_revisions=db_revisions,
        head_revisions=heads,
        detail=(
            f'DDL from unapplied revisions already exists '
            f'({already_there.describe()}) — those migrations would fail'
        ),
        fix_command=fix,
    )


def diagnose_module(
    module_name: str, schema: SchemaState, db_revisions: frozenset[str]
) -> ModuleDiagnosis:
    """Classify one module from its version rows and the state of the database."""
    script = _script_directory(module_name)
    heads = frozenset(script.get_heads())

    if not db_revisions:
        return _diagnose_stampless(module_name, schema, heads)

    known = {rev.revision for rev in script.walk_revisions()}
    unknown = db_revisions - known
    if unknown:
        return ModuleDiagnosis(
            module=module_name,
            status='unknown_revision',
            db_revisions=db_revisions,
            head_revisions=heads,
            detail=(
                f'version table points at {", ".join(sorted(unknown))}, which no '
                f'migration file defines — the code is older than the database'
            ),
            fix_command=f'python manage.py db stamp-module {module_name} <revision>',
        )

    if db_revisions == heads:
        return ModuleDiagnosis(
            module=module_name,
            status='ok',
            db_revisions=db_revisions,
            head_revisions=heads,
            detail='at head',
        )

    return _diagnose_pending(module_name, schema, db_revisions, heads)


def diagnose_modules(
    engine: Engine, modules: Sequence[str] | None = None
) -> list[ModuleDiagnosis]:
    """Diagnose every module with migrations, in one pass over the database.

    Raises ``DoctorInfrastructureError`` if the database cannot be inspected.
    """
    names = (
        sorted(modules) if modules is not None else discover_modules_with_migrations()
    )
    if not names:
        return []

    try:
        with engine.connect() as conn:
            schema = read_schema_state(conn)
            versions = {
                name: _read_version_rows(
                    conn, get_version_table_name(name), schema.tables
                )
                for name in names
            }
    except SQLAlchemyError as exc:
        raise DoctorInfrastructureError(str(exc)) from exc

    return [diagnose_module(name, schema, versions[name]) for name in names]


def has_drift(diagnoses: Sequence[ModuleDiagnosis]) -> bool:
    return any(d.is_drift for d in diagnoses)


def unvalidated_constraints(engine: Engine) -> list[tuple[str, str]]:
    """Constraints added ``NOT VALID`` and never validated, as (table, name).

    Not drift, and never a reason to refuse a boot: such a constraint checks
    every new write, it only says nothing about the rows that were there
    before it. ``schemafk01`` leaves a foreign key in this state on purpose
    when the rows under it point at parents that no longer exist, and the
    doctor keeps naming it on every start, so the promise to finish it does
    not live only in one migration's output.

    Raises ``DoctorInfrastructureError`` if the database cannot be inspected.
    """
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    'SELECT conrelid::regclass::text, conname FROM pg_constraint '
                    'WHERE NOT convalidated ORDER BY 1, 2'
                )
            ).fetchall()
    except SQLAlchemyError as exc:
        raise DoctorInfrastructureError(str(exc)) from exc
    return [(row[0], row[1]) for row in rows]


@dataclass(frozen=True)
class ColumnTypeDrift:
    """A column whose live type is not the type its model declares."""

    table: str
    column: str
    live_type: str
    model_type: str


def _complete_metadata(skip: Collection[str] = ()) -> MetaData:
    """``Base.metadata`` with every model imported: core, templates, each module.

    A table joins the metadata only when the file declaring it is imported, and
    a CLI process has imported none of them — ``app.models`` itself leaves some
    core models out of its ``__init__``, so its submodules are walked one by one.
    The modules named in *skip* are the ones discovery rejected: importing their
    models runs the package that failed to load (or that is not allowed to), and
    the backend does not load them either.
    """
    import app.models as core_models
    from app.database import Base

    importlib.import_module('app.core.template_models')
    for info in pkgutil.iter_modules(core_models.__path__):
        importlib.import_module(f'app.models.{info.name}')
    for module_dir in sorted(MODULES_ROOT.iterdir()):
        if (
            not module_dir.is_dir()
            or module_dir.name.startswith('_')
            or module_dir.name in skip
        ):
            continue
        name = f'app.modules.{module_dir.name}.models'
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise
    return Base.metadata


def column_type_drift(
    engine: Engine, skip: Collection[str] = ()
) -> list[ColumnTypeDrift]:
    """Columns present in both the models and the database, typed differently.

    The case this exists for: a database that grew through an older chain kept
    ``timestamp without time zone`` where the models declare
    ``DateTime(timezone=True)``, and nothing reported it until a user saw times
    shifted by their UTC offset. The comparison is Alembic's own
    (``compare_type``), the one ``--autogenerate`` uses. Tables or columns that
    exist on only one side are not reported here: a module that is not
    installed has no tables, and that is not drift.

    Not a reason to refuse a boot either: the doctor runs before the
    migrations, and the migration that fixes a drift is often the one about to
    run.

    The modules in *skip* are left out of the models (``_complete_metadata``).

    Raises ``DoctorInfrastructureError`` if the database cannot be inspected.
    """
    metadata = _complete_metadata(skip)
    drift: list[ColumnTypeDrift] = []
    try:
        with engine.connect() as conn:
            live_tables = inspect(conn).get_multi_columns()
            impl = MigrationContext.configure(conn).impl
            for (_schema, table_name), live_columns in live_tables.items():
                table = metadata.tables.get(table_name)
                if table is None:
                    continue
                for live in live_columns:
                    model_column = table.columns.get(live['name'])
                    if model_column is None or not impl.compare_type(
                        Column(live['name'], live['type']), model_column
                    ):
                        continue
                    drift.append(
                        ColumnTypeDrift(
                            table=table_name,
                            column=live['name'],
                            live_type=str(live['type'].compile(conn.dialect)),
                            model_type=str(model_column.type.compile(conn.dialect)),
                        )
                    )
    except SQLAlchemyError as exc:
        raise DoctorInfrastructureError(str(exc)) from exc
    return sorted(drift, key=lambda entry: (entry.table, entry.column))
