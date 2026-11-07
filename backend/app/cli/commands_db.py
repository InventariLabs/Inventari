from typing import TYPE_CHECKING
from uuid import UUID

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from app.cli import bootstrap_db, guard_disposable_install
from app.cli._migration_lock import hold_migration_lock
from app.cli._reset_sweep import (
    TERMINATE_OTHER_SESSIONS_PARAMS,
    TERMINATE_OTHER_SESSIONS_SQL,
)

if TYPE_CHECKING:
    from app.core.migration_doctor import ColumnTypeDrift

db_app = typer.Typer(no_args_is_help=True)
console = Console()


@db_app.command()
def reset(
    yes_i_am_sure: bool = typer.Option(
        False, '--yes-i-am-sure', help='Skip confirmation prompt'
    ),
):
    """DROP SCHEMA public CASCADE and rebuild. DESTRUCTIVE!"""
    import os

    from sqlalchemy import create_engine, text

    guard_disposable_install('drops every table in the database')

    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        console.print('[red]DATABASE_URL is not set.[/]')
        raise typer.Exit(code=1)

    if not yes_i_am_sure:
        console.print('[bold yellow]⚠  DESTRUCTIVE OPERATION[/]')
        console.print('This will DROP ALL DATA in the current database.')
        db_name = database_url.rsplit('/', 1)[-1].split('?')[0]
        confirmation = typer.prompt(f'Type the database name to confirm ({db_name})')
        if confirmation != db_name:
            console.print('[red]Confirmation failed. Aborting.[/]')
            raise typer.Exit(code=1)

    engine = create_engine(database_url)
    # The same lock the backend's entrypoint holds while it migrates: a reset
    # that ran beside a migration would drop the schema under it, and the
    # sweep below spares the lock session on the promise that it is waiting,
    # not working (app.cli._migration_lock).
    with hold_migration_lock(), engine.connect() as conn:
        console.print('Terminating other connections...')
        conn.execute(
            text(TERMINATE_OTHER_SESSIONS_SQL), TERMINATE_OTHER_SESSIONS_PARAMS
        )
        conn.execute(text('DROP SCHEMA public CASCADE'))
        conn.execute(text('CREATE SCHEMA public'))
        conn.execute(text('GRANT ALL ON SCHEMA public TO public'))
        conn.commit()

    console.print('[green]✔ Database reset successfully.[/]')
    console.print('Run [bold]manage.py db upgrade[/] to apply migrations.')


@db_app.command()
def seed(
    profile: str = typer.Option(
        'clean_core',
        '--profile',
        '-p',
        help='Seed profile: clean_core, food_home, equipment_wms',
    ),
    organization_id: str | None = typer.Option(
        None,
        '--org',
        help='Organization the profile is applied to. Without it the only '
        'organization is used; a database with none takes the '
        'installation-wide data, and one with several is refused and listed.',
    ),
    insert_only: bool = typer.Option(
        True,
        '--insert-only/--overwrite',
        help='Leave rows that already exist as they are (the default). '
        '--overwrite refreshes their definitions; a name the organization '
        'changed stays protected either way.',
    ),
):
    """Seed system data (storage types, categories, UoM)."""
    bootstrap_db()
    from app.database import SessionLocal
    from app.seed_data import list_seedable_organizations, seed_all

    with SessionLocal() as db:
        organizations = list_seedable_organizations(db)

    org_uuid = _resolve_seed_organization(organization_id, organizations)
    seed_all(profile=profile, organization_id=org_uuid, insert_only=insert_only)

    if org_uuid is None:
        console.print(
            '[green]✔ Installation-wide seed data applied (units of measure).[/]'
        )
        console.print(
            '[yellow]No organization exists yet, so nothing a tenant owns could '
            'be seeded. Create the first admin — `manage.py user create-admin` — '
            'and re-run this command to apply the profile.[/]'
        )
        return

    mode = 'insert-only' if insert_only else 'overwrite'
    console.print(
        f'[green]✔ Seed data applied (profile: {profile}, org: {org_uuid}, '
        f'mode: {mode}).[/]'
    )


