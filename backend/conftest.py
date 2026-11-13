"""
Configuration and fixtures for Inventari application tests.

According to pytest documentation, we use importlib import mode for new projects.
Source: https://docs.pytest.org/en/stable/explanation/goodpractices.html
"""

import asyncio
import importlib
import importlib.util
import os
import sys
import tempfile
import uuid
from collections.abc import AsyncGenerator, Generator
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.db_isolation import (
    controller_run_id,
    drop_run_databases,
    run_scoped_db_name,
)

# IMPORTANT: Set TESTING mode BEFORE importing app/main to skip module discovery there
os.environ['TESTING'] = 'true'
settings.TESTING = True
# TESTING with DEBUG off is refused at import (config.check_testing_mode_is_
# deliberate). The suite is exactly the case that combination exists for, and
# xdist workers inherit this environment, so they have to carry the
# acknowledgement — otherwise every worker dies importing app.config.
os.environ['TESTING_ACK_UNSAFE'] = 'true'
settings.TESTING_ACK_UNSAFE = True


@pytest.fixture(autouse=True)
def _force_testing_mode():
    import app.config as config

    os.environ['TESTING'] = 'true'
    settings.TESTING = True
    config.settings.TESTING = True
    yield
    os.environ['TESTING'] = 'true'
    settings.TESTING = True
    config.settings.TESTING = True


@pytest.fixture(autouse=True)
def _db_facade_still_forwards():
    """Fail the test that left a real attribute on ``app.core.db_facade``.

    The facade forwards its session factories and engines to ``app.database``
    through a module ``__getattr__``. ``monkeypatch.setattr(db_facade, ...)``
    restores by *setting* the value it read, so after the test the facade
    holds a frozen copy — usually the engine of an earlier ``client``
    lifespan, whose pool belongs to a closed event loop. Every later test on
    that worker that patches ``app.database`` then reaches the frozen engine
    and fails with "attached to a different loop", far from the cause.
    Patch ``app.database`` instead; the facade reads it live.
    """
    yield
    frozen = hygiene.unfreeze_db_facade()
    if frozen:
        pytest.fail(
            f'db_facade no longer forwards {frozen} to app.database — patch '
            'app.database, not the facade',
            pytrace=False,
        )


@pytest.fixture
def stub_dns(monkeypatch):
    """Answer DNS lookups from a table instead of the network.

    SSRF validation resolves every outbound URL before the request goes
    out, which otherwise makes these tests depend on a working resolver
    *and* on whatever address the real name happens to hold today — the
    pinned request URL is built from that answer.

    Unmapped names resolve to a globally routable address. It used to be a
    TEST-NET-3 one (RFC 5737) — belonging to nobody was the appeal — and that
    worked only because the guard's list of private ranges was short of the
    documentation pools. The guard now refuses everything that is not globally
    routable, so a stand-in for a public name has to be one. Nothing leaves the
    process either way; the transport is stubbed in every test that uses this.

    Use ``resolves()`` to pin a specific address and ``fails()`` to simulate
    NXDOMAIN.

    A bare service name (``db``, ``redis``, ``localhost``) is not the outside
    world: unless the table names it, it goes to the real resolver, so a test
    that also talks to the database keeps its connection.
    """
    import socket

    table: dict[str, str | None] = {}
    default_ip = '93.184.216.34'
    real_getaddrinfo = socket.getaddrinfo

    def _getaddrinfo(host, port, *args, **kwargs):
        if host not in table and isinstance(host, str) and '.' not in host:
            return real_getaddrinfo(host, port, *args, **kwargs)
        ip = table.get(host, default_ip)
        if ip is None:
            raise socket.gaierror(socket.EAI_NONAME, 'Name or service not known')
        if ':' in ip:
            return [(socket.AF_INET6, socket.SOCK_STREAM, 6, '', (ip, port or 0, 0, 0))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port or 0))]

    monkeypatch.setattr(socket, 'getaddrinfo', _getaddrinfo)

    class _StubbedDns:
        default = default_ip

        def resolves(self, host: str, ip: str) -> None:
            table[host] = ip

        def fails(self, host: str) -> None:
            table[host] = None

    return _StubbedDns()


from app.core.module_registry import module_registry

# Discover modules before importing app.main so dynamic routers are included.
if not module_registry.get_all():
    module_registry.discover_modules()

# Build dynamic list of available module names for test fixtures.
_ALL_MODULE_NAMES: list[str] = ['core'] + [
    m.metadata.name for m in module_registry.get_all() if m.metadata.name != 'core'
]

# Ensure all module models are imported so SQLAlchemy can resolve cross-module
# relationships (e.g. Item.stock_take_items -> StockTakeItem, Item.source_document -> Document).
# By the module's package (discovery imports app.modules.<name>), not by the
# module object's class: a define_module() module's class lives in
# app.core.define_module, so that path imported nothing for most modules. A
# module without models is skipped; one whose models fail to import fails here.
for _mod in module_registry.get_all():
    _models = f'app.modules.{_mod.metadata.name}.models'
    if importlib.util.find_spec(_models) is not None:
        importlib.import_module(_models)

