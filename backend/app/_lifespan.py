"""FastAPI lifespan context manager.

Replaces the deprecated ``@app.on_event`` handlers. Owns startup/shutdown
of async resources (DB engine, EventBus, TaskScheduler, NotificationHub,
TokenBlacklist, cache) and module lifecycle hooks.
"""

import asyncio
from contextlib import asynccontextmanager
from logging import Logger
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

if TYPE_CHECKING:
    from fastapi import FastAPI


def _get_logger() -> Logger:
    from app.core.logging import get_logger

    return get_logger('app')


async def _warm_up_async_engine(async_engine, logger: Logger) -> None:
    """Open one connection on the current loop to replace stale pool ones."""
    if async_engine is None:
        return
    from sqlalchemy import text

    try:
        async with async_engine.connect() as conn:
            await asyncio.wait_for(conn.execute(text('SELECT 1')), timeout=10)
    except (TimeoutError, OSError) as exc:
        logger.warning('[Startup] DB warmup failed: %s', exc)


async def _connect_redis_services(
    logger: Logger, settings, event_bus, notification_hub, task_scheduler
) -> asyncio.Task | None:
    """Connect the three Redis-backed services. Each one is optional.

    Returns the NotificationHub listener task (or ``None``), which shutdown
    has to cancel before the connection closes under it.
    """
    logger.info('[Startup] Connecting EventBus to Redis...')
    try:
        await asyncio.wait_for(event_bus.connect(settings.REDIS_URL), timeout=5)
        await event_bus.start_listener()
        logger.info('[Startup] EventBus connected.')
    except Exception as exc:  # noqa: BLE001 — Redis is optional
        logger.warning('[Startup] EventBus Redis skipped: %s', exc)

    logger.info('[Startup] Connecting TaskScheduler to Redis...')
    try:
        await asyncio.wait_for(task_scheduler.connect(settings.REDIS_URL), timeout=5)
        logger.info('[Startup] TaskScheduler connected.')
    except Exception as exc:  # noqa: BLE001 — Redis is optional
        logger.warning('[Startup] TaskScheduler Redis skipped: %s', exc)

    hub_task: asyncio.Task | None = None
    logger.info('[Startup] Connecting NotificationHub to Redis...')
    try:
        await asyncio.wait_for(notification_hub.connect_redis(), timeout=5)
        hub_task = asyncio.create_task(notification_hub.listen_redis())
        logger.info('[Startup] NotificationHub connected.')
    except Exception as exc:  # noqa: BLE001 — Redis is optional
        logger.warning('[Startup] NotificationHub Redis skipped: %s', exc)
    return hub_task


async def _connect_critical_redis(logger: Logger, settings, token_blacklist) -> bool:
    """Point the token blacklist at the dedicated noeviction instance.

    Returns ``False`` when that instance is unavailable, so the caller can fall
    back to the main one — an allkeys-lru eviction there could drop revoked
    tokens, which fails open.
    """
    try:
        import redis.asyncio as aioredis

        critical_redis = aioredis.from_url(
            settings.REDIS_CRITICAL_URL, decode_responses=True
        )
        await asyncio.wait_for(critical_redis.ping(), timeout=5)
        token_blacklist.set_redis(critical_redis)
        logger.info('[Startup] TokenBlacklist connected to critical Redis.')
        return True
    except Exception as exc:  # noqa: BLE001 — fall back to main instance
        logger.warning(
            '[Startup] Critical Redis unavailable (%s) — '
            'TokenBlacklist using main Redis.',
            exc,
        )
        return False


async def _wire_token_blacklist_and_cache(logger: Logger, settings, event_bus) -> None:
    """Give the blacklist and the cache their Redis connection, if there is one."""
    from app.core.token_blacklist import token_blacklist

    if event_bus.redis is None:
        logger.warning(
            '[Startup] Redis unavailable – TokenBlacklist running in fail-open mode.'
        )
        return

    connected_to_critical = False
    if settings.REDIS_CRITICAL_URL:
        connected_to_critical = await _connect_critical_redis(
            logger, settings, token_blacklist
        )
    if not connected_to_critical:
        token_blacklist.set_redis(event_bus.redis)
        if not settings.REDIS_CRITICAL_URL:
            logger.info('[Startup] TokenBlacklist connected to Redis.')

    from app.core.cache import set_cache_redis

    set_cache_redis(event_bus.redis)
    logger.info('[Startup] Cache connected to Redis.')