def _resolve_seed_organization(
    requested: str | None, organizations: list[tuple[UUID, str]]
) -> UUID | None:
    """The tenant a seed run applies to; ``None`` when there is none to pick.

    A named organization has to exist: an id that names nothing would seed
    nothing, which is the silent no-op this command is being pulled out of.
    Without a name, one organization is unambiguous and several are the
    operator's decision — neither is guessed.
    """
    listed = '\n'.join(f'  {name} — {org_id}' for org_id, name in organizations)

    if requested is not None:
        try:
            wanted = UUID(requested)
        except ValueError:
            console.print(f'[red]✘ --org is not a UUID: {requested}[/]')
            _print_existing(listed)
            raise typer.Exit(code=1) from None

        if not any(org_id == wanted for org_id, _ in organizations):
            console.print(f'[red]✘ No organization has the id {wanted}.[/]')
            _print_existing(listed)
            raise typer.Exit(code=1)
        return wanted

    if len(organizations) > 1:
        console.print(
            '[red]✘ More than one organization exists — name the one to seed '
            'with --org.[/]'
        )
        console.print(f'Organizations on this installation:\n{listed}')
        raise typer.Exit(code=1)

    if not organizations:
        return None

    org_id, name = organizations[0]
    console.print(f'[dim]Using the only organization: {name} — {org_id}[/]')
    return org_id


def _print_existing(listed: str) -> None:
    """Name what could have been chosen instead, or say there is nothing."""
    if listed:
        console.print(f'Organizations on this installation:\n{listed}')
    else:
        console.print('This installation has no organizations yet.')


@db_app.command()
def upgrade(
    revision: str = typer.Argument('head', help='Target revision (default: head)'),
):
    """Apply database migrations (alembic upgrade).

    When upgrading to ``head``, per-module migrations
    (``alembic_version_<module>`` tables) are applied too — otherwise module
    columns added after the core baseline (e.g. the maker settings) stay
    missing and the API 500s on fresh deploys.
    """
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config('alembic.ini')
    command.upgrade(alembic_cfg, revision)
    console.print(f'[green]✔ Migrated to {revision}.[/]')
    if revision == 'head':
        _upgrade_all_modules()


@db_app.command()
def downgrade(
    revision: str = typer.Argument(
        ..., help='Target revision (e.g. -1 or revision hash)'
    ),
):
    """Rollback database migrations (alembic downgrade)."""
    from alembic import command
    from alembic.config import Config

    guard_disposable_install('rolls migrations back and drops what they added')

    alembic_cfg = Config('alembic.ini')
    command.downgrade(alembic_cfg, revision)
    console.print(f'[green]✔ Downgraded to {revision}.[/]')


@db_app.command()
def migrate(message: str = typer.Argument(..., help='Migration message')):
    """Generate new migration (alembic revision --autogenerate)."""
    bootstrap_db()
    from alembic import command
    from alembic.config import Config
    from alembic.script import Script

    alembic_cfg = Config('alembic.ini')
    written = command.revision(alembic_cfg, message=message, autogenerate=True)
    if not isinstance(written, Script):
        console.print(
            '[yellow]No model change found — no migration written. Change a '
            'model first; a data-only migration is written by hand with '
            '`alembic revision -m "<message>"`.[/]'
        )
        return
    console.print(
        f'[green]✔ Migration created: {written.path}[/]\n'
        'Read it before `make db-upgrade`: autogenerate cannot tell a renamed '
        'column from a dropped one.'
    )


def _migration_db_url() -> str:
    """URL for migration-time work — ``MIGRATION_DATABASE_URL`` when set.

    It points straight at Postgres so the session-scoped advisory lock in
    entrypoint.sh does not travel through a transaction-mode pooler.
    """
    import os

    db_url = os.getenv('MIGRATION_DATABASE_URL') or os.getenv('DATABASE_URL')
    if not db_url:
        console.print('[red]DATABASE_URL is not set.[/]')
        raise typer.Exit(code=1)
    return db_url