from app import database as app_database
from app.core._event_bus import event_bus
from app.core.contracts import ModuleModelBase
from app.core.contributions import QuotaProvider, contribution_registry
from app.core.limiter import limiter
from app.database import Base, dispatch_committed_events, get_async_db, get_db
from app.main import app
from app.models.ai_usage_log import (
    AIUsageLog,  # noqa: F401 — ensure table is in Base.metadata
)
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.role import (  # noqa: F401 — ensure tables are in Base.metadata
    Role,
    UserRole,
)
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.items._date_meta import merge_legacy_date_into_meta
from app.services.token_service import create_access_token, get_password_hash
from tests import _db_hygiene as hygiene

# ``create_all`` builds the tables and nothing else. The other objects the
# application reads — the quants as the records tell them, and the guard that
# refuses a reservation past its grain at commit — are created by the baseline
# migration's own statements, so the suite runs what ships: a test that builds
# a hold no record stands behind fails the way production would.
_baseline_migration = importlib.import_module(
    'migrations.versions.baseline_002_full_schema'
)
# The triggers that keep the ledger's totals are a later revision's statements,
# run the same way, and so is the revision that replaced their function since.
_ledger_totals_migration = importlib.import_module(
    'migrations.versions.ledgertotals01_create_stock_ledger_totals'
)
_ledger_totals_key_order_migration = importlib.import_module(
    'migrations.versions.ledgertotals03_take_removed_totals_in_key_order'
)

# Lazy imports for module-specific models to avoid import order issues
# These are imported on-demand by fixtures to prevent duplicate SQLAlchemy model registration
# when modules have co-located tests

# We use PostgreSQL test database for tests (same as production)
# This eliminates compatibility issues with JSONB and other PostgreSQL-specific features
DB_USER = os.getenv('DB_USER', 'storage_user')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'storage_pass')
DB_HOST = os.getenv('DB_HOST', 'db')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME_BASE = os.getenv('DB_TEST_NAME', 'inventari_test')

# Support for parallel testing via pytest-xdist
# Each worker gets its own database and redis streams to avoid race conditions;
# the streams wear the run id as the databases do, so two suites on one Redis
# never read each other's events.
# The name also wears this run's id: two suites sharing one database server
# never share worker-database names, so a sweep dropping another (finished)
# run's databases cannot delete a live run's databases under it — which is
# how a suite loses a worker database mid-flight and reports "ERROR at
# setup — database does not exist" while the passed count stays green.
worker_id = os.environ.get('PYTEST_XDIST_WORKER')
# The controller mints the id; a worker reads the one it inherited.
TEST_RUN_ID = controller_run_id(mint=not worker_id)
if worker_id:
    DB_NAME = run_scoped_db_name(DB_NAME_BASE, worker_id)
    # Isolate Redis for parallel tests
    settings.REDIS_STREAM_NAME = f'inventari_stream_{TEST_RUN_ID}_{worker_id}'
    settings.REDIS_TASKS_STREAM_NAME = f'inventari_tasks_{TEST_RUN_ID}_{worker_id}'
else:
    DB_NAME = run_scoped_db_name(DB_NAME_BASE, None)
    settings.REDIS_STREAM_NAME = f'inventari_stream_{TEST_RUN_ID}'
    settings.REDIS_TASKS_STREAM_NAME = f'inventari_tasks_{TEST_RUN_ID}'

# app.main was imported above, so the event-bus singleton already read the
# default stream name in its constructor; point it at this run's stream.
event_bus._stream_name = settings.REDIS_STREAM_NAME

# Force settings.DATABASE_URL to use the direct worker database (bypass PgBouncer for tests)
TEST_DATABASE_URL = (
    f'postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
)
settings.DATABASE_URL = TEST_DATABASE_URL

# app.database built its sync engine from settings.DATABASE_URL when it was
# imported — above, before the redirect — so SessionLocal kept pointing at the
# database DATABASE_URL names: the stack's development database locally, an
# empty one in CI. Code that opens its own SessionLocal wrote there, and the
# tests that read back through it passed only where that database happened to
# have a schema. configure() rebinds the sessionmaker in place, so every module
# that imported SessionLocal before this line follows it to the worker database.
app_database.engine.dispose()
app_database.engine = create_engine(TEST_DATABASE_URL, echo=False)
app_database.SessionLocal.configure(bind=app_database.engine)

TEST_ASYNC_DATABASE_URL = TEST_DATABASE_URL.replace(
    'postgresql://', 'postgresql+asyncpg://', 1
)


def create_test_db_if_not_exists():
    """Ensure the test database exists by connecting to 'postgres' first."""
    # Connection string to default 'postgres' database
    sys_url = f'postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/postgres'
    sys_engine = create_engine(sys_url, isolation_level='AUTOCOMMIT')

    with sys_engine.connect() as conn:
        # Check if database exists
        result = conn.execute(
            text(f"SELECT 1 FROM pg_database WHERE datname='{DB_NAME}'")
        )
        if not result.scalar():
            print(f'\n[xdist] Creating worker database: {DB_NAME}')
            conn.execute(text(f'CREATE DATABASE {DB_NAME}'))

    sys_engine.dispose()


