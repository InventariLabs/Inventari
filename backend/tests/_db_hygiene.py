"""Keeping a worker's database fit for the next test.

Every xdist worker owns one database that its tests share one after another,
so each test has to find the database as the previous one found it: the
schema ``create_all`` built, the system-data snapshot (units of measure and
categories) in place, every other table empty. Two things keep that true —
``restore_pristine`` before and after a test that wrote, and
``drop_leftover_ddl`` after one that may have changed the schema.

Both are asked on every test, so both are written to answer "nothing to do"
in a single round trip:

* the schema is compared by a fingerprint computed in the catalogs (a few
  sums of hashes, ~2 ms) and only a mismatch pays for the full comparison
  that names the offender;
* the tables that hold rows are found by a plpgsql function generated once
  per worker. A plpgsql function keeps its query plans for the life of the
  connection, so asking about ~100 tables costs well under a millisecond;
  the same question sent as one ``UNION ALL`` is planned afresh each time
  (~10 ms);
* the system-data tables are left alone while they are exactly what the
  snapshot put there — the same row count, every row written by the
  transaction that replayed the snapshot (``xmin``). An insert, update or
  delete by a test shows in one of the two.
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.contracts import ModuleModelBase
from app.database import Base

# System data every test starts from, in foreign-key order (uoms -> uom_categories).
# All of them have UUID primary keys generated in Python, so there is no sequence
# to resync when the rows are copied instead of re-inserted.
SEED_TABLES = ('uom_categories', 'uoms', 'categories')

# One statement per table: asyncpg runs the extended query protocol, which
# rejects several commands in a single prepared statement.
REPLAY_SEED_STATEMENTS = tuple(
    f'INSERT INTO public.{table} SELECT * FROM seed_cache.{table}'
    for table in SEED_TABLES
)

_DIRTY_FUNCTION = 'public.inventari_dirty_tables'

# What create_all built for this worker, per kind of DDL a test can add
# (tables, columns, indexes, functions, triggers) and the catalog fingerprint
# of all of them. Snapshotted once per worker by ``snapshot_ddl``.
_ddl_baseline: dict | None = None

# The transaction that last replayed the snapshot: every system-data row it
# wrote carries its id in ``xmin``.
_seed_xid: str = ''


# Whether the role may switch off constraint triggers for the length of a
# transaction (``session_replication_role``, superuser only). Decided once per
# worker by ``install_dirty_probe``.
_may_skip_constraints = False


def reset() -> None:
    """Forget a previous worker database (called before provisioning a new one)."""
    global _ddl_baseline, _seed_xid, _may_skip_constraints
    _ddl_baseline = None
    _seed_xid = ''
    _may_skip_constraints = False


def clearable_names(present: set[str]) -> tuple[str, ...]:
    """The modelled tables that exist in this database, the core's first.

    A community module's tables live on ``ModuleModelBase.metadata`` by design,
    so a test that writes to one has to be cleaned up after like any other.
    ``Base.metadata`` can also name a table this database never got (a model
    imported after ``create_all`` ran), and naming one in the function or in the
    clearing statement fails the whole statement — hence the intersection.
    """
    return tuple(
        table.name
        for metadata in (Base.metadata, ModuleModelBase.metadata)
        for table in metadata.sorted_tables
        if table.name in present
    )


def clear_statement(non_empty: list[str]) -> str:
    """One statement that empties every table holding rows.

    ``TRUNCATE`` was the obvious way and cost ~120 ms a test: it gives each
    table a new file, and the commit waits for those files to reach the disk.
    Deleting the rows instead costs ~10 ms — the tables hold single-digit row
    counts, this is a test database, and nothing here is big enough for a
    sequential scan to notice.

    The deletes go in one statement because the schema has cycles
    (``organizations.created_by`` names a user, ``users.organization_id``
    names an organization), so no order of separate ``DELETE`` statements
    satisfies the foreign keys. Data-modifying CTEs all run to completion on
    one snapshot and the constraint triggers fire once at the end, by which
    time both tables are empty — which is what ``TRUNCATE ... CASCADE`` gave
    for free.
    """
    clauses = ', '.join(
        f'd{i} AS (DELETE FROM {name})' for i, name in enumerate(non_empty)
    )
    return f'WITH {clauses} SELECT 1'


# ---------------------------------------------------------------------------
# Schema: what a test must not leave behind
# ---------------------------------------------------------------------------

# Order-independent sums of hashes over everything ``drop_leftover_ddl`` can
# name: relations (tables, indexes, sequences), their live columns, triggers
# and functions. The object ids go into the hash, so dropping a table and
# creating another of the same name still shows.
_FINGERPRINT_SQL = text(
    """
    SELECT
      (SELECT coalesce(sum(hashtextextended(c.oid::text || c.relname || c.relkind::text, 0)), 0)
         FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace),
      (SELECT coalesce(sum(hashtextextended(a.attrelid::text || ':' || a.attnum || a.attname, 0)), 0)
         FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
        WHERE c.relnamespace = 'public'::regnamespace
          AND a.attnum > 0 AND NOT a.attisdropped),
      (SELECT coalesce(sum(hashtextextended(t.oid::text || t.tgname, 0)), 0)
         FROM pg_trigger t WHERE NOT t.tgisinternal),
      (SELECT coalesce(sum(hashtextextended(p.oid::text || p.proname, 0)), 0)
         FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace)
    """
)


def _fingerprint(conn) -> tuple:
    return tuple(conn.execute(_FINGERPRINT_SQL).one())


def _live_triggers(conn) -> set[tuple[str, str]]:
    return {
        (r[0], r[1])
        for r in conn.execute(
            text(
                'SELECT tgrelid::regclass::text, tgname FROM pg_trigger '
                'WHERE NOT tgisinternal'
            )
        )
    }


def snapshot_ddl(conn) -> None:
    """Record what ``create_all`` built, per kind of DDL a test can add.

    One query per kind, once per worker.
    """
    global _ddl_baseline
    _ddl_baseline = {
        'tables': {
            r[0]
            for r in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        },
        'columns': {
            (r[0], r[1])
            for r in conn.execute(
                text(
                    'SELECT table_name, column_name FROM '
                    "information_schema.columns WHERE table_schema = 'public'"
                )
            )
        },
        'indexes': {
            r[0]
            for r in conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
            )
        },
        'functions': {
            (r[0], r[1])
            for r in conn.execute(
                text(
                    'SELECT proname, pg_get_function_identity_arguments(p.oid) '
                    'FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid '
                    "WHERE n.nspname = 'public'"
                )
            )
        },
        # Triggers the worker was born with (the hold guard's) stay; the
        # guard used to drop every trigger it found, which no trigger
        # installed at provisioning could survive.
        'triggers': _live_triggers(conn),
        'fingerprint': _fingerprint(conn),
    }


def drop_leftover_ddl(conn) -> list[str]:
    """Compare the live schema with the worker's DDL baseline, drop the
    difference, and name it for the caller to raise at the owning test.

    A trigger, a table, an index, a column, a function — any of them
    outlives the transaction that made it, and since teardown deletes rows
    instead of truncating, a left-behind trigger also detonates on the next
    test's DELETE. The baseline is what ``create_all`` built for this
    worker (see ``snapshot_ddl``); everything outside it is a test's doing.
    Each kind is probed separately — a guard written for the example in a
    review used to watch exactly one of the five.

    The drops run inside the caller's transaction, tables first so
    CASCADE takes a leftover table's own indexes and triggers with it; the
    accusation is returned rather than raised, so the caller can commit
    the drops first and blame the test afterwards.
    """
    if _ddl_baseline is None:
        snapshot_ddl(conn)
        return []
    if _fingerprint(conn) == _ddl_baseline['fingerprint']:
        return []

    names: list[str] = []
    current_tables = {
        r[0]
        for r in conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
    }
    for table in sorted(current_tables - _ddl_baseline['tables']):
        conn.execute(text(f'DROP TABLE "{table}" CASCADE'))
        names.append(f'table {table}')

    for table, name in sorted(_live_triggers(conn) - _ddl_baseline['triggers']):
        conn.execute(text(f'DROP TRIGGER "{name}" ON {table}'))
        names.append(f'trigger {table} → {name}')

    current_indexes = {
        r[0]
        for r in conn.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
        )
    }
    for index in sorted(current_indexes - _ddl_baseline['indexes']):
        conn.execute(text(f'DROP INDEX IF EXISTS "{index}"'))
        names.append(f'index {index}')

    current_columns = {
        (r[0], r[1])
        for r in conn.execute(
            text(
                'SELECT table_name, column_name FROM information_schema.columns '
                "WHERE table_schema = 'public'"
            )
        )
    }
    for table, column in sorted(current_columns - _ddl_baseline['columns']):
        conn.execute(text(f'ALTER TABLE "{table}" DROP COLUMN "{column}"'))
        names.append(f'column {table}.{column}')

    current_functions = {
        (r[0], r[1])
        for r in conn.execute(
            text(
                'SELECT proname, pg_get_function_identity_arguments(p.oid) '
                'FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid '
                "WHERE n.nspname = 'public'"
            )
        )
    }
    for name, args in sorted(current_functions - _ddl_baseline['functions']):
        conn.execute(text(f'DROP FUNCTION "{name}"({args})'))
        names.append(f'function {name}({args})')

    return names


def left_ddl_message(names: list[str]) -> str:
    return (
        'this test left DDL behind — it outlives the transaction and poisons '
        f'every test after it: {"; ".join(names)}. The teardown dropped it, '
        'so the failure lands here instead of a hundred tests later.'
    )


# ---------------------------------------------------------------------------
# Data: what a test must not leave behind
# ---------------------------------------------------------------------------


def install_dirty_probe(conn, present: set[str], seed_rows: dict[str, int]) -> None:
    """Generate ``inventari_dirty_tables(seed_xid)`` for this worker's tables.

    It returns the names of the tables that are not as the snapshot left them:
    a system-data table whose row count or row-writing transaction differs from
    the snapshot's, any other table that holds a row. Must run before
    ``snapshot_ddl`` so the function is part of the baseline.
    """
    global _may_skip_constraints
    _may_skip_constraints = bool(
        conn.execute(
            text('SELECT rolsuper FROM pg_roles WHERE rolname = current_user')
        ).scalar()
    )
    checks = []
    for name in clearable_names(present):
        if name in seed_rows:
            checks.append(
                f'IF (SELECT count(*) FROM {name}) <> {seed_rows[name]} '
                f'OR EXISTS (SELECT 1 FROM {name} WHERE xmin::text <> seed_xid) '
                f"THEN r := r || '{name}'::text; END IF;"
            )
        else:
            checks.append(
                f"IF EXISTS (SELECT 1 FROM {name}) THEN r := r || '{name}'::text; "
                'END IF;'
            )
    conn.execute(
        text(
            f'CREATE FUNCTION {_DIRTY_FUNCTION}(seed_xid text) RETURNS text[] '
            "LANGUAGE plpgsql AS $fn$ DECLARE r text[] := '{}'; BEGIN "
            + ' '.join(checks)
            + ' RETURN r; END $fn$'
        )
    )


def _clear(conn, names: list[str]) -> None:
    """Empty *names*: plain deletes where the role may switch constraints off.

    Every row deleted from a referenced table makes Postgres look for referencing
    rows in each table that points at it, and most of the schema points at
    ``organizations``. With ``session_replication_role = replica`` for the
    transaction those checks are skipped; they are not needed, because every
    table that holds a row is in *names* and the whole set goes. Without the
    privilege ``clear_statement`` does it in one statement the checks can
    follow.
    """
    if not _may_skip_constraints:
        conn.execute(text(clear_statement(names)))
        return
    deletes = '; '.join(f'DELETE FROM {name}' for name in names)
    conn.execute(
        text(
            'SET LOCAL session_replication_role = replica; '
            f'{deletes}; '
            'SET LOCAL session_replication_role = DEFAULT'
        )
    )


def dirty_tables(conn) -> list[str]:
    """The tables that are not as the snapshot left them, as ``restore_pristine`` sees them."""
    return list(
        conn.execute(
            text(f'SELECT {_DIRTY_FUNCTION}(:xid)'), {'xid': _seed_xid}
        ).scalar()
    )


def may_skip_constraints() -> bool:
    """Whether the role may switch constraint triggers off for a transaction."""
    return _may_skip_constraints


def restore_pristine(conn) -> bool:
    """Bring the data back to what the snapshot holds. True if anything was dirty.

    The caller commits. System data that is exactly as replayed stays where it
    is; if any of it changed, all of it is deleted with the rest and replayed
    again, because the three tables reference one another.
    """
    global _seed_xid
    dirty = dirty_tables(conn)
    if not dirty:
        return False
    names = set(dirty)
    replay = bool(names & set(SEED_TABLES))
    if replay:
        names |= set(SEED_TABLES)
    _clear(conn, sorted(names))
    if replay:
        for statement in REPLAY_SEED_STATEMENTS:
            conn.execute(text(statement))
        _seed_xid = conn.execute(
            text(f'SELECT xmin::text FROM public.{SEED_TABLES[0]} LIMIT 1')
        ).scalar_one()
    return True


# ---------------------------------------------------------------------------
# The database facade: what a test must not leave frozen
# ---------------------------------------------------------------------------


def unfreeze_db_facade() -> list[str]:
    """Take off ``app.core.db_facade`` the names a test left set on it.

    The facade forwards its session factories and engines to ``app.database``
    through a module ``__getattr__``, so a test that points ``app.database``
    at its own engine reaches it through the facade too. A name set on the
    facade itself shadows the forwarding for every later test on the worker.
    Returns the names it took off.
    """
    from app.core import db_facade

    frozen = [
        name
        for name in db_facade.__all__
        if name in vars(db_facade) and name not in ('AsyncSession', 'Base')
    ]
    for name in frozen:
        delattr(db_facade, name)
    return frozen


# ---------------------------------------------------------------------------
# Event bus: what a test must not leave subscribed
# ---------------------------------------------------------------------------


def subscriptions(bus) -> set[tuple[str, tuple]]:
    """Every (event, listener entry) on *bus* — what a start can be diffed against."""
    return {
        (event, entry) for event, entries in bus._listeners.items() for entry in entries
    }


def release_subscriptions(bus, started: set[tuple[str, tuple]]) -> None:
    """Take *started* off the bus, and only that.

    The bus is shared by every test on the worker, and a module's
    ``on_startup`` subscribes again each time it runs: left in place, the 900th
    test on a worker ran the order recalculation 900 times per completed
    receipt. A module first imported during the test subscribes once and must
    stay subscribed, which is why the removal is a difference and not a reset.
    """
    for event in {event for event, _ in started}:
        bus._listeners[event] = [
            entry
            for entry in bus._listeners.get(event, [])
            if (event, entry) not in started
        ]