def _sync_engine():
    from sqlalchemy import create_engine

    return create_engine(
        _migration_db_url().replace('postgresql+asyncpg', 'postgresql')
    )


def _print_unvalidated_constraints(unvalidated: list[tuple[str, str]]) -> None:
    if not unvalidated:
        return
    console.print(
        f'[yellow]![/] {len(unvalidated)} constraint(s) check new writes but not '
        'the rows written before them. Repair those rows, then validate:'
    )
    for table_name, name in unvalidated:
        console.print(f'  ALTER TABLE {table_name} VALIDATE CONSTRAINT {name};')


def _print_column_type_drift(drift: 'list[ColumnTypeDrift]') -> None:
    if not drift:
        return
    console.print(
        f'[yellow]![/] {len(drift)} column(s) in the database differ in type from '
        'what the models declare. A pending migration may be about to fix them; '
        'if this list survives a restart, nothing will:'
    )
    for entry in drift:
        console.print(
            f'  {entry.table}.{entry.column}: database {entry.live_type}, '
            f'models {entry.model_type}'
        )


def _report_rejected_modules() -> set[str]:
    """Name every module discovery rejects, why, and how to take it out.

    The backend starts without a rejected module — the registry logs the
    reason and loads the rest — so a rejection is not a reason to refuse the
    boot. It was one by accident: the column-type check below imported every
    module's models, a package that cannot be imported raised out of the
    doctor, and the entrypoint restarted the container forever while blaming
    the migration state.
    """
    from app.core.module_registry import module_registry
    from app.core.module_tracking import load_module_tracking

    module_registry.discover_modules()
    rejected = module_registry.get_rejected_modules()
    if not rejected:
        return set()
    installed = load_module_tracking()
    for record in rejected:
        console.print(
            f'[yellow]![/] Module [cyan]{record.module_name}[/] is rejected and '
            f'does not load: {escape(record.reason)}',
            soft_wrap=True,
        )
        if record.module_name in installed:
            console.print(
                '  The backend starts without it. Fix the package and upgrade it, '
                f'or take it out: python manage.py module uninstall '
                f'{record.module_name}',
                soft_wrap=True,
            )
        else:
            console.print(
                '  The backend starts without it. Fix it, or remove the directory '
                f'app/modules/{record.module_name}.',
                soft_wrap=True,
            )
    return {record.module_name for record in rejected}


