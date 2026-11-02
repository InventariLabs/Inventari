"""An unreadable signing secret is a failed delivery, and the breaker sees it.

Measured before this: the payload went out unsigned, the delivery log said
``success``, and the endpoint's failure counter stayed where it was — a
channel whose signing secret had just been rotated was indistinguishable,
from the receiver and from the circuit breaker both, from one that never had
a secret. Now the attempt is refused before anything is sent: the log carries
the reason, the counter moves, and the endpoint reaches the cut-off like any
failing channel.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.database
from app.core.events import SystemEvent, TenantEventPayload
from app.models.organization import Organization
from app.modules.webhooks._webhook_constants import _DELIVERY_STATUS_FAILED
from app.modules.webhooks.models import WebhookDeliveryLog, WebhookEndpoint
from app.modules.webhooks.webhook_service import dispatch_event

from .._signing_helpers import recording_transport, unreadable

TABLES = 'webhook_delivery_logs, webhook_endpoints, organizations'

SessionFactory = async_sessionmaker[AsyncSession]


@pytest.fixture
async def session_factory(
    async_engine_fixture: Any, setup_test_db: Any, monkeypatch: pytest.MonkeyPatch
) -> SessionFactory:
    factory = async_sessionmaker(
        async_engine_fixture, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        await session.execute(text(f'TRUNCATE {TABLES} RESTART IDENTITY CASCADE'))
        await session.commit()
    # The subscriber opens its own sessions through the module DB facade,
    # which forwards live to app.database.AsyncSessionLocal.
    monkeypatch.setattr(app.database, 'AsyncSessionLocal', factory)
    return factory


@pytest.fixture
async def rotated_key_channel(session_factory: SessionFactory) -> WebhookEndpoint:
    from app.services.crypto_service import encrypt_module_secret

    async with session_factory() as session:
        org = Organization(name=f'org-{uuid.uuid4().hex[:8]}', enabled_modules=[])
        session.add(org)
        await session.flush()
        webhook = WebhookEndpoint(
            organization_id=org.id,
            name='Rotated key',
            # An IP literal: the guard passes it without a resolver, and the
            # refusal being measured arrives before any request would.
            url='https://93.184.216.34/hook',
            event_types=['item.created'],
            max_retries=0,
            retry_backoff_seconds=10,
            timeout_seconds=10,
            is_active=True,
            secret=unreadable(encrypt_module_secret('webhooks', 'hmac-key')),
        )
        session.add(webhook)
        await session.commit()
        session.expunge(webhook)
        return webhook


@pytest.mark.integration
class TestAnUnreadableSecret:
    async def test_the_log_carries_the_reason_and_the_counter_moves(
        self,
        session_factory: SessionFactory,
        rotated_key_channel: WebhookEndpoint,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sent: list[dict[str, Any]] = []
        monkeypatch.setattr(
            'app.modules.webhooks._webhook_delivery.httpx.AsyncClient',
            recording_transport(sent),
        )

        await dispatch_event(
            SystemEvent.ITEM_CREATED,
            TenantEventPayload(
                organization_id=str(rotated_key_channel.organization_id),
                detail='x',
            ),
        )

        async with session_factory() as session:
            log = await session.scalar(select(WebhookDeliveryLog))
            endpoint = await session.get(WebhookEndpoint, rotated_key_channel.id)

        assert sent == [], 'the refusal happens before anything is sent'
        assert log is not None, 'the attempt has to leave a row'
        assert log.delivery_status == _DELIVERY_STATUS_FAILED
        assert log.status_code is None, 'nothing was sent, so nothing answered'
        assert log.error_message is not None
        assert 'cannot be read' in log.error_message

        assert endpoint is not None
        assert endpoint.consecutive_failures == 1, (
            'the breaker counts the refusal like any other failure — a '
            'success here is how the channel stayed silently unverifiable'
        )
