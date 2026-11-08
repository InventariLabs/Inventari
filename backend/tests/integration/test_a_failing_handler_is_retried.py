"""A handler that fails on a stream delivery is retried, then parked — never lost.

The consumer used to log the exception and acknowledge the message on the
next line: a handler that raised, deterministically or on a database blip,
had its event dropped with no retry, no dead-letter queue and nothing for an
administrator to see. The bus now writes the failed handler to the delivery
log (``event_deliveries``) and the retry worker runs it again, alone, with
backoff; after ``MAX_HANDLER_ATTEMPTS`` it is parked as dead and the
organization's admins are told.

Everything here goes through the production delivery path — XADD, the
consumer group, the ACK — against a real Redis stream, not the TESTING
inline dispatch, which retries nothing by design.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core._event_bus import MAX_HANDLER_ATTEMPTS, EventBus, handler_name
from app.core._event_types import EventPayload, TenantEventPayload
from app.core.event_delivery_retry import retry_failed_deliveries
from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper
from app.i18n.service import get_error_message
from app.models.event_delivery import EventDelivery
from app.models.notification import Notification
from app.models.organization import Organization

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_INSTANCE_EVENT = 'test.instance_wide'


@pytest.fixture
async def sessions(async_engine_fixture: Any, setup_test_db: Any):
    factory = async_sessionmaker(
        async_engine_fixture, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as db:
        await db.execute(
            text('TRUNCATE event_deliveries, notifications RESTART IDENTITY CASCADE')
        )
        await db.commit()
    return factory


@pytest.fixture
async def org_with_admin(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Retry Org', enabled_modules=['core'])
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    await ModuleTestHelper.create_user_async(
        real_async_db_session, org, email=f'admin_{uuid.uuid4().hex[:8]}@test.com'
    )
    await real_async_db_session.commit()
    return org


@pytest.fixture
async def bus(sessions: Any):
    """A bus on its own stream, writing its delivery log to the test database."""
    bus = EventBus()
    bus._stream_name = f'retry_test_stream_{uuid.uuid4().hex[:12]}'
    bus._group_name = f'retry_test_group_{uuid.uuid4().hex[:12]}'
    bus._session_factory = sessions
    await bus.connect(settings.REDIS_URL)
    assert bus._redis is not None, 'test requires a reachable Redis'
    yield bus
    if bus._redis is None:
        await bus.connect(settings.REDIS_URL)
    if bus._redis is not None:
        await bus._redis.delete(bus._stream_name)
    await bus.disconnect()


async def _deliver(
    bus: EventBus,
    payload: EventPayload,
    until: asyncio.Event,
    event: str = 'item.created',
) -> None:
    """Emit through the stream and let the consumer loop take it."""
    with patch.object(settings, 'TESTING', False):
        await bus.emit(event, payload)
        listener = asyncio.create_task(bus.listen())
        await asyncio.wait_for(until.wait(), timeout=5)
        # Let the loop finish the message it is holding (record + ACK).
        await asyncio.sleep(0.3)
        bus._stopping = True
        await asyncio.wait_for(listener, timeout=5)
        bus._stopping = False


async def _pending(bus: EventBus) -> int:
    assert bus._redis is not None
    summary = await bus._redis.xpending(bus._stream_name, bus._group_name)
    return int(summary['pending'] if isinstance(summary, dict) else summary[0])


async def _rows(sessions: Any) -> list[EventDelivery]:
    async with sessions() as db:
        return list((await db.execute(select(EventDelivery))).scalars().all())


async def _make_due(sessions: Any) -> None:
    """Skip the backoff wait: the schedule is tested on its own below."""
    async with sessions() as db:
        await db.execute(
            update(EventDelivery)
            .where(EventDelivery.status == 'retrying')
            .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()


async def _retry(sessions: Any, bus: EventBus) -> int:
    return await retry_failed_deliveries(sessions, bus)


def _failing(calls: list[str], seen: asyncio.Event, *, times: int) -> Callable:
    async def reprice_the_shelf(payload: EventPayload) -> None:
        calls.append('run')
        seen.set()
        if len(calls) <= times:
            raise RuntimeError('pricing service unreachable')

    return reprice_the_shelf


class TestAFailureOnTheStream:
    async def test_is_recorded_for_a_retry_and_the_message_is_acknowledged(
        self, bus: EventBus, sessions: Any
    ):
        calls: list[str] = []
        seen = asyncio.Event()
        handler = _failing(calls, seen, times=99)
        bus._listeners['item.created'] = [(handler, 100, None)]

        await _deliver(bus, TenantEventPayload(organization_id=str(uuid.uuid4())), seen)

        rows = await _rows(sessions)
        assert len(rows) == 1
        row = rows[0]
        assert row.status == 'retrying'
        assert row.attempts == 1
        assert row.handler == handler_name(handler)
        assert row.last_error == 'RuntimeError: pricing service unreachable'
        assert row.next_attempt_at is not None
        assert row.next_attempt_at > datetime.now(UTC)
        # Handed to the worker, so the stream is done with it.
        assert await _pending(bus) == 0

    async def test_that_cannot_be_recorded_stays_pending_for_redelivery(
        self, bus: EventBus
    ):
        """Acknowledging a failure nobody wrote down would be the old loss."""

        class Unreachable:
            def __call__(self) -> Unreachable:
                return self

            async def __aenter__(self) -> None:
                raise OSError('database unreachable')

            async def __aexit__(self, *exc: object) -> None:
                return None

        bus._session_factory = Unreachable()
        calls: list[str] = []
        seen = asyncio.Event()
        bus._listeners['item.created'] = [(_failing(calls, seen, times=99), 100, None)]

        await _deliver(bus, TenantEventPayload(organization_id=str(uuid.uuid4())), seen)

        assert await _pending(bus) == 1


class TestTheRetry:
    async def test_runs_only_the_failed_handler_so_the_notification_is_not_sent_twice(
        self, bus: EventBus, sessions: Any, org_with_admin: Organization
    ):
        """The handler contract: siblings that succeeded are not re-run."""
        calls: list[str] = []
        seen = asyncio.Event()

        async def tell_the_admins(payload: EventPayload) -> None:
            async with sessions() as db:
                await core_api.notifications.notify_org_admins_async(
                    db,
                    org_with_admin.id,
                    title={'en': 'New product'},
                    content={'en': 'A product was added.'},
                )
                await db.commit()

        bus._listeners['item.created'] = [
            (tell_the_admins, 10, None),
            (_failing(calls, seen, times=1), 20, None),
        ]

        await _deliver(
            bus, TenantEventPayload(organization_id=str(org_with_admin.id)), seen
        )
        await _make_due(sessions)
        assert await _retry(sessions, bus) == 1

        assert calls == ['run', 'run']
        [row] = await _rows(sessions)
        assert row.status == 'succeeded'
        assert row.attempts == 2
        async with sessions() as db:
            sent = (await db.execute(select(Notification))).scalars().all()
        assert len(sent) == 1

    async def test_a_redelivered_event_leaves_the_failed_handler_to_the_worker(
        self, bus: EventBus, sessions: Any
    ):
        """Reclaim brings the whole event back; the failed handler is not run twice."""
        calls: list[str] = []
        bus._listeners['item.created'] = [
            (_failing(calls, asyncio.Event(), times=99), 100, None)
        ]
        message = {
            'event': 'item.created',
            'event_id': uuid.uuid4().hex,
            'payload': json.dumps({'organization_id': str(uuid.uuid4())}),
        }

        assert await bus._handle_stream_message('1-0', message)
        assert await bus._handle_stream_message('1-0', message, redelivered=True)

        assert calls == ['run']
        assert len(await _rows(sessions)) == 1

    async def test_a_row_the_relay_published_twice_is_one_event(
        self, bus: EventBus, sessions: Any
    ):
        """The relay re-publishes a row whose commit it did not see; the copy
        is a fresh stream message, not a reclaim, and must still be known."""
        calls: list[str] = []
        bus._listeners['item.created'] = [
            (_failing(calls, asyncio.Event(), times=99), 100, None)
        ]
        message = {
            'event': 'item.created',
            'event_id': str(uuid.uuid4()),
            'sender_id': 'outbox-relay',
            'payload': json.dumps({'organization_id': str(uuid.uuid4())}),
        }

        assert await bus._handle_stream_message('1-0', message)
        assert await bus._handle_stream_message('2-0', message)

        assert calls == ['run']

    async def test_waits_twice_as_long_after_each_failure(
        self, bus: EventBus, sessions: Any
    ):
        calls: list[str] = []
        seen = asyncio.Event()
        bus._listeners['item.created'] = [(_failing(calls, seen, times=99), 100, None)]

        await _deliver(bus, TenantEventPayload(organization_id=str(uuid.uuid4())), seen)
        [first] = await _rows(sessions)
        assert first.next_attempt_at is not None
        first_wait = first.next_attempt_at - first.updated_at
        await _make_due(sessions)
        await _retry(sessions, bus)

        [second] = await _rows(sessions)
        assert second.attempts == 2
        assert second.next_attempt_at is not None
        second_wait = second.next_attempt_at - datetime.now(UTC)
        assert timedelta(seconds=25) < first_wait < timedelta(seconds=35)
        assert timedelta(seconds=55) < second_wait < timedelta(seconds=65)

    async def test_skips_what_is_not_due_yet(self, bus: EventBus, sessions: Any):
        calls: list[str] = []
        seen = asyncio.Event()
        bus._listeners['item.created'] = [(_failing(calls, seen, times=99), 100, None)]

        await _deliver(bus, TenantEventPayload(organization_id=str(uuid.uuid4())), seen)

        assert await _retry(sessions, bus) == 0
        assert calls == ['run']


class TestAHandlerThatKeepsFailing:
    async def test_is_parked_as_dead_and_the_admins_are_told_once(
        self, bus: EventBus, sessions: Any, org_with_admin: Organization
    ):
        calls: list[str] = []
        seen = asyncio.Event()
        bus._listeners['item.created'] = [(_failing(calls, seen, times=99), 100, None)]

        await _deliver(
            bus, TenantEventPayload(organization_id=str(org_with_admin.id)), seen
        )
        for _ in range(MAX_HANDLER_ATTEMPTS - 1):
            await _make_due(sessions)
            await _retry(sessions, bus)
        # A dead row is not picked up again.
        await _make_due(sessions)
        assert await _retry(sessions, bus) == 0

        assert len(calls) == MAX_HANDLER_ATTEMPTS
        [row] = await _rows(sessions)
        assert row.status == 'dead'
        assert row.attempts == MAX_HANDLER_ATTEMPTS
        assert row.next_attempt_at is None
        async with sessions() as db:
            [alert] = (await db.execute(select(Notification))).scalars().all()
        assert alert.type == 'error'
        assert alert.meta_data['type'] == 'event_delivery_dead'
        assert alert.meta_data['handler'] == row.handler
        assert row.handler in alert.content
        assert 'pricing service unreachable' in alert.content

        # The next event this broken handler loses does not ring the bell again.
        seen.clear()
        await _deliver(
            bus, TenantEventPayload(organization_id=str(org_with_admin.id)), seen
        )
        for _ in range(MAX_HANDLER_ATTEMPTS - 1):
            await _make_due(sessions)
            await _retry(sessions, bus)
        async with sessions() as db:
            alerts = (await db.execute(select(Notification))).scalars().all()
        assert len(alerts) == 1

    async def test_of_no_organization_is_told_to_the_superusers_once(
        self, bus: EventBus, sessions: Any, org_with_admin: Organization
    ):
        """An installation-wide event has no organization admins to tell, and
        was only recorded and logged. The instance's superusers can act on it,
        so they hear about it — in their own language, and once a day per
        handler, as the admins do."""
        async with sessions() as db:
            superuser = await ModuleTestHelper.create_user_async(
                db, org_with_admin, email=f'root_{uuid.uuid4().hex[:8]}@test.com'
            )
            superuser.is_superuser = True
            superuser.preferred_language = 'pl'
            await db.commit()

        async def _lose_one() -> None:
            calls: list[str] = []
            seen = asyncio.Event()
            # An event of the installation, not of an organization.
            bus._listeners[_INSTANCE_EVENT] = [
                (_failing(calls, seen, times=99), 100, None)
            ]
            await _deliver(bus, EventPayload(), seen, _INSTANCE_EVENT)
            for _ in range(MAX_HANDLER_ATTEMPTS - 1):
                await _make_due(sessions)
                await _retry(sessions, bus)

        await _lose_one()
        await _lose_one()

        rows = await _rows(sessions)
        assert [r.status for r in rows] == ['dead', 'dead']
        assert all(r.organization_id is None for r in rows)
        async with sessions() as db:
            [alert] = (
                (
                    await db.execute(
                        select(Notification).where(Notification.user_id == superuser.id)
                    )
                )
                .scalars()
                .all()
            )
        assert alert.type == 'error'
        assert alert.meta_data['handler'] == rows[0].handler
        assert alert.title == get_error_message('event_delivery_dead_title', 'pl')

    async def test_that_is_no_longer_subscribed_is_parked_at_once(
        self, bus: EventBus, sessions: Any
    ):
        calls: list[str] = []
        seen = asyncio.Event()
        bus._listeners['item.created'] = [(_failing(calls, seen, times=99), 100, None)]
        await _deliver(bus, TenantEventPayload(organization_id=str(uuid.uuid4())), seen)

        bus._listeners['item.created'] = []  # the module was switched off
        await _make_due(sessions)
        await _retry(sessions, bus)

        [row] = await _rows(sessions)
        assert row.status == 'dead'
        assert 'is subscribed any more' in (row.last_error or '')
        assert calls == ['run']


class TestTheHandlerName:
    async def test_names_the_module_function_not_the_subscription_wrapper(self):
        """The retry finds its handler by name, so ``wrapper`` would match anything."""
        from app.core._event_bus import event_bus

        async def recount_the_shelf(payload: EventPayload) -> None:
            return None

        before = list(event_bus._listeners.get('item.created', []))
        core_api.events.subscribe('item.created', recount_the_shelf)
        try:
            [(wrapper, _, _)] = [
                entry
                for entry in event_bus._listeners['item.created']
                if entry not in before
            ]
            assert wrapper is not recount_the_shelf
            assert event_bus.name_of(wrapper) == handler_name(recount_the_shelf)
            assert (
                event_bus.find_handler(
                    'item.created', handler_name(recount_the_shelf), None
                )
                is wrapper
            )
        finally:
            event_bus._listeners['item.created'] = before