@db_app.command()
def doctor():
    """Check every module's version table against its migration chain.

    Exit 0 when the state is consistent (including an empty database, which is
    what a fresh install looks like), 1 on drift. Runs from entrypoint.sh before
    the migrations, so a broken state produces one readable error instead of a
    restart loop. Constraints still waiting for validation, columns whose type
    differs from the models', and modules discovery rejects are listed too, but
    they never fail the check.
    """
    from sqlalchemy.exc import SQLAlchemyError

    from app.core.migration_doctor import (
        DoctorInfrastructureError,
        column_type_drift,
        diagnose_modules,
        has_drift,
        unvalidated_constraints,
    )

    rejected = _report_rejected_modules()

    try:
        engine = _sync_engine()
    except SQLAlchemyError as exc:
        console.print(f'[yellow]![/] Cannot reach the database: {exc}')
        console.print('Skipping the migration check; the migration itself will report.')
        return

    try:
        diagnoses = diagnose_modules(engine)
        unvalidated = unvalidated_constraints(engine)
        type_drift = column_type_drift(engine, skip=rejected)
    except DoctorInfrastructureError as exc:
        # Fail open: an unreachable database is not drift, and the migration
        # running right after this will fail loudly on its own.
        console.print(f'[yellow]![/] Cannot inspect the database: {exc}')
        console.print('Skipping the migration check; the migration itself will report.')
        return
    finally:
        engine.dispose()

    _print_unvalidated_constraints(unvalidated)
    _print_column_type_drift(type_drift)

    if not diagnoses:
        console.print('[green]✔ No modules with migrations.[/]')
        return

    table = Table(title='Module migration state')
    table.add_column('Module', style='cyan')
    table.add_column('Status')
    table.add_column('DB', style='dim')
    table.add_column('Code head', style='dim')
    table.add_column('Detail')

    status_styles = {
        'ok': 'green',
        'pending': 'yellow',
        'fresh': 'blue',
        'reconcilable': 'yellow',
        'schema_ahead': 'bold red',
        'partial_schema': 'bold red',
        'unknown_revision': 'bold red',
    }
    for diagnosis in diagnoses:
        style = status_styles.get(diagnosis.status, '')
        table.add_row(
            diagnosis.module,
            f'[{style}]{diagnosis.status}[/{style}]' if style else diagnosis.status,
            diagnosis.db_revision_display,
            diagnosis.head_revision_display,
            diagnosis.detail,
        )
    console.print(table)

    if not has_drift(diagnoses):
        console.print('[green]✔ Migration state is consistent.[/]')
        return

    console.print('')
    console.print('[bold red]Migration drift detected.[/] Fix before migrating:')
    for diagnosis in diagnoses:
        if diagnosis.is_drift and diagnosis.fix_command:
            console.print(f'  [cyan]{diagnosis.module}[/]: {diagnosis.fix_command}')
    console.print('')
    console.print('Then re-run [bold]db doctor[/] and restart.')
    raise typer.Exit(code=1)


#: The revision the chain was flattened to before v0.11.0. A database that grew
#: through the previous chain carries a revision id this checkout no longer
#: knows; it is stamped onto this one instead of replaying a chain that no
#: longer exists.
LEGACY_CHAIN_BASELINE = 'baseline_002'

#: The last revision the previous chain reached. Only a database that records
#: it is stamped: an earlier revision can carry the same schema and still miss
#: a data-only one — ``docurl01`` rewrote stored notification links after
#: ``poolcode01`` widened a column, and no schema comparison can see a row.
LEGACY_CHAIN_PREVIOUS_HEAD = 'docvis01'


def _module_chain_changes(gap, pending) -> bool:
    """Whether one ``compare_metadata`` entry is a pending module revision's work.

    A column entry counts when a pending revision does to that very column
    what the gap asks for: adds the one the database lacks, drops the one it
    has spare, alters the one that differs. Altering a column the database
    lost does not bring it back. An index or constraint counts when a pending
    revision names it, or when every column it covers is one a pending
    revision touches. A modification is a list of entries, and counts only as
    a whole.
    """
    for entry in gap if isinstance(gap, list) else [gap]:
        kind = entry[0]
        if kind == 'add_column':
            if (entry[2], entry[3].name) not in pending.added:
                return False
        elif kind == 'remove_column':
            if (entry[2], entry[3].name) not in pending.dropped:
                return False
        elif kind.startswith('modify_'):
            if (entry[2], entry[3]) not in pending.altered:
                return False
        else:
            item = entry[1]
            table = getattr(item, 'table', None)
            covered = [column.name for column in getattr(item, 'columns', [])]
            if getattr(item, 'name', None) in pending.names:
                continue
            if (
                table is None
                or not covered
                or not all(
                    (table.name, column) in pending.columns for column in covered
                )
            ):
                return False
    return True


#: What the core revisions after the baseline remove. A database stamped from
#: the previous chain still carries these, and the upgrade that follows the
#: stamp drops them, so their absence from the models is not a reason to refuse
#: it. Tables, and ``(table, column)`` pairs.
_DROPPED_AFTER_BASELINE_TABLES = {'item_type_definitions'}
_DROPPED_AFTER_BASELINE_COLUMNS = {('items', 'item_type')}


#: The indexes the core revisions after the baseline build on tables the
#: previous chain already had. The models declare them, so a database stamped
#: from the previous chain lacks them until the upgrade that follows the stamp.
_ADDED_AFTER_BASELINE_INDEXES = {
    'ix_items_org_archived_at',
    'uq_storage_locations_org_parent_name',
    'uq_storage_locations_org_root_name',
}