# ---------------------------------------------------------------------------
# Guardian: the shared app/modules tree is read-only for the whole test run.
#
# Every xdist worker reads this tree, so a test that installs a module package
# into it opens a window in which a fake module is a real one for every other
# reader: the migration doctor enumerates it, the upgrade stamp guard counts
# it, the roundtrip test imports the listing at collection time — before this
# test has even started. Five readers were counted doing exactly that.
#
# The decision this encodes: installation in tests goes to a tree of the
# test's own, never to ``app/modules`` — see ``fixture_module`` in
# ``tests/integration`` for the redirect of writers and readers alike.
#
# This is the net for the test that forgets. It refuses the write AT THE
# MOMENT of the write — an audit hook, not a before/after comparison of the
# listing — because the writer this class of test historically copies
# installed its package and removed it again in teardown, and a change that
# undoes itself is invisible to any comparison of listings. The hook raises
# inside the writing test, so the failure lands where the write happened.
# A comparison of listings is kept nowhere: every way the listing can change
# goes through one of the audited operations below.
#
# Bytecode caches are exempt: they are derived data no reader of the tree
# enumerates (the readers list module directories, manifests and sources).
# ---------------------------------------------------------------------------

# Which positional arguments of each audited event actually MUTATE the tree.
# Sources are reads: copyfile/copytree read their source, symlink only points
# at its target — the doctor-drift tests build their scenarios by symlinking
# real modules into a chain of their own, and scaffold tests copy
# ``example_widgets`` out to a tree of their own; both are legal.
# ``shutil.move`` and ``os.rename``/``os.replace`` remove the source, so both
# ends mutate.
_AUDITED_WRITE_EVENTS = {
    'os.mkdir': (0,),
    'os.rename': (0, 1),
    'os.replace': (0, 1),
    'os.remove': (0,),
    'os.rmdir': (0,),
    'os.link': (1,),
    'os.symlink': (1,),
    'shutil.copyfile': (1,),
    'shutil.copytree': (1,),
    'shutil.rmtree': (0,),
    'shutil.move': (0, 1),
}
_OPEN_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
# Trailing separator so a sibling directory (app/modules-evil) never matches.
_MODULES_ROOT = str(Path(__file__).resolve().parent / 'app' / 'modules') + os.sep


def _lands_in_modules_tree(raw) -> bool:
    """Whether a path argument lands inside the shared tree.

    Pure string work on purpose: this runs inside an audit hook on the hot
    path of every file open in the run, so no stat, no resolve, no I/O.
    """
    if isinstance(raw, (int, type(None))):
        return False
    if isinstance(raw, bytes):
        raw = raw.decode(sys.getfilesystemencoding(), 'replace')
    absolute = os.path.abspath(os.fspath(raw))
    below_root = absolute.startswith(_MODULES_ROOT)
    return below_root and '__pycache__' not in absolute.split(os.sep)


def _refuse_shared_modules_write(event: str, path: str) -> None:
    pytest.fail(
        f'a test wrote into the shared app/modules tree ({event}: {path}). '
        'The tree is read-only for the whole run: every xdist worker reads '
        'it, so an installed package is a real module for every other '
        'reader while it exists - even if the write is undone again in '
        "teardown. Install into a tree of the test's own instead; "
        'fixture_module in tests/integration shows the redirect every '
        'installing test must use.',
    )


def _guard_shared_modules_tree(event: str, args: tuple) -> None:
    if event == 'open':
        path, mode, flags = args
        if isinstance(path, int):
            return
        if (flags or 0) & _OPEN_WRITE_FLAGS or (
            mode and any(letter in mode for letter in 'wax+')
        ):
            if _lands_in_modules_tree(path):
                _refuse_shared_modules_write(event, path)
        return
    if event not in _AUDITED_WRITE_EVENTS:
        return
    for index in _AUDITED_WRITE_EVENTS[event]:
        if index >= len(args):
            continue
        arg = args[index]
        if not isinstance(arg, (str, bytes, os.PathLike)):
            continue
        if _lands_in_modules_tree(arg):
            _refuse_shared_modules_write(event, arg)


sys.addaudithook(_guard_shared_modules_tree)


@pytest.fixture(scope='session', autouse=True)
def disable_rate_limiting():
    """Globally disable rate limiting for tests."""
    limiter.enabled = False
    yield
    # No need to revert as session ends


@pytest.fixture(scope='session', autouse=True)
def init_file_storage():
    """Initialize FileStorageService with a temp directory for tests."""
    from app.core.file_storage.schemas import StorageConfigSchema
    from app.core.file_storage.service import FileStorageService

    with tempfile.TemporaryDirectory() as tmpdir:
        config = StorageConfigSchema(backend='local', local_path=tmpdir)
        FileStorageService.initialize(config)
        yield


@pytest.fixture(scope='session', autouse=True)
def close_unclosed_event_loops():
    """Close event loops that test helpers create but do not own explicitly."""
    policy = asyncio.get_event_loop_policy()
    original_new_event_loop = policy.new_event_loop
    tracked_loops: list[asyncio.AbstractEventLoop] = []

    def new_event_loop():
        loop = original_new_event_loop()
        tracked_loops.append(loop)
        return loop

    policy.new_event_loop = new_event_loop
    try:
        yield
    finally:
        policy.new_event_loop = original_new_event_loop
        for loop in tracked_loops:
            if loop.is_closed() or loop.is_running():
                continue
            loop.close()


