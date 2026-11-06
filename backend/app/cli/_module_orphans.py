"""What an uninstall leaves behind — counted before it runs.

Removing a module removes its code. It does not remove what the module
wrote while it was installed, and most of that does not live in the
module's own tables: an organization still lists the name in
``enabled_modules``, the audit journal still holds entries about records
only this module could read, core items and categories still carry its
``module_name``, webhooks still subscribe to its events, files still sit
under ``<org>/<module>/``.

Uninstalling used to answer that question by deleting the schema — the
default ``on_uninstall`` downgrades the module's migrations to base — so
the leftovers question never came up and the data went with it. Now that
the tables stay, somebody has to say what stayed, in numbers, at the
moment of the decision. That is this module: it counts, it never deletes,
and every probe degrades to silence when the table it asks about is not
installed here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import get_logger

logger = get_logger(__name__)

#: How many names a group prints before it stops naming and just counts.
_DETAIL_LIMIT = 5

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

#: A table name has to be interpolated into the count query — SQL has no
#: bind parameter for an identifier — so a name that is not one is dropped
#: rather than quoted. The names come from an installed module's own files,
#: which is code the operator chose to run in-process; this is not the
#: barrier that protects them, it is the one that keeps a typo or a clever
#: string from reaching the database as syntax.
_IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,62}$')


@dataclass(frozen=True)
class OrphanGroup:
    """One kind of leftover: what it is, how many, and where to look."""

    label: str
    count: int
    where: str
    names: tuple[str, ...] = ()
    #: Whether ``--drop-data`` is what removes this. Only the module's own
    #: tables are; everything else in the report outlives the uninstall
    #: either way, which is the part an operator reaching for the flag is
    #: least likely to expect.
    goes_with_drop_data: bool = False
    #: Wording for a count of one. A report that says "1 stored files"
    #: reads as generated rather than written, and the operator is being
    #: asked to make a decision on it.
    singular: str = ''
    #: Where-line for the ``--drop-data`` view of a group that flag
    #: removes. ``where`` describes what an uninstall without it leaves
    #: behind, which under "will destroy" would say the opposite.
    where_dropped: str = ''

    def reads_as(self) -> str:
        if self.count < 0:
            return f'not counted: {self.label}'
        noun = self.singular if self.count == 1 and self.singular else self.label
        return f'{self.count} {noun}'


@dataclass(frozen=True)
class OrphanReport:
    """What the probes found, and whether every probe could run.

    An empty group list alone cannot say whether the module stored
    nothing or the database could not be read: both used to arrive as
    an empty list, and the uninstall printed the first meaning for the
    second case. A non-empty ``failures`` marks the report incomplete,
    so no caller can mistake it for an answer.
    """

    groups: tuple[OrphanGroup, ...]
    failures: tuple[str, ...] = ()


def _table_exists(db, table: str) -> bool:
    """True when *table* is present in this database.

    Half the probes below ask about module-owned tables — approvals,
    webhooks — which a given installation may simply not have. A missing
    table is not a failure to report; it is a question that does not
    apply here.
    """
    return bool(db.execute(text('SELECT to_regclass(:t)'), {'t': table}).scalar())


def _scalar_count(db, sql: str, params: dict[str, object]) -> int:
    return int(db.execute(text(sql), params).scalar() or 0)


def _names(db, sql: str, params: dict[str, object]) -> tuple[str, ...]:
    rows = db.execute(text(sql), params).scalars().all()
    return tuple(str(r) for r in rows[:_DETAIL_LIMIT])


def _tablenames_in(source: str) -> set[str]:
    """Every table a Python file names, by any of the three ways.

    ``__tablename__ = 'x'`` on a model class; ``op.create_table('x')`` and
    ``create_table_if_absent('x', …)`` in a migration — the helper is how
    this repository's own migrations create tables, and a walker that
    missed it named an incomplete set: the uninstall summary then claimed
    a drop the database never made, with the helper's table still sitting
    in it; and a CREATE TABLE statement inside a string literal given to
    ``execute``. All three, because no single one is complete: a module
    can create a table no model maps (a join table, an audit trail), and
    a model can exist before the migration that creates it.

    Deliberately blind to which ``DeclarativeBase`` a model inherits from.
    The architecture lint has a table walk of its own, and it excludes
    models built on a non-Core base on the grounds that core Alembic does
    not track them — true there, and exactly wrong here: a community
    module may not import ``app.database`` at all (the AST validator
    forbids it), so *every* community model sits on a base of its own.
    Reusing that walk reported zero tables for the one kind of module
    this report exists for.
    """
    import ast

    tables: set[str] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == '__tablename__'
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


def _module_tables(name: str) -> tuple[set[str], tuple[str, ...]]:
    """Table names the installed module owns, read from its own files.

    Read from the copy on disk, which is still there when the report
    runs — the walk happens before any file is removed. The second half
    names every file that could not be read: its tables cannot be named,
    and an empty set alone would read as "nothing to keep".
    """
    from app.cli._module_meta import BACKEND_MODULES_DIR

    module_dir: Path = BACKEND_MODULES_DIR / name
    if not module_dir.is_dir():
        return set(), ()
    tables: set[str] = set()
    unreadable: list[str] = []
    for py_file in sorted(module_dir.rglob('*.py')):
        try:
            tables |= {
                table
                for table in _tablenames_in(py_file.read_text(encoding='utf-8'))
                if _IDENTIFIER.match(table)
            }
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError) as exc:
            logger.warning(
                '[module-uninstall] cannot read tables from %s: %s', py_file, exc
            )
            unreadable.append(f'cannot read tables from {py_file}: {exc}')
    return tables, tuple(unreadable)


def _own_tables_group(db, module_tables: set[str]) -> OrphanGroup | None:
    tables = sorted(t for t in module_tables if _table_exists(db, t))
    if not tables:
        return None
    total = 0
    populated: list[str] = []
    for table in tables:
        # S608: no bind parameter exists for an identifier; the name
        # matched _IDENTIFIER before it got here.
        rows = _scalar_count(db, f'SELECT count(*) FROM "{table}"', {})  # noqa: S608
        total += rows
        if rows:
            populated.append(f'{table} ({rows})')
    return OrphanGroup(
        label="rows in the module's own tables",
        singular="row in the module's own tables",
        goes_with_drop_data=True,
        count=total,
        where='kept as they are; ' + ', '.join(tables),
        where_dropped='dropped with the module; ' + ', '.join(tables),
        # One table is already named on the line above; listing it again
        # under itself is noise. The per-table split earns its place only
        # when there is more than one table to split.
        names=tuple(populated[:_DETAIL_LIMIT]) if len(tables) > 1 else (),
    )


def _enabled_group(db, name: str) -> OrphanGroup | None:
    sql = """
        SELECT name FROM organizations
        WHERE enabled_modules::jsonb @> to_jsonb(CAST(:n AS text))
        ORDER BY name
    """
    count_sql = """
        SELECT count(*) FROM organizations
        WHERE enabled_modules::jsonb @> to_jsonb(CAST(:n AS text))
    """
    count = _scalar_count(db, count_sql, {'n': name})
    if not count:
        return None
    return OrphanGroup(
        label='organizations still listing the module as enabled',
        singular='organization still listing the module as enabled',
        count=count,
        where='organizations.enabled_modules — the name outlives the code',
        names=_names(db, sql, {'n': name}),
    )


def _tagged_core_rows(db, name: str) -> list[OrphanGroup]:
    """Core records this module created and tagged with its name."""
    groups: list[OrphanGroup] = []
    for table, label in (
        ('items', 'inventory records'),
        ('categories', 'categories'),
    ):
        if not _table_exists(db, table):
            continue
        count = _scalar_count(
            db,
            f'SELECT count(*) FROM "{table}" WHERE module_name = :n',  # noqa: S608 — fixed table list
            {'n': name},
        )
        if count:
            groups.append(
                OrphanGroup(
                    label=f'{label} tagged with this module',
                    singular=f'{label} tagged with this module',
                    count=count,
                    where=f'{table}.module_name — a core table, never dropped',
                )
            )
    return groups


def _prefixed_group(
    db,
    name: str,
    table: str,
    column: str,
    label: str,
    singular: str,
    *,
    separator: str = '_',
) -> OrphanGroup | None:
    """Rows whose *column* names one of the module's own kinds.

    Modules name what they own after themselves — ``maker_recipe``,
    ``recipe.cooked`` — so the prefix is the only link between a core row
    and the module that wrote it. It is a convention, not a foreign key,
    which is why the report says "naming" rather than "belonging to".
    """
    if not _table_exists(db, table):
        return None
    sql = f"""
        SELECT count(*) FROM "{table}"
        WHERE {column} = :n OR {column} LIKE :prefix
    """  # noqa: S608 — fixed table/column pairs, values bound
    count = _scalar_count(db, sql, {'n': name, 'prefix': f'{name}{separator}%'})
    if not count:
        return None
    return OrphanGroup(
        label=label,
        singular=singular,
        count=count,
        where=f'{table}.{column} starting with {name!r}',
    )


def _webhook_group(db, name: str) -> OrphanGroup | None:
    if not _table_exists(db, 'webhook_endpoints'):
        return None
    sql = """
        SELECT count(*) FROM webhook_endpoints
        WHERE EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(event_types::jsonb) e
            WHERE e LIKE :prefix
        )
    """
    count = _scalar_count(db, sql, {'prefix': f'{name}.%'})
    if not count:
        return None
    return OrphanGroup(
        label="webhook endpoints subscribed to this module's events",
        singular="webhook endpoint subscribed to this module's events",
        count=count,
        where='webhook_endpoints.event_types — they will stop firing, silently',
    )


def _notification_group(db, name: str) -> OrphanGroup | None:
    if not _table_exists(db, 'notifications'):
        return None
    sql = """
        SELECT count(*) FROM notifications
        WHERE link LIKE :route OR type LIKE :prefix
    """
    count = _scalar_count(db, sql, {'route': f'/{name}/%', 'prefix': f'{name}%'})
    if not count:
        return None
    return OrphanGroup(
        label="notifications pointing at this module's screens",
        singular="notification pointing at this module's screens",
        count=count,
        where='notifications.link — the route is gone after the restart',
    )


def _file_group(name: str) -> OrphanGroup | None:
    """Files under ``<org>/<module>/`` in the local storage backend."""
    from app.config import settings

    if settings.FILE_STORAGE_BACKEND != 'local':
        return OrphanGroup(
            label='stored files',
            count=-1,
            where=f'not counted: the storage backend is '
            f'{settings.FILE_STORAGE_BACKEND!r} — look for keys under <org>/{name}/',
        )
    root = Path(settings.FILE_STORAGE_LOCAL_PATH)
    if not root.is_dir():
        return None
    count = 0
    for org_dir in root.iterdir():
        module_dir = org_dir / name
        if org_dir.is_dir() and module_dir.is_dir():
            count += sum(1 for p in module_dir.rglob('*') if p.is_file())
    if not count:
        return None
    return OrphanGroup(
        label='stored files',
        singular='stored file',
        count=count,
        where=f'{root}/<org>/{name}/ — kept on disk',
    )


def collect_orphans(name: str) -> OrphanReport:
    """Everything an uninstall of *name* would leave behind, counted.

    Never writes. A probe that cannot run — a database that is not
    reachable, a table shaped differently than expected — is logged and
    skipped rather than allowed to abort the uninstall: the report exists
    to inform the decision, and a report that can crash the command it
    precedes would be a worse deal than no report.

    A skipped probe is not an empty answer, though, so it is recorded in
    ``failures`` rather than silently dropped: the caller has to be able
    to say "this could not be checked" instead of reporting that the
    module stored nothing.
    """
    from app.database import SessionLocal

    module_tables, unreadable = _module_tables(name)
    groups: list[OrphanGroup] = []
    failures: list[str] = list(unreadable)
    try:
        with SessionLocal() as db:
            probes = (
                lambda: _own_tables_group(db, module_tables),
                lambda: _enabled_group(db, name),
                lambda: _webhook_group(db, name),
                lambda: _notification_group(db, name),
                lambda: _prefixed_group(
                    db,
                    name,
                    'audit_log',
                    'target_type',
                    'audit journal entries naming this module',
                    'audit journal entry naming this module',
                ),
                lambda: _prefixed_group(
                    db,
                    name,
                    'approval_requests',
                    'target_type',
                    'approval requests naming this module',
                    'approval request naming this module',
                ),
                lambda: _prefixed_group(
                    db,
                    name,
                    'approval_workflows',
                    'target_type',
                    'approval workflows naming this module',
                    'approval workflow naming this module',
                ),
            )
            for probe in probes:
                try:
                    group = probe()
                except SQLAlchemyError as exc:
                    db.rollback()
                    logger.warning('[module-uninstall] orphan probe failed: %s', exc)
                    failures.append(str(exc))
                    continue
                if group is not None:
                    groups.append(group)
            groups.extend(_tagged_core_rows(db, name))
    except SQLAlchemyError as exc:
        logger.warning('[module-uninstall] orphan report unavailable: %s', exc)
        failures.append(str(exc))

    file_group = _file_group(name)
    if file_group is not None:
        groups.append(file_group)
    return OrphanReport(groups=tuple(groups), failures=tuple(failures))