def _added_after_baseline(gap) -> bool:
    """Whether one ``compare_metadata`` entry is an index a later revision builds."""
    entries = gap if isinstance(gap, list) else [gap]
    return all(
        entry[0] == 'add_index' and entry[1].name in _ADDED_AFTER_BASELINE_INDEXES
        for entry in entries
    )


def _dropped_after_baseline(gap) -> bool:
    """Whether one ``compare_metadata`` entry is a removal a later revision makes."""
    entries = gap if isinstance(gap, list) else [gap]
    for entry in entries:
        kind = entry[0]
        if kind == 'remove_column' and (entry[2], entry[3].name) in (
            _DROPPED_AFTER_BASELINE_COLUMNS
        ):
            continue
        if kind == 'remove_index' and (
            entry[1].table.name in _DROPPED_AFTER_BASELINE_TABLES
            or any(
                (entry[1].table.name, column.name) in _DROPPED_AFTER_BASELINE_COLUMNS
                for column in entry[1].columns
            )
        ):
            continue
        if kind == 'remove_table' and entry[1].name in _DROPPED_AFTER_BASELINE_TABLES:
            continue
        return False
    return True


def _unexplained_gaps(gaps: list, pending) -> list:
    """The gaps the baseline answers for: the ones no later revision closes.

    The flattening rebuilt the core chain only. Every module keeps its own
    chain and migrates after the stamp, so a column a module added since the
    previous chain is a revision its chain still has to run, not a sign the
    database is not the one the baseline builds — and refusing it made the
    stamp impossible for any release that brings a module migration. Only
    what those revisions change is set aside: a column the database lost, on
    a module's table as much as on the core's, no chain brings back.
    """
    return [
        gap
        for gap in gaps
        if not _dropped_after_baseline(gap)
        and not _added_after_baseline(gap)
        and not _module_chain_changes(gap, pending)
    ]


@db_app.command(name='stamp-baseline')
def stamp_baseline():
    """Mark a pre-0.11 database as the new baseline, after checking it.

    The chain was rebuilt before the first release: one baseline revision
    replaces every revision that came before it. A database that grew through
    that chain is already at the schema the baseline creates, so replaying it
    is both impossible (its revision ids are gone) and pointless. This writes
    the new revision into ``alembic_version`` — but only for a database that
    records the chain's last revision and whose schema matches the models,
    short of what the module chains still have to change after it. An
    earlier revision can look the same and still miss a data-only one, and a
    schema gap would stay hidden until something reads the missing column.

    Run it once per installation, before the new release's backend starts:
    the entrypoint migrates on boot and cannot get past the revision it does
    not know. ``DEPLOYMENT.md`` has the command in the update procedure.
    """
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    from app.core.autogenerate_scope import load_model_metadata, schema_gaps
    from app.core.migration_doctor import pending_module_changes

    config = Config('alembic.ini')
    known = {
        revision.revision
        for revision in ScriptDirectory.from_config(config).walk_revisions()
    }

    try:
        engine = _sync_engine()
    except SQLAlchemyError as exc:
        console.print(f'[red]Cannot reach the database:[/] {exc}')
        raise typer.Exit(code=1) from exc

    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
            if current in known:
                console.print(
                    f'[green]✔[/] Already on the current chain at [bold]{current}[/] '
                    '— nothing to stamp.'
                )
                return
            if current is None:
                console.print(
                    '[red]No revision is recorded.[/] This looks like an empty '
                    'database: run [bold]manage.py db upgrade[/] instead.'
                )
                raise typer.Exit(code=1)

            if current != LEGACY_CHAIN_PREVIOUS_HEAD:
                console.print(
                    f'[bold red]Refusing to stamp {current}:[/] the supported '
                    f'start is [bold]{LEGACY_CHAIN_PREVIOUS_HEAD}[/], the last '
                    'revision of the previous chain. An earlier one can carry '
                    'the same schema and still miss a data-only revision.'
                )
                console.print(
                    '\nUpgrade the installation to the previous release first, '
                    'then run this again.'
                )
                raise typer.Exit(code=1)

            gaps = _unexplained_gaps(
                schema_gaps(connection, load_model_metadata()),
                pending_module_changes(connection),
            )
    finally:
        engine.dispose()

    if gaps:
        console.print(
            f'[bold red]Refusing to stamp {current}:[/] the schema is not the one '
            'this release expects.'
        )
        for gap in gaps:
            console.print(f'  - {gap}')
        console.print(
            "\nThe database records the previous chain's last revision, but that "
            'chain did not leave this schema. Repair the differences listed '
            'above, then run this again.'
        )
        raise typer.Exit(code=1)

    # Written directly rather than through ``alembic stamp``: the command
    # resolves the revision it finds in the table, and this one deliberately
    # does not exist in this checkout any more. The check above already proved
    # the schema is the one the baseline builds.
    engine = _sync_engine()
    try:
        with engine.begin() as connection:
            connection.execute(text('DELETE FROM alembic_version'))
            connection.execute(
                text('INSERT INTO alembic_version (version_num) VALUES (:revision)'),
                {'revision': LEGACY_CHAIN_BASELINE},
            )
    finally:
        engine.dispose()

    console.print(
        f'[green]✔[/] Stamped {current} as [bold]{LEGACY_CHAIN_BASELINE}[/]. '
        'Run [bold]manage.py db upgrade[/] next (the entrypoint does it on boot).'
    )