# The worker's one sync engine. The async fixtures cannot request the session
# ``engine`` fixture (see _ensure_worker_db), but they clean the database
# through the same pooled connection the sync tests do: a pooled connection
# keeps the plans of the hygiene queries, a new asyncpg connection per test
# would plan them again.
_worker_engine_instance = None


def _worker_engine():
    global _worker_engine_instance
    if _worker_engine_instance is None:
        _worker_engine_instance = create_engine(TEST_DATABASE_URL, echo=False)
    return _worker_engine_instance


def _dispose_worker_engine() -> None:
    global _worker_engine_instance
    if _worker_engine_instance is not None:
        _worker_engine_instance.dispose()
        _worker_engine_instance = None


@pytest.fixture(scope='session')
def engine():
    """Creates database engine for tests."""
    yield _worker_engine()
    _dispose_worker_engine()


def _seed_system_data(session: Session) -> None:
    """Seed the installation-wide data the snapshot can hold: UoM + categories.

    Storage types are owned by an organization since, and no
       organization exists when the snapshot is built — ``seed_org_storage_types``
       gives each test organization its own set instead.

       Food categories are seeded because the integration suite was written
       against the food vertical. Production boot seeds UoM only; the profile
       seed runs per organization at onboarding.
    """
    from app._seed_uom import seed_uom
    from app.seed_profiles._food_home_categories import seed_food_categories

    seed_uom(session)
    seed_food_categories(session)
    session.commit()


def seed_org_storage_types(session: Session, organization_id) -> None:
    """Re-export of the shared helper (see ``app.core.testing``)."""
    from app.core.testing import seed_org_storage_types as _seed

    _seed(session, organization_id)


def _build_seed_snapshot(engine) -> dict[str, int]:
    """Seed once per worker and snapshot the rows into a `seed_cache` schema.

    Seeding through the seeder functions costs ~150ms per test: ~65 lookups,
    ~65 INSERTs and a commit, paid by the ~4100 tests that touch the DB.
    Replaying the snapshot is four `INSERT ... SELECT` statements producing
    byte-identical rows, so each test still starts from a freshly seeded
    database — it just gets there ~10x cheaper. Returns the row count of each
    snapshotted table, which is what an untouched copy is recognised by.
    """
    session = sessionmaker(bind=engine)()
    try:
        _seed_system_data(session)
    finally:
        session.close()

    with engine.connect() as conn:
        conn.execute(text('DROP SCHEMA IF EXISTS seed_cache CASCADE'))
        conn.execute(text('CREATE SCHEMA seed_cache'))
        for table in hygiene.SEED_TABLES:
            conn.execute(
                text(f'CREATE TABLE seed_cache.{table} AS TABLE public.{table}')
            )
        counts = {
            table: conn.execute(
                text(f'SELECT count(*) FROM seed_cache.{table}')
            ).scalar_one()
            for table in hygiene.SEED_TABLES
        }
        conn.execute(text(f'TRUNCATE {", ".join(hygiene.SEED_TABLES)} CASCADE'))
        conn.commit()
    return counts


_worker_db_ready = False


def _provision_worker_db(engine) -> None:
    """Drop and rebuild this worker's schema, once per worker process.

    Every test on a worker -- sync through ``setup_test_db``, async through
    ``real_async_db_session`` -- has to find the same thing: a database whose
    tables match the current models and whose seed snapshot is fresh. Both
    entry points used to provision it separately, and only the sync one
    dropped the schema first: the async one ran ``create_all`` on whatever
    was there, which adds missing tables but never a missing column. So a
    worker whose first test happened to be async kept last week's schema,
    and which test came first depended on the collection order -- under a
    random order that was 150 errors, under the default order none.

    Idempotent and cheap after the first call.
    """
    global _worker_db_ready
    if _worker_db_ready:
        return
    hygiene.reset()
    create_test_db_if_not_exists()
    # Brutal force: drop schema public and recreate it to wipe everything
    # cleanly -- tables, columns, enum types.
    with engine.connect() as conn:
        conn.execute(text('DROP SCHEMA public CASCADE;'))
        conn.execute(text('CREATE SCHEMA public;'))
        conn.commit()
    Base.metadata.create_all(bind=engine)
    # A community module's tables are on a metadata of their own (and not in
    # the core's chain), so nothing above built them.
    ModuleModelBase.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        conn.execute(text(_baseline_migration.VIEW_SQL))
        for statement in _baseline_migration.GUARD_SQL:
            conn.execute(text(statement))
        for statement in _ledger_totals_migration.TRIGGER_SQL:
            conn.execute(text(statement))
        conn.execute(text(_ledger_totals_key_order_migration.FUNCTION_SQL))
        conn.commit()
    seed_rows = _build_seed_snapshot(engine)
    with engine.connect() as conn:
        present = {
            row[0]
            for row in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        }
        hygiene.install_dirty_probe(conn, present, seed_rows)
        conn.commit()
    with engine.connect() as conn:
        # The leftover-DDL guard compares every teardown against what the
        # schema looked like the day the worker was born -- nothing added
        # to it after this point is legitimate.
        hygiene.snapshot_ddl(conn)
    _worker_db_ready = True


