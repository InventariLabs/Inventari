"""The one event a switched-off Webhooks module still sends: that it went quiet.

The module's own switch is already saved when the event about it reaches the
dispatcher, so the gate that keeps a switched-off module silent cut that last
event off first — a receiver could not tell "the organization turned Webhooks
off" from "nothing changed in the pantry". The announcement is the single
exception; everything else stays cut off.
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.database
from app.core.events import SystemEvent, TenantEventPayload
from app.models.organization import Organization
from app.modules.webhooks.models import WebhookEndpoint
from app.modules.webhooks.webhook_service import dispatch_event

TABLES = 'webhook_delivery_logs, webhook_endpoints, organizations'

SessionFactory = async_sessionmaker[AsyncSession]

ATTEMPT = 'app.modules.webhooks.webhook_service._attempt_delivery'


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
    monkeypatch.setattr(app.database, 'AsyncSessionLocal', factory)
    return factory


@pytest.fixture
async def switched_off_org(session_factory: SessionFactory) -> uuid.UUID:
    """An organization whose enabled set names other modules, not webhooks."""
    async with session_factory() as session:
        org = Organization(
            name=f'org-{uuid.uuid4().hex[:8]}', enabled_modules=['items']
        )
        session.add(org)
        await session.flush()
        org_id = org.id
        for name, events in (
            ('Listens to the switch', ['module.disabled', 'item.created']),
            ('Only items', ['item.created']),
        ):
            session.add(
                WebhookEndpoint(
                    organization_id=org_id,
                    name=name,
                    url=f'https://example.com/{uuid.uuid4().hex[:6]}',
                    event_types=events,
                    max_retries=3,
                    retry_backoff_seconds=10,
                    timeout_seconds=10,
                    is_active=True,
                )
            )
        await session.commit()
    return org_id


def _module_payload(org_id: uuid.UUID, module_name: str) -> TenantEventPayload:
    return TenantEventPayload.model_validate(
        {'organization_id': str(org_id), 'module_name': module_name}
    )


async def _delivered_events(
    session_factory: SessionFactory, org_id: uuid.UUID
) -> list[str]:
    async with session_factory() as session:
        rows = await session.execute(
            text(
                'SELECT event_type FROM webhook_delivery_logs '
                'WHERE organization_id = :org ORDER BY created_at'
            ),
            {'org': org_id},
        )
        return list(rows.scalars().all())


@pytest.mark.integration
class TestSwitchingWebhooksOff:
    async def test_the_announcement_reaches_the_endpoints_that_listen(
        self, session_factory: SessionFactory, switched_off_org: uuid.UUID
    ) -> None:
        attempt = AsyncMock(return_value=(True, 200, 'ok', None))
        with patch(ATTEMPT, attempt):
            await dispatch_event(
                SystemEvent.MODULE_DISABLED,
                _module_payload(switched_off_org, 'webhooks'),
            )

        # One endpoint subscribes to module.disabled; the other does not.
        assert attempt.await_count == 1
        assert await _delivered_events(session_factory, switched_off_org) == [
            'module.disabled'
        ]

    async def test_the_receiver_is_told_which_module_went_quiet(
        self, session_factory: SessionFactory, switched_off_org: uuid.UUID
    ) -> None:
        attempt = AsyncMock(return_value=(True, 200, 'ok', None))
        with patch(ATTEMPT, attempt):
            await dispatch_event(
                SystemEvent.MODULE_DISABLED,
                _module_payload(switched_off_org, 'webhooks'),
            )

        async with session_factory() as session:
            payload = (
                await session.execute(
                    text(
                        'SELECT payload_json FROM webhook_delivery_logs '
                        'WHERE organization_id = :org'
                    ),
                    {'org': switched_off_org},
                )
            ).scalar_one()
        assert payload['event'] == 'module.disabled'
        assert payload['data']['module_name'] == 'webhooks'

    async def test_nothing_else_leaves_while_the_module_is_off(
        self, session_factory: SessionFactory, switched_off_org: uuid.UUID
    ) -> None:
        attempt = AsyncMock(side_effect=AssertionError('no probe may leave'))
        with patch(ATTEMPT, attempt):
            await dispatch_event(
                SystemEvent.ITEM_CREATED,
                TenantEventPayload(
                    **{'organization_id': str(switched_off_org), 'detail': 'x'}
                ),
            )

        assert attempt.await_count == 0
        assert await _delivered_events(session_factory, switched_off_org) == []

    async def test_another_modules_announcement_stays_cut_off(
        self, session_factory: SessionFactory, switched_off_org: uuid.UUID
    ) -> None:
        """Only the module's own switch is announced — a neighbour going off
        while Webhooks is off says nothing the receiver may hear."""
        attempt = AsyncMock(side_effect=AssertionError('no probe may leave'))
        with patch(ATTEMPT, attempt):
            await dispatch_event(
                SystemEvent.MODULE_DISABLED,
                _module_payload(switched_off_org, 'nutrition'),
            )

        assert attempt.await_count == 0
        assert await _delivered_events(session_factory, switched_off_org) == []