@db_app.command(name='stamp-module')
def stamp_module(
    module_name: str = typer.Argument(..., help='Module whose version table to set'),
    revision: str = typer.Argument(..., help='Revision to record (e.g. 001_initial)'),
    yes: bool = typer.Option(False, '--yes', '-y', help='Skip confirmation prompt'),
    force: bool = typer.Option(
        False,
        '--force',
        help="Stamp even if the target revision's tables are missing",
    ),
):
    """Record a module as being at *revision* without running its migrations.

    Refuses unless the tables that revision's chain creates actually exist —
    stamping ahead of the schema hides the missing DDL until the first query
    fails. ``--force`` overrides, for the case where the tables live under a
    different name than the migration created.
    """
    from sqlalchemy import text

    from app.core.migration_doctor import tables_created_through
    from app.core.module_migrations import (
        discover_modules_with_migrations,
        run_module_migrations,
    )

    if module_name not in discover_modules_with_migrations():
        console.print(f'[red]No module with migrations named {module_name!r}.[/]')
        raise typer.Exit(code=1)

    try:
        expected_tables = tables_created_through(module_name, revision)
    except Exception as exc:  # Alembic raises several types for a bad revision
        console.print(f'[red]Cannot resolve revision {revision!r}: {exc}[/]')
        raise typer.Exit(code=1) from exc

    engine = _sync_engine()
    try:
        with engine.connect() as conn:
            missing = sorted(
                table
                for table in expected_tables
                if conn.execute(
                    text('SELECT to_regclass(:name)'), {'name': table}
                ).scalar()
                is None
            )
    finally:
        engine.dispose()

    if missing and force:
        console.print(
            f'[yellow]![/] --force: stamping anyway, though {", ".join(missing)} '
            f'{"is" if len(missing) == 1 else "are"} missing.'
        )
    elif missing:
        console.print(
            f'[red]Refusing to stamp:[/] revision {revision} creates tables that '
            f'do not exist: {", ".join(missing)}'
        )
        console.print(
            'The schema is behind the stamp you asked for. Run '
            '[bold]db upgrade-modules[/] instead, or pass --force if these tables '
            'live elsewhere.'
        )
        raise typer.Exit(code=1)

    if not yes:
        console.print(
            f'Stamping [cyan]{module_name}[/] at [bold]{revision}[/] — '
            f'{len(expected_tables)} table(s) verified present.'
        )
        typer.confirm('Write this to the version table?', abort=True)

    run_module_migrations(
        module_name, 'stamp', db_url=_migration_db_url(), revision=revision
    )
    console.print(f'[green]✔ {module_name} stamped at {revision}.[/]')