def _ensure_worker_db() -> None:
    """Provision the worker database for fixtures that cannot use setup_test_db.

    The async fixtures deliberately do not depend on that fixture
    (pytest-asyncio deadlocks when an async fixture requests a session-scoped
    sync one), so they call this instead. Same provisioning, own engine.
    """
    if _worker_db_ready:
        return
    bootstrap_engine = create_engine(TEST_DATABASE_URL)
    try:
        _provision_worker_db(bootstrap_engine)
    finally:
        bootstrap_engine.dispose()


@pytest.fixture(scope='session')
def setup_test_db(engine):
    """Provisions the worker database for the sync fixtures (see _provision_worker_db)."""
    _provision_worker_db(engine)
    return engine


@pytest.fixture(scope='function')
def db_session(engine, setup_test_db) -> Generator[Session]:
    """Creates new database session for each test."""
    # Tables are already created by setup_test_db fixture

    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_local()
    from app.core.events import event_bus

    started_subscriptions: set[tuple[str, tuple]] = set()

    try:
        # Put back the system-data snapshot built once per worker (see
        # _build_seed_snapshot) if the previous test changed it, and clear
        # whatever else is left over (an async test, a test that never took
        # this fixture) — usually nothing.
        hygiene.restore_pristine(session)

        # Wire module services/interceptors without running full application startup hooks.
        from app.core.container import service_container
        from app.core.context import ModuleContext
        from app.core.module_registry import module_registry

        for module in module_registry.get_all():
            module.register_services(service_container)
            module._wire_interceptors()
        session.commit()

        # Call on_startup for modules that need event subscriptions in tests.
        # Only specific modules — NOT webhooks (subscribes to ALL events, causes duplicates).
        ctx = ModuleContext(event_bus=event_bus)
        before = hygiene.subscriptions(event_bus)
        for module in module_registry.get_all():
            if module.metadata.name == 'purchase_orders':
                module.on_startup(ctx)
        started_subscriptions = hygiene.subscriptions(event_bus) - before

        yield session
    finally:
        # Only what this start added comes off (see release_subscriptions).
        hygiene.release_subscriptions(event_bus, started_subscriptions)
        session.close()
        with engine.connect() as conn:
            trans = conn.begin()
            try:
                # Leftover DDL comes off BEFORE the clear: the clear is a
                # DELETE now, and a trigger left by this very test would
                # detonate on it — the guard would never get to speak.
                # Dropped first, the clear runs on the database the test
                # should have left behind, and the accusation below names
                # the owner.
                dropped_ddl = hygiene.drop_leftover_ddl(conn)
                hygiene.restore_pristine(conn)
                trans.commit()
            except Exception:
                trans.rollback()
                raise
            if dropped_ddl:
                raise RuntimeError(hygiene.left_ddl_message(dropped_ddl))


@pytest.fixture(scope='session')
def async_engine_fixture():
    """Session-scoped async engine for real asyncpg in default client."""
    _engine = create_async_engine(
        TEST_ASYNC_DATABASE_URL, echo=False, poolclass=NullPool
    )
    yield _engine
    try:
        loop = asyncio.get_event_loop()
        if not loop.is_closed():
            loop.run_until_complete(_engine.dispose())
    except RuntimeError:
        pass


@pytest.fixture(scope='function')
def client(db_session: Session, async_engine_fixture) -> Generator[TestClient]:
    """Creates FastAPI test client with REAL AsyncSession (asyncpg)."""

    def override_get_db():
        try:
            db_session.commit()
        except Exception:  # noqa: BLE001 — fixture hygiene: whatever the commit hit, start clean
            db_session.rollback()
        try:
            yield db_session
        finally:
            try:
                db_session.commit()
            except Exception:  # noqa: BLE001 — fixture hygiene: whatever the commit hit, start clean
                db_session.rollback()

    _async_session_factory = async_sessionmaker(
        async_engine_fixture, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_async_db():
        # Mirror override_get_db: commit the test's pending sync-session writes
        # before the async request runs. require_module is async-only now,
        # so fully-async endpoint stacks never trigger the sync override — without
        # this commit the endpoint's SELECT ... FOR UPDATE deadlocks against rows
        # locked by db_session's uncommitted seed data.
        try:
            db_session.commit()
        except Exception:  # noqa: BLE001 — fixture hygiene: whatever the commit hit, start clean
            db_session.rollback()
        async with _async_session_factory() as session:
            try:
                yield session
                await session.commit()
                await dispatch_committed_events(session)
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_async_db] = override_get_async_db

    # The lifespan warms its own async pool with a round trip to the database
    # (and closes that connection again at shutdown): ~30 ms, paid by every test
    # that takes this fixture, for a pool these tests never use — the overrides
    # above hand every endpoint a session of the fixture's own.
    with (
        patch('app._lifespan._warm_up_async_engine', _skip_warm_up),
        TestClient(app) as test_client,
    ):
        yield test_client

    app.dependency_overrides.clear()


async def _skip_warm_up(async_engine, logger) -> None:
    return None


# One async engine for every test on the worker. Its pool is NullPool, so no
# connection outlives the test (and the event loop) that opened it; the engine
# itself holds nothing a loop owns. A new engine per test paid the dialect's
# first-connect round trips again every time.
_async_engine_instance = None


