"""Webhooks module — subscribes to all system events and dispatches HTTP webhooks."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import ModuleContext
from app.core.events import EventPayload, SystemEvent
from app.core.logging import get_logger
from app.core.modules import BaseModule, ModuleMetadata
from app.modules.webhooks._webhook_constants import event_name
from app.modules.webhooks.schemas import valid_event_types

logger = get_logger(__name__)


class WebhooksModule(BaseModule):
    def __init__(self) -> None:
        self._metadata = ModuleMetadata(
            name='webhooks',
            version='0.6.0',
            display_name='Webhooks',
            description=(
                'Send HTTP notifications on system events to external services '
                '(Home Assistant, Discord, n8n, Zapier, Node-RED, and more).'
            ),
            icon='webhook',
            category='integrations',
            module_type='core',
            requires=[],
            author='Core Team',
        )

    @property
    def metadata(self) -> ModuleMetadata:
        return self._metadata

    async def enable_preview(self, organization_id: UUID, db: AsyncSession) -> int:
        """Active endpoints that start receiving as soon as the module is on."""
        from app.modules.webhooks.webhook_service import (
            count_endpoints_that_would_resume,
        )

        return await count_endpoints_that_would_resume(db, organization_id)

    def get_secret_columns(self) -> list[Any]:
        """Each endpoint's signing secret."""
        from app.modules.webhooks.models import WebhookEndpoint

        return [WebhookEndpoint.secret]

    def register_routes(self) -> APIRouter:
        from app.modules.webhooks.router import router

        return router

    def on_startup(self, context: ModuleContext) -> None:
        super().on_startup(context)
        self._context = context

        # Register background workers via the scheduler facade
        try:
            from datetime import timedelta

            from app.core.public_api import core_api

            core_api.scheduler.register_task(
                'webhooks_retry_failed',
                timedelta(seconds=60),
                self._retry_worker,
                module_name='webhooks',
                is_persistent=True,
            )
            core_api.scheduler.register_task(
                'webhooks_cleanup_logs',
                timedelta(hours=24),
                self._cleanup_worker,
                module_name='webhooks',
                is_persistent=True,
            )
        except (ImportError, AttributeError):
            logger.warning(
                '[webhooks] TaskScheduler unavailable — retry and cleanup workers disabled.'
            )

        # Run the one-time legacy-key migration once at startup (idempotent:
        # after the first successful run it is a cheap no-op). It fires per
        # worker on boot, which is harmless — unlike the previous 1 Hz
        # scheduled task that looped forever in every worker.
        try:
            import asyncio

            asyncio.get_running_loop().create_task(self._migrate_settings_worker())
        except RuntimeError:
            logger.debug(
                '[webhooks] No running event loop — settings migration not scheduled'
            )

    def get_settings_schema(self) -> dict[str, Any] | None:
        return {
            'type': 'object',
            'properties': {
                'log_retention_days': {
                    'type': 'integer',
                    'default': 30,
                    'minimum': 1,
                    'maximum': 365,
                    'title': 'Log retention (days)',
                    'title_key': 'webhooks:settings.logRetentionDays',
                    'description_key': 'webhooks:settings.logRetentionDaysDescription',
                    'description': 'How long to keep webhook delivery logs.',
                },
                'circuit_breaker_threshold': {
                    'type': 'integer',
                    'default': 10,
                    'minimum': 3,
                    'maximum': 100,
                    'title': 'Circuit breaker threshold',
                    'title_key': 'webhooks:settings.circuitBreakerThreshold',
                    'description_key': 'webhooks:settings.circuitBreakerThresholdDescription',
                    'description': (
                        'Auto-disable a webhook after this many consecutive '
                        'failed attempts. Every attempt counts on its own — '
                        'the first delivery, each retry and the Test button '
                        'all feed the same tally.'
                    ),
                },
            },
        }

    def get_default_settings(self) -> dict[str, Any]:
        return {
            'log_retention_days': 30,
            'circuit_breaker_threshold': 10,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def on_modules_ready(self, context: ModuleContext) -> None:
        """Subscribe to every subscribable event — once they all exist.

        Not in ``on_startup``: that runs in the middle of an alphabetical walk
        of the modules directory, and a module that sorts after webhooks
        registers its payloads after this one has started. Taking the catalogue
        there is a one-shot snapshot of whatever happened to exist at that
        moment. The API still offers the subscription, because
        ``valid_event_types()`` is computed per request; the bus has no
        listener, because the subscription was not; and delivery is silently
        zero. Here every module has started, so the catalogue is the whole one.

        Iterating ``SystemEvent`` alone would skip everything modules
        contribute to the payload registry — a webhook on ``recipe.created``
        would be accepted by the API and then never fire.
        """
        self._context = context
        for event in sorted(valid_event_types()):
            context.subscribe(event, self._make_event_handler(event))

    def _make_event_handler(
        self, event: SystemEvent | str
    ) -> Callable[[EventPayload], Any]:
        """Return an async handler that dispatches *event* to matching webhooks."""
        name = event_name(event)

        async def _handle(payload: EventPayload) -> None:
            from app.core.events import TenantEventPayload

            if not isinstance(payload, TenantEventPayload):
                return  # Webhooks only support tenant-scoped events

            from app.modules.webhooks.webhook_service import dispatch_event

            # The subscriber opens and closes its own sessions; this handler
            # holds none, so nothing of the caller's rides along.
            try:
                await dispatch_event(name, payload)
            except Exception:  # failing event emission must never break the main flow
                logger.exception(
                    '[webhooks] Unhandled error dispatching event %s', name
                )

        _handle.__name__ = f'webhooks_handle_{name.replace(".", "_")}'
        return _handle

    async def _retry_worker(self, payload: dict[str, Any] | None = None) -> None:
        """Retry pending webhook deliveries (called by TaskScheduler every 60 s)."""
        from app.modules.webhooks._webhook_workers import retry_failed_deliveries

        async with self._context.global_session() as db:
            try:
                await retry_failed_deliveries(db)
            except Exception:  # worker loop must never crash on per-item failure
                logger.exception('[webhooks] Error in retry worker')

    async def _migrate_settings_worker(
        self, payload: dict[str, Any] | None = None
    ) -> None:
        """One-shot: migrate legacy ``webhooks`` flat key to ``module:webhooks``."""
        from app.modules.webhooks.migration import (
            migrate_all_orgs_webhooks_settings_async,
        )

        async with self._context.global_session() as db:
            try:
                migrated = await migrate_all_orgs_webhooks_settings_async(db)
                if migrated:
                    logger.info(
                        '[webhooks] Migrated settings for %d organization(s)',
                        migrated,
                    )
            except Exception:  # a failed migration must not stop startup
                logger.exception('[webhooks] Error during settings migration')

    async def _cleanup_worker(self, payload: dict[str, Any] | None = None) -> None:
        """Delete old delivery logs (called by TaskScheduler every 24 h)."""
        from app.modules.webhooks._webhook_workers import (
            cleanup_logs_per_organization_async,
        )

        default_days = self.get_default_settings().get('log_retention_days', 30)
        async with self._context.global_session() as db:
            try:
                await cleanup_logs_per_organization_async(db, default_days)
            except Exception:  # worker loop must never crash on per-item failure
                logger.exception('[webhooks] Error in log-cleanup worker')