@db_app.command(name='upgrade-modules')
def upgrade_modules():
    """Apply per-module Alembic migrations (alembic_version_<module> tables).

    Module tables were originally created by the archived core ``baseline_001``
    migration. After the module-migration isolation, each
    module owns its own migration chain. This command reconciles the two:

    1. For each module whose version table is empty AND whose tables
       already exist in the database (created by the core baseline),
       stamps to ``001_initial`` to skip the now-redundant initial
       migration.
    2. For new modules whose tables do NOT exist in the baseline,
       skips the stamp so the module's own ``001_initial`` migration
       creates them from scratch.
    3. Upgrades every module to ``head`` (applying incremental module
       migrations like ``po_reorder_rules`` that were added after the
       core baseline).
    """
    _upgrade_all_modules()


def _module_rejection_reason(module_name: str) -> str | None:
    """Why discovery refuses this module, or None when it loads.

    Two witnesses, because neither sees every refusal on its own. Discovery
    records the authoritative verdicts — safety violations in code that is
    perfectly importable, manifest mismatches, dependencies that fell away
    transitively — but it only records modules it actually looked at, and a
    migrations directory can outlive its module's package. The import probe
    catches that leftover; the records catch everything the interpreter
    happily accepts. (The import probe alone was the first gate: it stamped
    a safety-rejected module, because forbidden code is ordinary, importable
    Python.)
    """
    from app.core.module_registry import module_registry

    for record in module_registry.get_rejected_modules():
        if record.module_name == module_name:
            return record.reason
    import importlib

    # The package is imported, not the `module` submodule — the same thing
    # module discovery imports. A module that keeps its class in
    # `__init__.py` with no `module.py` loads fine there and must load fine
    # here; a broken `module.py` fails both, because the scaffold's
    # `__init__` imports it transitively.
    try:
        importlib.import_module(f'app.modules.{module_name}')
    except Exception:  # noqa: BLE001 — any import failure is a rejection here
        return 'module import failed'
    return None


def _should_stamp_at_baseline(
    module_tables: set[str], existing_tables: set[str]
) -> bool:
    """Stamp 001_initial only when every module table is already in the DB.

    A community module's tables were never part of the core baseline, so
    stamping over them would mark migrations applied that never ran — the
    tables get created only when the module's own migrations run for real.
    A tableless reading (nothing the module owns was found) keeps the old
    reconcile path: with nothing to reconcile, the stamp is harmless.
    """
    return not module_tables or all(t in existing_tables for t in module_tables)


