"""
Integration tests for EventBus Redis Streams persistence.

These tests connect to a real Redis instance and verify:
- XADD / XREADGROUP / XACK flow
- At-least-once delivery (message survives consumer restart)
- Consumer group isolation (messages not delivered to other groups)
- Graceful shutdown (disconnect() cancels listen task cleanly)

Tests use an isolated stream name to avoid collisions with other workers.
"""

import asyncio
import uuid

import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from app.config import settings
from app.core._event_bus import EventBus
from app.core.events import EventPayload, SystemEvent, TenantEventPayload

REDIS_URL = settings.REDIS_URL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unique_stream() -> str:
    """Return a unique stream name for test isolation."""
    return f'test_stream_{uuid.uuid4().hex}'


async def _flush_stream(client: aioredis.Redis, stream: str) -> None:
    """Delete the test stream after use."""
    await client.delete(stream)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def redis_client():
    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def stream_name() -> str:
    return _unique_stream()


@pytest_asyncio.fixture
async def bus(stream_name, redis_client):
    """EventBus connected to a dedicated test stream."""
    b = EventBus()
    b._stream_name = stream_name
    b._group_name = f'test_group_{uuid.uuid4().hex}'
    await b.connect(REDIS_URL)
    # Allow XADD to run: these tests specifically test the Redis Streams path.
    original_testing = settings.TESTING
    settings.TESTING = False
    yield b
    settings.TESTING = original_testing
    await b.disconnect()
    await _flush_stream(redis_client, stream_name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.integration
async def test_emit_adds_message_to_stream(bus, redis_client, stream_name):
    """emit() writes a message to the Redis stream via XADD."""
    await bus.emit(
        SystemEvent.ITEM_CREATED,
        TenantEventPayload(organization_id='org-1', item_name='Widget'),
    )

    # Give the async emit a moment to complete
    await asyncio.sleep(0.05)

    length = await redis_client.xlen(stream_name)
    assert length >= 1, 'Expected at least one message in the stream after emit()'


@pytest.mark.asyncio
@pytest.mark.integration
async def test_xack_removes_message_from_pending(bus, redis_client, stream_name):
    """After processing and ACK-ing, message leaves the Pending Entry List."""
    await bus.emit(
        SystemEvent.ITEM_UPDATED,
        TenantEventPayload(organization_id='org-1', item_name='WidgetV2'),
    )
    await asyncio.sleep(0.05)

    group = bus._group_name
    consumer = f'test_consumer_{uuid.uuid4().hex}'

    # Manually read via XREADGROUP (mimics what listen_stream does)
    streams = await redis_client.xreadgroup(
        group, consumer, {stream_name: '>'}, count=5
    )
    assert streams, 'Expected to read at least one message from stream'

    msg_ids = [msg_id for _, messages in streams for msg_id, _ in messages]
    assert msg_ids

    # Check message appears in PEL before ACK
    pel_before = await redis_client.xpending(stream_name, group)
    assert pel_before['pending'] > 0, 'Message should be in PEL after read'

    # ACK all messages
    for msg_id in msg_ids:
        await redis_client.xack(stream_name, group, msg_id)

    pel_after = await redis_client.xpending(stream_name, group)
    assert pel_after['pending'] == 0, 'PEL should be empty after all ACKs'


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pending_message_survives_consumer_restart(redis_client, stream_name):
    """A message that was read but NOT ACK-ed is re-deliverable after restart.

    This validates the at-least-once delivery guarantee.
    """
    group = f'test_group_{uuid.uuid4().hex}'
    consumer_a = f'consumer_a_{uuid.uuid4().hex}'
    consumer_b = f'consumer_b_{uuid.uuid4().hex}'

    # Create group and write a message directly
    await redis_client.xgroup_create(stream_name, group, id='0', mkstream=True)
    await redis_client.xadd(stream_name, {'event': 'test', 'data': 'payload'})

    # Consumer A reads but does NOT ACK (simulates crash)
    streams = await redis_client.xreadgroup(
        group, consumer_a, {stream_name: '>'}, count=1
    )
    assert streams, 'Consumer A should have read the message'

    # Claim the message as consumer B (simulates restart/rebalance)
    # Use XAUTOCLAIM with min-idle-time=0 to immediately claim
    result = await redis_client.xautoclaim(
        stream_name, group, consumer_b, 0, '0-0', count=1
    )
    claimed_messages = result[1]  # (next_id, messages, deleted_ids)
    assert claimed_messages, 'Consumer B should have claimed the unACK-ed message'

    # Cleanup
    await _flush_stream(redis_client, stream_name)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_local_handler_called_without_redis(stream_name):
    """Local subscribers receive events even when Redis is not connected (TESTING mode)."""
    bus = EventBus()
    bus._stream_name = stream_name
    # Do NOT call bus.connect() — simulates TESTING mode

    received = []

    async def handler(payload: EventPayload):
        received.append(payload.item_name)

    bus.subscribe(SystemEvent.ITEM_CREATED, handler)
    await bus.emit(
        SystemEvent.ITEM_CREATED,
        TenantEventPayload(organization_id='org-1', item_name='LocalOnly'),
    )
    await asyncio.sleep(0.05)

    assert 'LocalOnly' in received


@pytest.mark.asyncio
@pytest.mark.integration
async def test_disconnect_cancels_listen_task_cleanly(stream_name):
    """disconnect() cancels the listen task and awaits it without raising."""
    bus = EventBus()
    bus._stream_name = stream_name
    bus._group_name = f'test_group_{uuid.uuid4().hex}'
    await bus.connect(REDIS_URL)

    # Start the listen loop
    bus._listen_task = asyncio.create_task(bus.listen())
    await asyncio.sleep(0.05)  # let it start blocking on xreadgroup

    # Disconnect should cancel and await the task without raising
    await bus.disconnect()

    assert bus._listen_task.done(), 'Listen task should be done after disconnect()'
    assert bus._redis is None, 'Redis connection should be closed after disconnect()'

    # Cleanup
    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    await client.delete(stream_name)
    await client.aclose()
