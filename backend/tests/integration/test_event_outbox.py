"""Integration tests for the transactional outbox + relay.

- emit_transactional writes an outbox row in the caller's transaction:
  rollback drops it, commit keeps it unpublished until the relay runs.
- The relay publishes each committed row to the event stream exactly once
  and marks it published; a second relay run is a no-op.
- Rows left unpublished (crash between XADD and commit) are re-published
  by the next relay run (at-least-once).
"""

import uuid
from contextlib import nullcontext
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.core._event_bus import EventBus
from app.core._event_types import EventPayload
from app.core.outbox_relay import relay_outbox_batch


@pytest.fixture
async def session_factory(async_engine_fixture: Any, setup_test_db: Any):
    factory = async_sessionmaker(
        async_engine_fixture, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        await session.execute(text('TRUNCATE event_outbox RESTART IDENTITY CASCADE'))
        await session.commit()
    return factory


@pytest.fixture
async def bus() -> EventBus:
    """Fresh EventBus on a unique stream, connected to real Redis."""
    bus = EventBus()
    bus._stream_name = f'outbox_test_stream_{uuid.uuid4().hex[:12]}'
    bus._group_name = f'outbox_test_group_{uuid.uuid4().hex[:12]}'
    await bus.connect(settings.REDIS_URL)
    assert bus._redis is not None, 'test requires a reachable Redis'
    yield bus
    assert bus._redis is not None
    await bus._redis.delete(bus._stream_name)
    await bus.disconnect()


async def _count_rows(session_factory: Any, **where: Any) -> int:
    async with session_factory() as session:
        rows = (
            (await session.execute(text('SELECT * FROM event_outbox'))).mappings().all()
        )
        return sum(
            1
            for r in rows
            if all(
                (r[k] == v if v is not None else r[k] is None) for k, v in where.items()
            )
        )


@pytest.mark.integration
class TestEmitTransactional:
    async def test_commit_keeps_row_unpublished(self, session_factory: Any) -> None:
        org_id = uuid.uuid4()
        bus = EventBus()  # no Redis needed for the write path
        with patch.object(settings, 'TESTING', False):
            async with session_factory() as session:
                await bus.emit_transactional(
                    session,
                    'item.created',
                    EventPayload(
                        **{'organization_id': str(org_id), 'detail': 'committed'}
                    ),
                )
                await session.commit()

        assert await _count_rows(session_factory) == 1
        assert await _count_rows(session_factory, published_at=None) == 1

    async def test_rollback_drops_row(self, session_factory: Any) -> None:
        bus = EventBus()
        with patch.object(settings, 'TESTING', False):
            async with session_factory() as session:
                await bus.emit_transactional(
                    session,
                    'item.created',
                    EventPayload(
                        **{
                            'organization_id': str(uuid.uuid4()),
                            'detail': 'rolled-back',
                        }
                    ),
                )
                await session.rollback()

        assert await _count_rows(session_factory) == 0

    async def test_non_tenant_event_has_null_org(self, session_factory: Any) -> None:
        bus = EventBus()
        with patch.object(settings, 'TESTING', False):
            async with session_factory() as session:
                await bus.emit_transactional(
                    session, 'system.ping', EventPayload(**{'detail': 'global'})
                )
                await session.commit()

        assert await _count_rows(session_factory, organization_id=None) == 1


@pytest.mark.integration
class TestTheEmitterTravelsWithTheEvent:
    """A stream message says which module emitted it. The sender is a node
    UUID, so before the emitter rode in the row, a module's event that
    broke a consumer could not be traced back to the module."""

    async def _write_row(self, session_factory: Any, emitter: str | None) -> None:
        from app.core.module_identity import module_scope

        bus = EventBus()
        with patch.object(settings, 'TESTING', False):
            scope = module_scope(emitter) if emitter else nullcontext()
            with scope:
                async with session_factory() as session:
                    await bus.emit_transactional(
                        session,
                        'item.created',
                        EventPayload(
                            **{
                                'organization_id': str(uuid.uuid4()),
                                'detail': 'x',
                            }
                        ),
                    )
                    await session.commit()

    async def test_the_row_records_the_emitting_module(
        self, session_factory: Any
    ) -> None:
        await self._write_row(session_factory, emitter='webhooks')

        async with session_factory() as session:
            emitter = (
                await session.execute(text('SELECT emitter_module FROM event_outbox'))
            ).scalar()
        assert emitter == 'webhooks'

    async def test_core_emission_records_nobody(self, session_factory: Any) -> None:
        await self._write_row(session_factory, emitter=None)

        async with session_factory() as session:
            emitter = (
                await session.execute(text('SELECT emitter_module FROM event_outbox'))
            ).scalar()
        assert emitter is None

    async def test_the_relayed_message_names_the_module(
        self, session_factory: Any, bus: EventBus
    ) -> None:
        await self._write_row(session_factory, emitter='webhooks')

        with patch('app.core.outbox_relay.event_bus', bus):
            async with session_factory() as session:
                assert await relay_outbox_batch(session) == 1

        assert bus._redis is not None
        messages = await bus._redis.xrange(bus._stream_name)
        assert [data['module'] for _, data in messages] == ['webhooks']


@pytest.mark.integration
class TestOutboxRelay:
    async def _write_row(
        self, session_factory: Any, event: str = 'item.created'
    ) -> None:
        bus = EventBus()
        with patch.object(settings, 'TESTING', False):
            async with session_factory() as session:
                await bus.emit_transactional(
                    session,
                    event,
                    EventPayload(
                        **{'organization_id': str(uuid.uuid4()), 'detail': 'x'}
                    ),
                )
                await session.commit()

    async def test_relay_publishes_exactly_once(
        self, session_factory: Any, bus: EventBus
    ) -> None:
        await self._write_row(session_factory)

        with patch('app.core.outbox_relay.event_bus', bus):
            async with session_factory() as session:
                published = await relay_outbox_batch(session)

        assert published == 1
        assert await _count_rows(session_factory) == 1
        # No unpublished rows remain.
        assert await _count_rows(session_factory, published_at=None) == 0

        assert bus._redis is not None
        length = await bus._redis.xlen(bus._stream_name)
        assert length == 1

        # Second relay run: nothing left to publish.
        with patch('app.core.outbox_relay.event_bus', bus):
            async with session_factory() as session:
                published_again = await relay_outbox_batch(session)
        assert published_again == 0
        assert await bus._redis.xlen(bus._stream_name) == 1

    async def test_relay_republishes_after_crash_window(
        self, session_factory: Any, bus: EventBus
    ) -> None:
        """Crash between XADD and commit: the row stays unpublished, so the
        next relay run re-publishes it (at-least-once, documented)."""
        await self._write_row(session_factory)

        assert bus._redis is not None
        # Simulate a successful XADD whose marking transaction died.
        await bus._redis.xadd(
            bus._stream_name,
            {'event': 'item.created', 'sender_id': 'outbox-relay', 'payload': '{}'},
        )

        with patch('app.core.outbox_relay.event_bus', bus):
            async with session_factory() as session:
                published = await relay_outbox_batch(session)

        assert published == 1
        assert await _count_rows(session_factory, published_at=None) == 0
        # Stream has the crashed attempt + the re-published one.
        assert await bus._redis.xlen(bus._stream_name) == 2

    async def test_a_republished_row_is_the_same_event_to_the_delivery_log(
        self, session_factory: Any, bus: EventBus
    ) -> None:
        """Both copies carry the row id, so a handler that failed on the
        first is not run a second time off the duplicate."""
        await self._write_row(session_factory)
        async with session_factory() as session:
            [row_id] = (
                await session.execute(text('SELECT id FROM event_outbox'))
            ).scalars()

        with patch('app.core.outbox_relay.event_bus', bus):
            async with session_factory() as session:
                await relay_outbox_batch(session)
            async with session_factory() as session:
                await session.execute(
                    text('UPDATE event_outbox SET published_at = NULL')
                )
                await session.commit()
            async with session_factory() as session:
                await relay_outbox_batch(session)

        assert bus._redis is not None
        messages = await bus._redis.xrange(bus._stream_name)
        assert [data['event_id'] for _, data in messages] == [str(row_id)] * 2

    async def test_relay_without_redis_is_noop(self, session_factory: Any) -> None:
        await self._write_row(session_factory)
        bus = EventBus()  # never connected → redis None
        with patch('app.core.outbox_relay.event_bus', bus):
            async with session_factory() as session:
                published = await relay_outbox_batch(session)
        assert published == 0
        assert await _count_rows(session_factory, published_at=None) == 1

    async def test_relay_batch_limit(self, session_factory: Any, bus: EventBus) -> None:
        for _ in range(5):
            await self._write_row(session_factory)

        with patch('app.core.outbox_relay.event_bus', bus):
            async with session_factory() as session:
                published = await relay_outbox_batch(session, batch_limit=3)

        assert published == 3
        assert await _count_rows(session_factory, published_at=None) == 2
