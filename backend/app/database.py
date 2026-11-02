import sqlite3
from collections.abc import AsyncGenerator
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings

# Configure engine based on database type
connect_args = {}
poolclass = None

if 'sqlite' in settings.DATABASE_URL:
    # Register Decimal adapters for SQLite
    sqlite3.register_adapter(Decimal, lambda d: str(d))
    sqlite3.register_converter('DECIMAL', lambda v: Decimal(v.decode()))

    connect_args = {'check_same_thread': False, 'detect_types': sqlite3.PARSE_DECLTYPES}
    poolclass = StaticPool
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args=connect_args,
        poolclass=poolclass,
        echo=settings.SQL_ECHO,
    )
else:
    # PostgreSQL and others.
    # Dev: connects directly to Postgres (no PgBouncer) — SQLAlchemy pool only.
    # Prod: sits behind PgBouncer (transaction pooling); app keeps per-worker
    #   pools sized to stay within the backend's DEFAULT_POOL_SIZE budget.
    #   Pool math per gunicorn worker: sync pool 20+10=30 conn, async pool
    #   10+10=20 conn (see init_async_engine below) → 50 conn per worker.
    #   Total demand = WEB_CONCURRENCY × 50 × replicas; it must stay below
    #   PgBouncer's MAX_CLIENT_CONN and leave headroom under Postgres
    #   max_connections (PgBouncer DEFAULT_POOL_SIZE caps the server side).
    #   Prod (4x gunicorn, 1 replica): 4×(30+20)=200 client conn → PgBouncer
    #   DEFAULT_POOL_SIZE=30 → PG max=50. See docs/SCALING.md before adding
    #   a second replica.
    engine = create_engine(
        settings.DATABASE_URL,
        echo=settings.SQL_ECHO,
        pool_size=20,
        max_overflow=10,
        pool_timeout=10,
        pool_pre_ping=True,
        pool_recycle=300,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _build_async_url(sync_url: str) -> str:
    if sync_url.startswith('postgresql://'):
        return sync_url.replace('postgresql://', 'postgresql+asyncpg://', 1)
    raise RuntimeError(
        f'Async engine only supports PostgreSQL (postgresql://). Got: {sync_url[:40]}...'
    )


# Lazy-initialized async engine — created inside lifespan to bind to the correct event loop.
# Module-level creation would attach pool connections to the import-time loop (wrong loop).
async_engine = None
AsyncSessionLocal = None


def init_async_engine() -> None:
    """Create async engine and session factory. Call once during lifespan startup."""
    global async_engine, AsyncSessionLocal
    async_engine = create_async_engine(
        _build_async_url(settings.DATABASE_URL),
        echo=settings.SQL_ECHO,
        pool_size=10,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=300,
        pool_pre_ping=True,
        connect_args={
            'prepared_statement_cache_size': 0,
        },
    )
    AsyncSessionLocal = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )


# ── Sync session (kept for backward compatibility) ──────────────────────

# Products Database (OFF)
products_engine = None
ProductsSessionLocal = None

if settings.PRODUCTS_DATABASE_URL:
    products_engine = create_engine(
        settings.PRODUCTS_DATABASE_URL,
        echo=settings.SQL_ECHO,
        pool_size=3,
        max_overflow=4,
        pool_pre_ping=True,
        pool_recycle=300,
    )
    ProductsSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=products_engine
    )


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    except SQLAlchemyError:
        db.rollback()
        raise
    finally:
        db.close()


async def dispatch_committed_events(session: AsyncSession) -> None:
    """Hand the events the request wrote to the outbox to the bus, after the commit.

    ``emit_transactional`` rides the request's transaction; production's relay
    publishes the committed row, so this is a no-op there. Under TESTING the
    event is buffered on the session and only this call dispatches it.

    The work a service deferred with ``after_commit`` runs here too, and what
    it wrote (a stored notification beside the push announcing it) is
    committed after it.
    """
    from app.core.db_utils import run_after_commit
    from app.core.events import event_bus

    await event_bus.flush_pending(session)
    if await run_after_commit(session):
        await session.commit()


async def get_async_db() -> AsyncGenerator[AsyncSession]:
    """Request-scoped async session that commits when the endpoint returns.

    Inject it as ``Depends(get_async_db, scope='function')``. Without that
    scope FastAPI defaults a dependency with ``yield`` to ``'request'``, which
    unwinds *after* the response has been written to the socket — so the
    ``COMMIT`` below runs once the client already holds the response. A caller
    that uses an id it just received (create a list, then add an item to it)
    then reads a snapshot that predates the INSERT and gets a 404 for a row it
    was just handed. It is timing-dependent: invisible when a commit takes
    microseconds, routine when the server is busy and durability is on.

    ``scope='function'`` ends the dependency after the path operation function
    and before the response is sent, which is what makes a 2xx mean the write
    is committed. A stream that needs to query while the response is being
    written must not lean on this dependency at all — it borrows a fresh
    ``AsyncSessionLocal`` per tick, so the pooled connection and the
    transaction do not outlive the query.
    """
    if AsyncSessionLocal is None:
        raise RuntimeError(
            'Async engine not initialized. Call init_async_engine() first.'
        )
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
            await dispatch_committed_events(session)
        except SQLAlchemyError:
            await session.rollback()
            raise