def _worker_async_engine():
    global _async_engine_instance
    if _async_engine_instance is None:
        _async_engine_instance = create_async_engine(
            TEST_ASYNC_DATABASE_URL, echo=False, poolclass=NullPool
        )
    return _async_engine_instance


@pytest.fixture
async def real_async_db_session() -> AsyncGenerator[AsyncSession]:
    """Real AsyncSession connected to test DB via asyncpg.

    Does NOT depend on setup_test_db — pytest-asyncio 1.x deadlocks when
    an async fixture requests a session-scoped sync fixture — so it
    provisions the database itself via _ensure_worker_db().

    Restores the pristine database at setup: async test bodies (or the seeders
    they call) may COMMIT through run_sync sessions, which the teardown
    rollback cannot undo — without it, mutated seed rows leak into later async
    tests on the same xdist worker. The restore and the leftover-DDL check go
    through the worker's pooled sync connection, not a fresh asyncpg one.
    """
    _ensure_worker_db()
    with _worker_engine().begin() as conn:
        hygiene.restore_pristine(conn)
    session_factory = async_sessionmaker(
        _worker_async_engine(), class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
    # The same leftover-DDL guard the sync teardown runs: an async test
    # commits through run_sync sessions the rollback cannot undo, so its DDL
    # would survive this fixture untouched — and the first receipt race on
    # this very fixture is exactly the kind of test that could one day leave
    # a trigger behind.
    with _worker_engine().begin() as conn:
        dropped = hygiene.drop_leftover_ddl(conn)
    if dropped:
        raise RuntimeError(hygiene.left_ddl_message(dropped))


@pytest.fixture
async def real_async_client(db_session: Session) -> AsyncGenerator[AsyncClient]:
    """AsyncClient with REAL AsyncSession (asyncpg), not the sync proxy.

    Engine is created inside the fixture to share the test's event loop.
    """
    engine = create_async_engine(
        TEST_ASYNC_DATABASE_URL, echo=False, poolclass=NullPool
    )
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    def override_get_db():
        yield db_session

    async def override_get_async_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
                await dispatch_committed_events(session)
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_async_db] = override_get_async_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url='http://test'
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture
def test_household(db_session: Session) -> Organization:
    """Creates test organization with all discovered modules enabled."""
    organization = Organization(
        name='Test Organization',
        enabled_modules=list(_ALL_MODULE_NAMES),
    )
    db_session.add(organization)
    db_session.flush()
    seed_org_storage_types(db_session, organization.id)
    db_session.commit()
    db_session.refresh(organization)
    return organization


