"""Integration test: EventBus stream-only dispatch across two nodes.

Two EventBus instances ("nodes") share one Redis stream + consumer group.
An event emitted by node A must execute its handlers exactly once across the
cluster — the consumer group delivers each message to exactly one consumer,
and the removed sender-skip means the sender's own node may be that consumer.
"""

import asyncio
import uuid
from unittest.mock import patch

import pytest

from app.config import settings
from app.core._event_bus import EventBus
from app.core._event_types import EventPayload, TenantEventPayload


async def _make_bus(stream: str, group: str) -> EventBus:
    bus = EventBus()
    bus._stream_name = stream
    bus._group_name = group
    await bus.connect(settings.REDIS_URL)
    assert bus._redis is not None, 'test requires a reachable Redis'
    return bus


async def _consume_once(bus: EventBus) -> int:
    """Read pending new messages for this consumer and handle them inline.

    Returns the number of messages delivered to this consumer.
    """
    assert bus._redis is not None
    streams = await bus._redis.xreadgroup(
        bus._group_name, bus._node_id, {bus._stream_name: '>'}, count=10, block=200
    )
    delivered = 0
    for _stream, messages in streams or []:
        for msg_id, data in messages:
            await bus._handle_stream_message(msg_id, data)
            await bus._redis.xack(bus._stream_name, bus._group_name, msg_id)
            delivered += 1
    return delivered


@pytest.mark.integration
class TestStreamOnlyDispatch:
    async def test_event_executed_exactly_once_across_two_nodes(self):
        stream = f'test_stream_{uuid.uuid4().hex[:12]}'
        group = f'test_group_{uuid.uuid4().hex[:12]}'
        node_a = await _make_bus(stream, group)
        node_b = await _make_bus(stream, group)

        executions: list[str] = []

        async def handler_a(payload: EventPayload) -> None:
            executions.append('A')

        async def handler_b(payload: EventPayload) -> None:
            executions.append('B')

        node_a._listeners['item.created'] = [(handler_a, 100, None)]
        node_b._listeners['item.created'] = [(handler_b, 100, None)]

        try:
            # Prod path: emit is stream-only.
            with patch.object(settings, 'TESTING', False):
                await node_a.emit(
                    'item.created', TenantEventPayload(organization_id='org-1')
                )

            # Node B polls first and wins the single delivery.
            delivered_b = await _consume_once(node_b)
            delivered_a = await _consume_once(node_a)

            assert delivered_b == 1
            assert delivered_a == 0
            assert executions == ['B']
        finally:
            assert node_a._redis is not None
            await node_a._redis.delete(stream)
            await node_a.disconnect()
            await node_b.disconnect()

    async def test_sender_node_handles_own_message_when_sole_consumer(self):
        """If the emitter is the only live consumer, its own message is
        still handled (sender-skip removed) — never left unprocessed."""
        stream = f'test_stream_{uuid.uuid4().hex[:12]}'
        group = f'test_group_{uuid.uuid4().hex[:12]}'
        node_a = await _make_bus(stream, group)

        executions: list[str] = []

        async def handler_a(payload: EventPayload) -> None:
            executions.append('A')

        node_a._listeners['item.created'] = [(handler_a, 100, None)]

        try:
            with patch.object(settings, 'TESTING', False):
                await node_a.emit(
                    'item.created', TenantEventPayload(organization_id='org-1')
                )

            delivered = await _consume_once(node_a)
            assert delivered == 1
            assert executions == ['A']
        finally:
            assert node_a._redis is not None
            await node_a._redis.delete(stream)
            await node_a.disconnect()

    async def test_concurrent_consumers_still_single_execution(self):
        """Both nodes poll concurrently for one message — group semantics
        guarantee exactly one handler execution regardless of the winner."""
        stream = f'test_stream_{uuid.uuid4().hex[:12]}'
        group = f'test_group_{uuid.uuid4().hex[:12]}'
        node_a = await _make_bus(stream, group)
        node_b = await _make_bus(stream, group)

        executions: list[str] = []

        async def handler(payload: EventPayload) -> None:
            executions.append('ran')

        node_a._listeners['item.created'] = [(handler, 100, None)]
        node_b._listeners['item.created'] = [(handler, 100, None)]

        try:
            with patch.object(settings, 'TESTING', False):
                await node_a.emit(
                    'item.created', TenantEventPayload(organization_id='org-1')
                )

            delivered = await asyncio.gather(
                _consume_once(node_a), _consume_once(node_b)
            )
            assert sum(delivered) == 1
            assert len(executions) == 1
        finally:
            assert node_a._redis is not None
            await node_a._redis.delete(stream)
            await node_a.disconnect()
            await node_b.disconnect()