async def _seed_and_bootstrap(logger: Logger, settings) -> None:
    """Seed system data, then backfill org short_ids and promote the superuser.

    The bootstrap runs BEFORE module init so the superuser exists before any
    module startup hook fires. It lives here rather than in the cloud module so
    self-hosted instances get it too.
    """
    from app.seed_data import seed_all_async

    logger.info('[Startup] Seeding data...')
    try:
        await seed_all_async()
        logger.info('[Startup] Seed complete.')
    except SQLAlchemyError as e:
        logger.error(f'Failed to seed data: {e}')
        if settings.STRICT_STARTUP:
            raise

    logger.info('[Startup] Running startup bootstrap...')
    try:
        from app.services.bootstrap_service import run_startup_bootstrap_async

        await run_startup_bootstrap_async()
        logger.info('[Startup] Bootstrap complete.')
    except Exception as exc:  # noqa: BLE001 — bootstrap is non-fatal
        logger.warning('[Startup] Bootstrap skipped: %s', exc)


async def _initialize_modules(logger: Logger, event_bus) -> list[str]:
    """Run every module's startup hooks; returns the names that failed."""
    from app.core.context import ModuleContext
    from app.core.module_identity import module_scope
    from app.core.module_registry import module_registry
    from app.database import AsyncSessionLocal

    failed_modules: list[str] = []
    context = ModuleContext(event_bus=event_bus)
    async with AsyncSessionLocal() as db:  # type: ignore[misc]
        try:
            for module in module_registry.get_all():
                try:
                    # Hooks are the module's own code with no request around
                    # it; the identity they run under is what lets their
                    # settings/secret/event calls speak for the module.
                    with module_scope(module.metadata.name):
                        await module_registry.check_module_version_async(module, db)
                        module.on_startup(context)
                        await module.on_startup_async(context)
                    logger.info(f'Initialized module: {module.metadata.name}')
                except Exception as exc:  # noqa: BLE001 — startup must continue past per-module failures
                    logger.error(
                        f'Failed to initialize module {module.metadata.name}: {exc}'
                    )
                    failed_modules.append(module.metadata.name)
                    module_registry.mark_degraded(module.metadata.name)
            await db.commit()
        except Exception:  # rolled back, then re-raised
            await db.rollback()
            raise

        # Phase two: every module has started, so a catalogue built along the
        # way is complete. Hooks that consume one belong here and not in
        # on_startup, which runs in the middle of an alphabetical walk and
        # cannot see what later-named modules contribute — the webhook
        # subscription sat there and silently missed them.
        for module in module_registry.get_all():
            if module.metadata.name in failed_modules:
                continue
            try:
                with module_scope(module.metadata.name):
                    module.on_modules_ready(context)
            except Exception as exc:  # noqa: BLE001 — ready must continue past per-module failures
                logger.error(
                    f'Failed to run ready hook for module {module.metadata.name}: {exc}'
                )
                failed_modules.append(module.metadata.name)
                module_registry.mark_degraded(module.metadata.name)
    return failed_modules


def _register_background_jobs(task_scheduler, event_bus) -> None:
    """Register the recurring jobs and start ticking.

    The queue is DB-backed — no Redis required; SKIP LOCKED claiming keeps
    processing safe even when every node ticks. The two relay jobs are the
    exception: they only make sense with Redis present.
    """
    from datetime import timedelta

    from app.services.email_jobs import run_email_jobs_once
    from app.services.items._retention import run_archive_retention_once
    from app.services.reconciliation_job import (
        RECONCILIATION_INTERVAL,
        run_reconciliation_once,
    )

    task_scheduler.register(
        name='email_jobs',
        interval=timedelta(seconds=30),
        handler=run_email_jobs_once,
        module_name='core',
    )
    # archive retention — daily, org-opt-in via settings.
    task_scheduler.register(
        name='archive_retention',
        interval=timedelta(hours=24),
        handler=run_archive_retention_once,
        module_name='core',
    )
    # stock reconciliation — the three-pair drift check, measured on a
    # cycle so a silent divergence is a number in the log, and a growing
    # one is a warning to the org's admins.
    task_scheduler.register(
        name='stock_reconciliation',
        interval=RECONCILIATION_INTERVAL,
        handler=run_reconciliation_once,
        module_name='core',
    )
    if event_bus.redis is not None or task_scheduler._redis is not None:
        from app.core.event_delivery_retry import retry_failed_deliveries_once
        from app.core.outbox_relay import relay_outbox_once
        from app.core.stream_reaper import reap_streams_once

        task_scheduler.register(
            name='stream_reaper',
            interval=timedelta(minutes=5),
            handler=reap_streams_once,
            module_name='core',
        )
        task_scheduler.register(
            name='outbox_relay',
            interval=timedelta(seconds=2),
            handler=relay_outbox_once,
            module_name='core',
        )
        # Handlers that failed on a stream delivery, run again with backoff
        # until they succeed or are parked as dead.
        task_scheduler.register(
            name='event_delivery_retry',
            interval=timedelta(seconds=15),
            handler=retry_failed_deliveries_once,
            module_name='core',
        )
    task_scheduler.start_all()


