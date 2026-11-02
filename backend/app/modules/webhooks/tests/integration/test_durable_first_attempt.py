"""Integration tests for durable webhook first-attempt.

dispatch_event commits a PENDING delivery-log row BEFORE the HTTP attempt,
so a crash/restart mid-delivery leaves a trace. The retry worker requeues
stale pending rows and completes the delivery.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.database
from app.core.events import SystemEvent, TenantEventPayload
from app.models.organization import Organization
from app.modules.webhooks._webhook_constants import (
    _DELIVERY_STATUS_PENDING_RETRY,
    _DELIVERY_STATUS_SUCCESS,
)
from app.modules.webhooks._webhook_workers import retry_failed_deliveries
from app.modules.webhooks.models import WebhookDeliveryLog, WebhookEndpoint
from app.modules.webhooks.webhook_service import dispatch_event

TABLES = 'webhook_delivery_logs, webhook_endpoints, organizations'

SessionFactory = async_sessionmaker[AsyncSession]

# Scoped to the test's own organization: the table belongs to the worker's
# database, and a row any other writer leaves there is not this test's delivery.
_STATUSES_OF_ORG = (
    'SELECT delivery_status FROM webhook_delivery_logs WHERE organization_id = :org'
)


@pytest.fixture
async def session_factory(
    async_engine_fixture: Any,
    setup_test_db: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> SessionFactory:
    factory = async_sessionmaker(
        async_engine_fixture, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        await session.execute(text(f'TRUNCATE {TABLES} RESTART IDENTITY CASCADE'))
        await session.commit()
    # The subscriber opens its own sessions through the module DB facade,
    # which forwards live to app.database.AsyncSessionLocal — point that at
    # the test engine.
    monkeypatch.setattr(app.database, 'AsyncSessionLocal', factory)
    return factory


@pytest.fixture
async def webhook(session_factory: SessionFactory) -> WebhookEndpoint:
    async with session_factory() as session:
        org = Organization(name=f'org-{uuid.uuid4().hex[:8]}', enabled_modules=[])
        session.add(org)
        await session.flush()
        wh = WebhookEndpoint(
            organization_id=org.id,
            name='Test WH',
            url='https://example.com/hook',
            event_types=['item.created'],
            max_retries=3,
            retry_backoff_seconds=10,
            timeout_seconds=10,
            is_active=True,
        )
        session.add(wh)
        await session.commit()
        return wh


def _payload(org_id: uuid.UUID) -> TenantEventPayload:
    return TenantEventPayload(**{'organization_id': str(org_id), 'detail': 'x'})


@pytest.mark.integration
class TestDurableFirstAttempt:
    async def test_pending_row_committed_before_http_attempt(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        """During the HTTP call, a second session must already see a
        COMMITTED pending row — the crash trace."""
        observed_status: list[str] = []

        async def inspect_mid_flight(
            *args: Any, **kwargs: Any
        ) -> tuple[bool, int, str, None]:
            async with session_factory() as other:
                rows = (
                    (
                        await other.execute(
                            text(_STATUSES_OF_ORG),
                            {'org': webhook.organization_id},
                        )
                    )
                    .scalars()
                    .all()
                )
                observed_status.extend(rows)
            return (True, 200, 'ok', None)

        with patch(
            'app.modules.webhooks.webhook_service._attempt_delivery',
            side_effect=inspect_mid_flight,
        ):
            await dispatch_event(
                SystemEvent.ITEM_CREATED, _payload(webhook.organization_id)
            )

        assert observed_status == ['pending']

        async with session_factory() as session:
            final = (
                (
                    await session.execute(
                        text(_STATUSES_OF_ORG), {'org': webhook.organization_id}
                    )
                )
                .scalars()
                .all()
            )
        assert final == [_DELIVERY_STATUS_SUCCESS]

    async def test_crash_after_pending_row_gets_requeued_and_delivered(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        """Simulated crash: a stale pending row (no result) is requeued by
        the retry worker and delivered."""
        async with session_factory() as session:
            log = WebhookDeliveryLog(
                webhook_endpoint_id=webhook.id,
                organization_id=webhook.organization_id,
                event_type='item.created',
                payload_json={'foo': 'bar'},
                attempt_number=1,
                delivery_status='pending',
                next_retry_at=None,
            )
            session.add(log)
            await session.commit()
            log_id = cast(uuid.UUID, log.id)
            # Age the row past the stale threshold (created_at is server-side).
            await session.execute(
                text(
                    'UPDATE webhook_delivery_logs SET created_at = :ts WHERE id = :id'
                ),
                {'ts': datetime.now(UTC) - timedelta(minutes=30), 'id': log_id},
            )
            await session.commit()

        with patch(
            'app.modules.webhooks._webhook_workers._attempt_delivery',
            return_value=(True, 200, 'ok', None),
        ) as mock_attempt:
            async with session_factory() as session:
                await retry_failed_deliveries(session)

        mock_attempt.assert_called_once()
        async with session_factory() as session:
            row = await session.get(WebhookDeliveryLog, log_id)
            assert row is not None
            assert row.delivery_status == _DELIVERY_STATUS_SUCCESS

    async def test_fresh_pending_row_not_requeued(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        """A pending row from an in-flight attempt (young) must NOT be
        requeued — that would double-deliver."""
        async with session_factory() as session:
            log = WebhookDeliveryLog(
                webhook_endpoint_id=webhook.id,
                organization_id=webhook.organization_id,
                event_type='item.created',
                payload_json={'foo': 'bar'},
                attempt_number=1,
                delivery_status='pending',
                next_retry_at=None,
            )
            session.add(log)
            await session.commit()
            log_id = cast(uuid.UUID, log.id)

        with patch(
            'app.modules.webhooks._webhook_workers._attempt_delivery',
            return_value=(True, 200, 'ok', None),
        ) as mock_attempt:
            async with session_factory() as session:
                await retry_failed_deliveries(session)

        mock_attempt.assert_not_called()
        async with session_factory() as session:
            row = await session.get(WebhookDeliveryLog, log_id)
            assert row is not None
            assert row.delivery_status == 'pending'

    async def test_module_event_dispatches_by_plain_name(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        """A webhook on `recipe.created` must actually receive the event.

        Module events have no `SystemEvent` member, so they travel as plain
        strings. Matching used to read `event.value`, which meant a string
        dispatch raised before reaching any endpoint.
        """
        async with session_factory() as session:
            wh = await session.get(WebhookEndpoint, webhook.id)
            assert wh is not None
            wh.event_types = ['recipe.created']
            await session.commit()

        with patch(
            'app.modules.webhooks.webhook_service._attempt_delivery',
            return_value=(True, 200, 'ok', None),
        ):
            await dispatch_event('recipe.created', _payload(webhook.organization_id))

        async with session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        'SELECT event_type, delivery_status FROM webhook_delivery_logs '
                        'WHERE organization_id = :org'
                    ),
                    {'org': webhook.organization_id},
                )
            ).all()
        assert rows == [('recipe.created', _DELIVERY_STATUS_SUCCESS)]

    async def test_failed_first_attempt_lands_in_pending_retry(
        self, session_factory: SessionFactory, webhook: WebhookEndpoint
    ) -> None:
        with patch(
            'app.modules.webhooks.webhook_service._attempt_delivery',
            return_value=(False, 500, 'err', 'boom'),
        ):
            await dispatch_event(
                SystemEvent.ITEM_CREATED, _payload(webhook.organization_id)
            )

        async with session_factory() as session:
            rows = (
                (
                    await session.execute(
                        text(_STATUSES_OF_ORG), {'org': webhook.organization_id}
                    )
                )
                .scalars()
                .all()
            )
        assert rows == [_DELIVERY_STATUS_PENDING_RETRY]