def _upgrade_all_modules():
    from sqlalchemy import create_engine, inspect, text

    from app.core.architecture_lint._quality_checks import (
        _collect_module_tablenames,
    )
    from app.core.module_migrations import (
        MODULES_ROOT,
        discover_modules_with_migrations,
        run_module_migrations,
    )

    # The rejection verdicts below are discovery's own records; without a
    # scan this process would read an empty registry and gate on nothing.
    bootstrap_db()

    db_url = _migration_db_url()
    sync_url = db_url.replace('postgresql+asyncpg', 'postgresql')
    engine = create_engine(sync_url)
    inspector = inspect(engine)

    for module_name in discover_modules_with_migrations():
        rejection_reason = _module_rejection_reason(module_name)
        if rejection_reason:
            console.print(
                f'[red]✗ {module_name}: rejected by module discovery '
                f'({rejection_reason}) — not stamped, not migrated. Fix '
                f'the module and restart; the version row must not claim '
                f'work that never happened.[/]'
            )
            continue
        version_table = f'alembic_version_{module_name}'
        existing_tables = set(inspector.get_table_names())
        version_table_exists = version_table in existing_tables

        needs_stamp = True
        if version_table_exists:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(f'SELECT version_num FROM {version_table}')  # noqa: S608 — table name from internal Alembic config, not user input
                ).fetchall()
            needs_stamp = len(rows) == 0

        stamped = False
        if needs_stamp:
            # Only stamp at 001_initial when the module's tables already
            # exist (baseline reconciliation). For new modules whose tables
            # were never part of the baseline, skip the stamp so migrations
            # run from scratch and actually create the tables.
            module_tables = _collect_module_tablenames(MODULES_ROOT / module_name)
            if not _should_stamp_at_baseline(module_tables, existing_tables):
                console.print(
                    f'  {module_name}: tables not in baseline '
                    f'— running migrations from scratch'
                )
            else:
                run_module_migrations(
                    module_name,
                    'stamp',
                    db_url=db_url,
                    revision='001_initial',
                )
                stamped = True

        run_module_migrations(module_name, 'upgrade', db_url=db_url)

        if stamped:
            action = 'stamped + upgraded'
        elif needs_stamp:
            action = 'migrated from scratch'
        else:
            action = 'upgraded'
        console.print(f'[green]✔ {module_name}: {action}[/]')

    engine.dispose()
    console.print('[bold green]✔ All module migrations applied.[/]')


def reservation_disagreements(session) -> list:
    """The groups whose promises exceed what the records put on the shelf.

    ``stock_quants_from_records`` is the register's own answer for one
    (product, shelf, batch, owner) group: ``quantity`` is what the live
    records hold there, ``reserved_quantity`` is what the reservation rows
    of that group promise, summed per the grain they name. Both numbers sit
    in the view, so this reads the records and the rows; the quant table,
    whose running total was the other opinion this command used to compare,
    is gone.

    Nothing here can report the old ``over`` any more: there is no cached
    total left to stand higher than the rows. What is left is what the old
    command called ``short`` — a shelf holding less than documents already
    claim on it, including a promise with no record under it at all, which
    the view reports as quantity 0.
    """
    from sqlalchemy import select

    from app.models.stock_quants_from_records import stock_quants_from_records

    stmt = (
        select(
            stock_quants_from_records.c.organization_id,
            stock_quants_from_records.c.product_template_id,
            stock_quants_from_records.c.storage_location_id,
            stock_quants_from_records.c.quantity,
            stock_quants_from_records.c.reserved_quantity,
        )
        .where(
            stock_quants_from_records.c.reserved_quantity
            > stock_quants_from_records.c.quantity
        )
        .order_by(stock_quants_from_records.c.organization_id)
    )
    return list(session.execute(stmt).all())


@db_app.command(name='check-reservations')
def check_reservations() -> None:
    """Compare what the records put on a shelf with what documents promise there.

    The reservation rows say who holds what of a group; the live records say
    how much of it the shelf carries. When a document claims more than the
    records carry, the next operation would take stock somebody is already
    promised, and no screen shows it — this command does.

    Exit 0 when every shelf carries what its promises add up to, 1 when one
    does not, listing the groups:

      short — the promises exceed the records: stock somebody is holding
              can be taken by the next operation, or nothing stands under
              the promise any more
    """
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import Session

    try:
        engine = _sync_engine()
    except SQLAlchemyError as exc:
        console.print(f'[red]Cannot reach the database: {exc}[/]')
        raise typer.Exit(code=1) from exc

    with Session(engine) as session:
        rows = reservation_disagreements(session)
    engine.dispose()

    if not rows:
        console.print('[green]✔ Every shelf carries what its reservations promise.[/]')
        return

    console.print(
        f'[bold red]{len(rows)} group(s) promise more than the shelf carries.[/]'
    )
    for row in rows:
        console.print(
            f'  [short] org {row.organization_id} '
            f'product {row.product_template_id} '
            f'location {row.storage_location_id}: '
            f'on_hand={row.quantity}, reservations={row.reserved_quantity}'
        )
    raise typer.Exit(code=1)