async def _reclaim_after_restart(logger: Logger, event_bus, task_scheduler) -> None:
    """Run the stream reaper once now instead of waiting for its first tick.

    What a previous process read and never acknowledged is redelivered here,
    after the modules have subscribed their handlers, rather than up to a
    reaper interval later. Entries not yet idle for ``STREAM_CLAIM_IDLE_MS``
    stay for the tick.
    """
    if event_bus.redis is None and task_scheduler._redis is None:
        return
    from app.core.stream_reaper import reap_streams_once

    try:
        await reap_streams_once()
    except (
        Exception
    ) as exc:  # same net as the reaper tick: this step must not end startup
        logger.warning('[Startup] Stream reclaim skipped: %s', exc, exc_info=True)


async def _start_services(
    logger: Logger, event_bus
) -> tuple[asyncio.Task | None, list[str]]:
    """Everything that has to happen before the app serves a request.

    Returns the NotificationHub listener task (shutdown cancels it) and the
    modules that failed to initialize — the caller decides whether that is
    fatal (STRICT_STARTUP).
    """
    from app.api.websocket import hub as notification_hub
    from app.config import settings
    from app.core.scheduler import task_scheduler

    if settings.TESTING:
        logger.info('[Startup] Skipping Redis listeners and seeding in TESTING mode')
        return None, []

    hub_task = await _connect_redis_services(
        logger, settings, event_bus, notification_hub, task_scheduler
    )
    await _wire_token_blacklist_and_cache(logger, settings, event_bus)
    await _seed_and_bootstrap(logger, settings)

    logger.info('[Startup] Initializing modules...')
    failed_modules = await _initialize_modules(logger, event_bus)

    logger.info('[Startup] Starting task scheduler...')
    _register_background_jobs(task_scheduler, event_bus)
    await _reclaim_after_restart(logger, event_bus, task_scheduler)

    from app.core.dev_guard import run_dev_guard

    run_dev_guard()
    logger.info('[Startup] All startup tasks complete.')
    return hub_task, failed_modules


async def _run_shutdown(hub_task: asyncio.Task | None, async_engine) -> None:
    """Tear down in the reverse order of startup.

    The WS hub listener is cancelled BEFORE its Redis connection closes and
    then awaited — otherwise the blocked ``pubsub.listen()`` dies with a
    ConnectionError as an unretrieved task exception.
    """
    from app.api.websocket import hub as notification_hub
    from app.core.events import event_bus
    from app.core.scheduler import task_scheduler

    if hub_task is not None:
        hub_task.cancel()
        try:
            await hub_task
        except asyncio.CancelledError:
            pass
    await task_scheduler.stop_all_async()
    await notification_hub.disconnect_redis()
    await event_bus.disconnect()

    if async_engine is not None:
        await async_engine.dispose()


@asynccontextmanager
async def lifespan(app: 'FastAPI'):
    """Initialize and tear down async services around the FastAPI app."""
    logger = _get_logger()
    logger.info('[Startup] Lifespan entered.')
    from app.config import settings
    from app.core.events import event_bus

    # Initialize async engine INSIDE the lifespan to bind to the correct event loop.
    # Module-level creation would attach pool connections to the import-time loop.
    from app.database import init_async_engine

    logger.info('[Startup] Initializing async DB engine...')
    init_async_engine()
    logger.info('[Startup] Async DB engine initialized.')

    from app.database import async_engine

    await _warm_up_async_engine(async_engine, logger)

    hub_task: asyncio.Task | None = None
    failed_modules: list[str] = []
    try:
        hub_task, failed_modules = await _start_services(logger, event_bus)
    except Exception as e:  # startup must never crash past failed background services
        logger.error(f'Startup failed: {e}', exc_info=True)

    # STRICT_STARTUP gate — enforced AFTER the blanket catch so it actually
    # fires instead of being swallowed. Previous code raised inside the try
    # block, landing in this same except handler.
    if not settings.TESTING and settings.STRICT_STARTUP and failed_modules:
        raise RuntimeError(
            f'STRICT_STARTUP enabled — modules failed to initialize: '
            f'{", ".join(failed_modules)}'
        )

    # Configuration worth a line at startup rather than a surprise later.
    from app.config import warn_if_frontend_url_is_local
    from app.services.email_service import warn_if_system_smtp_is_plaintext

    warn_if_frontend_url_is_local()
    warn_if_system_smtp_is_plaintext()

    from app.core.worker_recycle import start_watch

    memory_watch = start_watch()

    logger.info('[Startup] Lifespan startup complete. Yielding control.')
    yield  # Application runs here

    if memory_watch is not None:
        memory_watch.cancel()
    await _run_shutdown(hub_task, async_engine)