@pytest.fixture
def test_user(db_session: Session, test_household: Organization) -> User:
    """Creates test user."""
    user = User(
        email='test@example.com',
        hashed_password=get_password_hash('testpassword123'),
        full_name='Test User',
        organization_id=test_household.id,
        role='admin',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_user2(db_session: Session, test_household: Organization) -> User:
    """Creates second test user."""
    user = User(
        email='test2@example.com',
        hashed_password=get_password_hash('testpassword123'),
        full_name='Test User 2',
        organization_id=test_household.id,
        role='user',
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_storage_type(db_session: Session) -> StorageType:
    """Creates test storage type."""
    storage_type = StorageType(name='Freezer', type_code='FREEZER', icon='Snowflake')
    db_session.add(storage_type)
    db_session.commit()
    db_session.refresh(storage_type)
    return storage_type


@pytest.fixture
def test_storage_type_fridge(db_session: Session) -> StorageType:
    """Creates test storage type - fridge."""
    storage_type = StorageType(name='Fridge', type_code='FRIDGE', icon='Refrigerator')
    db_session.add(storage_type)
    db_session.commit()
    db_session.refresh(storage_type)
    return storage_type


@pytest.fixture
def test_storage_location(
    db_session: Session, test_user: User, test_storage_type: StorageType
) -> StorageLocation:
    """Creates test storage location."""
    storage = StorageLocation(
        organization_id=test_user.organization_id,
        created_by=test_user.id,
        storage_type_id=test_storage_type.id,
        name='Kitchen Freezer',
        description='Main Freezer',
        location_details='Kitchen',
    )
    db_session.add(storage)
    db_session.commit()
    db_session.refresh(storage)
    return storage


@pytest.fixture
def test_category(db_session: Session) -> Category:
    """Creates test category."""
    category = Category(name='Pork', icon='🥩', sort_order=1)
    db_session.add(category)
    db_session.commit()
    db_session.refresh(category)
    return category


@pytest.fixture
def test_item(
    db_session: Session, test_storage_location: StorageLocation, test_category: Category
) -> Item:
    """Creates test item."""
    item = Item(
        organization_id=test_storage_location.organization_id,
        storage_location_id=test_storage_location.id,
        category_id=test_category.id,
        name='Pork Loin',
        brand='Good Brand',
        quantity=2,
        expiry_date=date.today() + timedelta(days=30),
        shelf_location='Shelf 1',
    )
    item.meta_data = merge_legacy_date_into_meta(
        item.meta_data, 'freeze_date', date.today()
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


@pytest.fixture
def test_items_batch(
    db_session: Session, test_storage_location: StorageLocation, test_category: Category
) -> list[Item]:
    """Creates batch of test items."""
    items = []
    for i in range(5):
        item = Item(
            organization_id=test_storage_location.organization_id,
            storage_location_id=test_storage_location.id,
            category_id=test_category.id,
            name=f'Product {i + 1}',
            brand=f'Brand {i + 1}',
            quantity=i + 1,
            expiry_date=date.today() + timedelta(days=10 + i * 5),
            shelf_location=f'Shelf {i + 1}',
        )
        item.meta_data = merge_legacy_date_into_meta(
            item.meta_data, 'freeze_date', date.today()
        )
        db_session.add(item)
        items.append(item)

    db_session.commit()
    for item in items:
        db_session.refresh(item)
    return items


@pytest.fixture
def test_stock_take(
    db_session: Session,
    test_user: User,
    test_storage_location: StorageLocation,
    test_items_batch: list[Item],
):
    """Creates test stock take."""
    # Lazy import to avoid import order issues with module-specific tests
    from app.modules.stock_takes.models import StockTake, StockTakeItem, StockTakeStatus

    stock_take = StockTake(
        user_id=test_user.id,
        organization_id=test_user.organization_id,
        storage_location_id=test_storage_location.id,
        name='Test Stock Take',
        description='Test stock take',
        status=StockTakeStatus.IN_PROGRESS,
    )
    db_session.add(stock_take)
    db_session.flush()

    # Add stock take items
    for item in test_items_batch:
        stock_take_item = StockTakeItem(
            stock_take_id=stock_take.id,
            item_id=item.id,
            item_name=item.name,
            item_brand=item.brand,
            uom_id=item.uom_id,
            system_quantity=item.quantity,
            location_in_storage=item.shelf_location,
        )
        db_session.add(stock_take_item)

    db_session.commit()
    db_session.refresh(stock_take)
    return stock_take


@pytest.fixture
def auth_headers(test_user: User) -> dict:
    """Returns authorization headers with JWT token."""
    access_token = create_access_token(data={'sub': str(test_user.id)})
    return {'Authorization': f'Bearer {access_token}'}


@pytest.fixture
def auth_headers_user2(test_user2: User) -> dict:
    """Returns authorization headers for second user."""
    access_token = create_access_token(data={'sub': str(test_user2.id)})
    return {'Authorization': f'Bearer {access_token}'}


@pytest.fixture
def temp_upload_dir():
    """Creates temporary directory for uploaded files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


class _AtItemLimit(QuotaProvider):
    """A quota provider that holds the organizations a test names at their
    item limit.

    The registry ships the ``QuotaProvider`` protocol and nothing that
    implements it, so ``check_quota`` answered "allowed" for everyone and
    the gate could only be measured by patching ``check_quota`` itself —
    which patches the very code under test. A test registers this one
    instead: the gate then walks its own loop over real providers, and the
    refusal arrives as the ``QuotaExceededError`` production would raise.
    """

    def __init__(self) -> None:
        self._held: set[uuid.UUID] = set()

    def hold(self, organization_id: uuid.UUID) -> None:
        """Put *organization_id* at its item limit for this test."""
        self._held.add(organization_id)

    async def check_organization_limit(
        self, organization_id: uuid.UUID, limit_type: str, db: Any
    ) -> bool:
        """Refuse the item limit only — other limits stay this provider's
        business only when a test says so, and ``db`` is never queried: the
        fixture holds by id, so a caller may pass a stub session."""
        if limit_type != 'max_items':
            return True
        return organization_id not in self._held

    async def get_limit_value(
        self, organization_id: uuid.UUID, limit_type: str, db: Any
    ) -> int | float | None:
        """No number to display: the fixture holds an organization outright
        rather than capping it at a count, so it has no ceiling to report."""
        return None


@pytest.fixture
def put_on_item_limit():
    """Put an organization at its item limit for the duration of one test.

    Returns the callable that names the organization to hold. The limit is
    enforced by a provider registered with the contribution registry — the
    extension point ``check_quota`` already walks — so the gate under test
    runs its own code rather than a patched copy of it. The provider is
    unregistered at teardown: the registry is a process-wide singleton
    shared by every test in the worker.
    """
    provider = _AtItemLimit()
    contribution_registry.register('quota_providers', provider)
    try:
        yield provider.hold
    finally:
        # ``get`` hands back the registry's own list for a known point, so
        # removing from it is removing from the registry.
        contribution_registry.get('quota_providers').remove(provider)


# --- Async test fixtures (mirror sync fixtures, AsyncSession-based) ---


@pytest.fixture
async def async_test_household(
    real_async_db_session: AsyncSession,
) -> Organization:
    """Creates test organization in async session with all discovered modules enabled."""
    organization = Organization(
        name='Test Organization',
        enabled_modules=list(_ALL_MODULE_NAMES),
    )
    real_async_db_session.add(organization)
    await real_async_db_session.flush()
    await real_async_db_session.run_sync(
        lambda session: seed_org_storage_types(session, organization.id)
    )
    await real_async_db_session.refresh(organization)
    return organization


@pytest.fixture
async def async_test_user(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
) -> User:
    """Creates test user in async session (unique email to avoid conflicts)."""
    user = User(
        email=f'async_test_{uuid.uuid4().hex[:8]}@example.com',
        hashed_password=get_password_hash('testpassword123'),
        full_name='Test User',
        organization_id=async_test_household.id,
        role='admin',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def async_test_user2(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
) -> User:
    """Creates second test user in async session (unique email to avoid conflicts)."""
    user = User(
        email=f'async_test2_{uuid.uuid4().hex[:8]}@example.com',
        hashed_password=get_password_hash('testpassword123'),
        full_name='Test User 2',
        organization_id=async_test_household.id,
        role='user',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(user)
    return user


@pytest.fixture
async def async_test_storage_type(
    real_async_db_session: AsyncSession,
) -> StorageType:
    """Creates test storage type in async session."""
    storage_type = StorageType(name='Freezer', type_code='FREEZER', icon='Snowflake')
    real_async_db_session.add(storage_type)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(storage_type)
    return storage_type


@pytest.fixture
async def async_test_storage_location(
    real_async_db_session: AsyncSession,
    async_test_user: User,
    async_test_storage_type: StorageType,
) -> StorageLocation:
    """Creates test storage location in async session."""
    storage = StorageLocation(
        organization_id=async_test_user.organization_id,
        created_by=async_test_user.id,
        storage_type_id=async_test_storage_type.id,
        name='Kitchen Freezer',
        description='Main Freezer',
        location_details='Kitchen',
    )
    real_async_db_session.add(storage)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(storage)
    return storage


@pytest.fixture
async def async_test_category(
    real_async_db_session: AsyncSession,
) -> Category:
    """Creates test category in async session."""
    category = Category(name='Pork', icon='Pork', sort_order=1)
    real_async_db_session.add(category)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(category)
    return category


@pytest.fixture
async def async_test_item(
    real_async_db_session: AsyncSession,
    async_test_storage_location: StorageLocation,
    async_test_category: Category,
) -> Item:
    """Creates test item in async session."""
    item = Item(
        organization_id=async_test_storage_location.organization_id,
        storage_location_id=async_test_storage_location.id,
        category_id=async_test_category.id,
        name='Pork Loin',
        brand='Good Brand',
        quantity=2,
        expiry_date=date.today() + timedelta(days=30),
        shelf_location='Shelf 1',
    )
    item.meta_data = merge_legacy_date_into_meta(
        item.meta_data, 'freeze_date', date.today()
    )
    real_async_db_session.add(item)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(item)
    return item


@pytest.fixture
async def async_test_items_batch(
    real_async_db_session: AsyncSession,
    async_test_storage_location: StorageLocation,
    async_test_category: Category,
) -> list[Item]:
    """Creates batch of test items in async session."""
    items = []
    for i in range(5):
        item = Item(
            organization_id=async_test_storage_location.organization_id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name=f'Product {i + 1}',
            brand=f'Brand {i + 1}',
            quantity=i + 1,
            expiry_date=date.today() + timedelta(days=10 + i * 5),
            shelf_location=f'Shelf {i + 1}',
        )
        item.meta_data = merge_legacy_date_into_meta(
            item.meta_data, 'freeze_date', date.today()
        )
        real_async_db_session.add(item)
        items.append(item)

    await real_async_db_session.flush()
    for item in items:
        await real_async_db_session.refresh(item)
    return items


def pytest_sessionfinish(session, exitstatus):
    """Drop the databases this run created; their names carry the run id.

    Only the controller does this (workers are still needed while they run,
    and each worker's own session finishes before the controller's). A run
    killed outright leaves orphans; sweeping those is the recovery recipe's
    business, and since the names carry run ids the sweep has to name the
    run it means — a glob across runs is exactly the mistake this split
    exists to make harmless.
    """
    if os.environ.get('PYTEST_XDIST_WORKER'):
        _dispose_worker_engine()
        return
    dropped = drop_run_databases(TEST_DATABASE_URL, DB_NAME_BASE, TEST_RUN_ID)
    if dropped:
        print(
            f'\n[test-db] dropped {len(dropped)} database(s) '
            f'this run created: {", ".join(sorted(dropped))}'
        )


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Say out loud when the run carries errors, not only failures.

    An ERROR at setup is not a failed test, so a reader filtering the
    summary for 'failed' — or a pipe that ate the exit code — pushes a tree
    with tests that never ran. The count is already in the line; this banner
    exists so the line cannot be skimmed.
    """
    errors = terminalreporter.stats.get('error', [])
    if errors:
        terminalreporter.write_sep(
            '=', 'ERRORS ARE NOT FAILURES — READ THEM', red=True, bold=True
        )
        terminalreporter.write_line(
            f'{len(errors)} error(s) at setup/teardown. Tests reported as '
            'errors DID NOT RUN. Find "ERROR at" above before trusting the '
            'passed count.'
        )


# Register the module-test plugin so @pytest.mark.module('name') auto-fixtures work.
pytest_plugins = ['app.core.module_test_plugin']


# Pytest configuration
def pytest_configure(config):
    """Pytest configuration."""
    config.addinivalue_line('markers', 'unit: unit tests')
    config.addinivalue_line('markers', 'integration: integration tests')
    config.addinivalue_line('markers', 'slow: slow tests')
    config.addinivalue_line(
        'markers', 'async_db: tests that exercise real AsyncSession + asyncpg'
    )
    config.addinivalue_line(
        'markers',
        "module: marks tests as module-specific (use @pytest.mark.module('name') to auto-create fixtures)",
    )
