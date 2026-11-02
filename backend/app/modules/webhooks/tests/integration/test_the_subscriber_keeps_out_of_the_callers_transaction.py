"""The event subscriber keeps out of the caller's transaction.

A subscriber that rides the request session closes the caller's unit of work
from the inside: its durability commit lands mid-stack, so a caller that
refuses AFTER emitting can no longer roll its own work back. The subscriber
owns its sessions instead — the refusal after emit still discards the
caller's work, while the subscriber's own delivery trace stays durable.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.database
from app.core.events import TenantEventPayload
from app.models.organization import Organization
from app.modules.webhooks._webhook_constants import _DELIVERY_STATUS_PENDING_RETRY
from app.modules.webhooks.models import WebhookDeliveryLog, WebhookEndpoint
from app.modules.webhooks.webhook_service import dispatch_event

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
    # which forwards live to app.database.AsyncSessionLocal — point that at
    # the test engine so the subscriber's commits land in the test database.
    monkeypatch.setattr(app.database, 'AsyncSessionLocal', factory)
    return factory


@pytest.fixture
async def org_id(session_factory: SessionFactory) -> Any:
    async with session_factory() as session:
        org = Organization(
            name=f'org-{uuid.uuid4().hex[:8]}', enabled_modules=['webhooks']
        )
        session.add(org)
        await session.flush()
        session.add(
            WebhookEndpoint(
                organization_id=org.id,
                name='Probe receiver',
                url='http://127.0.0.1:59999/never',
                event_types=['location.created'],
                max_retries=3,
                retry_backoff_seconds=10,
                timeout_seconds=10,
                is_active=True,
            )
        )
        await session.commit()
        return org.id


@pytest.mark.integration
class TestTheSubscriberKeepsOutOfTheCallersTransaction:
    async def test_refusal_after_emit_still_rolls_the_callers_work_back(
        self, session_factory: SessionFactory, org_id: Any
    ) -> None:
        """'Odmowa po emit': the caller refuses after the event went out.

        The subscriber must have committed nothing on the caller's session —
        its own delivery trace durable, the caller's work still discardable.
        """
        async with session_factory() as caller:
            # The caller's work-in-flight: a row only this transaction can
            # see until it commits.
            witness = Organization(name='Witness rogue', enabled_modules=[])
            caller.add(witness)
            await caller.flush()

            # The subscriber runs, as it does on the inline no-Redis dispatch:
            # it matches the endpoint, commits PENDING rows in its own session,
            # attempts delivery (refused: nothing listens on :59999) and
            # commits the outcome.
            await dispatch_event(
                'location.created', TenantEventPayload(organization_id=str(org_id))
            )

            assert caller.in_transaction(), (
                'the subscriber closed the caller’s transaction mid-stack'
            )
            async with session_factory() as other:
                leaked = await other.scalar(
                    select(Organization).where(Organization.name == 'Witness rogue')
                )
            assert leaked is None, (
                'the caller’s uncommitted work became visible — a session '
                'the caller does not own committed it'
            )

            # The refusal itself: the caller rolls the unit of work back.
            await caller.rollback()

        async with session_factory() as after:
            gone = await after.scalar(
                select(Organization).where(Organization.name == 'Witness rogue')
            )
            assert gone is None, (
                'the refusal after emit must still discard the caller’s work'
            )

            trace = await after.scalar(
                select(WebhookDeliveryLog).where(
                    WebhookDeliveryLog.organization_id == org_id
                )
            )
            assert trace is not None, (
                'the subscriber’s own session keeps its delivery trace durable'
            )
            assert trace.event_type == 'location.created'
            assert trace.delivery_status == _DELIVERY_STATUS_PENDING_RETRY
            assert trace.attempt_number == 1
