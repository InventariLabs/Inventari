"""A module that sorts after webhooks still gets its webhooks delivered.

Module startup is an alphabetical walk of the modules directory, and webhooks
used to subscribe to the event catalogue in the middle of it — taking the
catalogue once, at its own turn. Every module in the tree happens to sort
before webhooks, so the one-shot subscription looked complete and was never
questioned.

A community module named after w is the case that breaks it: ``work_orders``,
``warehouse_tools``, ``zendesk_sync``. They register their payloads after
webhooks has already taken its snapshot. The API still offers the subscription
— ``valid_event_types()`` is computed per request — the bus has no listener,
because the subscription was not, and delivery is silently zero. Nothing
reports a problem: the endpoint is active, the event is accepted, the log
simply never gets a row.

The subscription now happens in a phase that runs after every module has
started, so it sees the whole catalogue whatever the names sort to.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core._event_bus import EventBus
from app.core.contracts.events._base import TenantEventPayload
from app.core.contracts.events._registry import _RUNTIME_PAYLOAD_TYPES, register_payload
from app.core.modules import BaseModule, ModuleMetadata
from app.models.organization import Organization
from app.modules.webhooks.models import WebhookEndpoint
from app.modules.webhooks.module import WebhooksModule

TABLES = 'webhook_delivery_logs, webhook_endpoints, organizations'

SessionFactory = async_sessionmaker[AsyncSession]

LATE_EVENT = 'work_orders.late_ping'


class LatePayload(TenantEventPayload):
    """What a module named after webhooks contributes to the catalogue."""

    note: str = ''


class WorkOrdersModule(BaseModule):
    """Stands in for a community module whose name sorts after webhooks."""

    def __init__(self) -> None:
        self._metadata = ModuleMetadata(
            name='work_orders',
            version='0.1.0',
            display_name='Work Orders',
            description='stands in for a module that starts after webhooks',
            icon='clipboard-list',
            category='business',
            module_type='community',
            requires=[],
            author='test',
        )

    @property
    def metadata(self) -> ModuleMetadata:
        return self._metadata

    def register_routes(self) -> Any:
        from fastapi import APIRouter

        return APIRouter()

    def on_startup(self, context: Any) -> None:
        # Deliberately no super(): the stand-in contributes one payload and
        # nothing else, so this test measures the ordering alone.
        register_payload(LATE_EVENT, LatePayload)


class _StubRegistry:
    """The slice of ModuleRegistry that the startup walk touches."""

    def __init__(self, modules: list[BaseModule]) -> None:
        self._modules = modules
        self.degraded: list[str] = []

    def get_all(self) -> list[BaseModule]:
        return self._modules

    async def check_module_version_async(self, module: BaseModule, db: Any) -> None:
        return None

    def mark_degraded(self, name: str) -> None:
        self.degraded.append(name)


@pytest.fixture
async def session_factory(
    async_engine_fixture: Any, setup_test_db: Any
) -> SessionFactory:
    factory = async_sessionmaker(
        async_engine_fixture, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        await session.execute(text(f'TRUNCATE {TABLES} RESTART IDENTITY CASCADE'))
        await session.commit()
    return factory


@pytest.fixture
def late_event_cleaned() -> Any:
    """The payload catalogue is process-global; leave no entry behind."""
    yield
    _RUNTIME_PAYLOAD_TYPES.pop(LATE_EVENT, None)


@pytest.fixture
async def started_bus(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: SessionFactory,
    late_event_cleaned: Any,
) -> EventBus:
    """Run the real startup walk over webhooks and a module that sorts later."""
    from app import _lifespan

    # `webhooks` sorts before `work_orders`, which is the whole precondition:
    # webhooks takes its catalogue snapshot while the late module's events do
    # not exist yet.
    stub = _StubRegistry([WebhooksModule(), WorkOrdersModule()])
    monkeypatch.setattr('app.core.module_registry.module_registry', stub)
    # The startup walk opens its own session for the version check; the test
    # engine is the only engine this run has.
    monkeypatch.setattr('app.database.AsyncSessionLocal', session_factory)

    bus = EventBus()
    failed = await _lifespan._initialize_modules(_lifespan._get_logger(), bus)
    assert failed == [], f'startup reported failures: {failed}'
    return bus


@pytest.mark.integration
class TestTheWebhookSubscriptionWaitsForEveryModule:
    async def test_a_late_modules_webhook_actually_delivers(
        self,
        started_bus: EventBus,
        session_factory: SessionFactory,
    ) -> None:
        """The stand-in registered its payload after webhooks started — and
        an endpoint subscribed to it must still produce a delivery row."""
        async with session_factory() as session:
            org = Organization(
                name=f'org-{uuid.uuid4().hex[:8]}', enabled_modules=['webhooks']
            )
            session.add(org)
            await session.flush()
            session.add(
                WebhookEndpoint(
                    organization_id=org.id,
                    name='late module hook',
                    url='https://example.com/late',
                    event_types=[LATE_EVENT],
                    max_retries=0,
                    retry_backoff_seconds=1,
                    timeout_seconds=5,
                    is_active=True,
                )
            )
            await session.commit()
            org_id = org.id

        await started_bus.emit(
            LATE_EVENT,
            TenantEventPayload(**{'organization_id': str(org_id), 'note': 'hello'}),
        )

        async with session_factory() as session:
            rows = (
                (
                    await session.execute(
                        text('SELECT count(*) FROM webhook_delivery_logs')
                    )
                )
                .scalars()
                .one()
            )
        assert rows == 1, (
            'a module that sorts after webhooks registered its payload and an '
            'endpoint subscribed to it, yet nothing was delivered — the '
            'subscription was taken before that payload existed'
        )
