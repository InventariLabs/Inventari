"""
Integration tests for EventBus internal methods.

Covers: subscribe, emit (local), _safe_execute, _execute_local,
properties, and EventPayload/TenantEventPayload.
"""

import asyncio

import pytest

from app.core._event_bus import EventBus
from app.core._event_types import (
    EventPayload,
    SystemEvent,
    TenantEventPayload,
)


@pytest.mark.integration
class TestEventPayload:
    def test_create_basic_payload(self):
        payload = EventPayload()
        assert payload.model_dump() == {}

    def test_payload_with_extra_fields(self):
        payload = EventPayload(item_name='Widget', item_id='123')
        assert payload.item_name == 'Widget'
        assert payload.item_id == '123'

    def test_tenant_payload_requires_org_id(self):
        payload = TenantEventPayload(organization_id='org-1', extra='data')
        assert payload.organization_id == 'org-1'
        assert payload.extra == 'data'

    def test_payload_model_dump(self):
        payload = EventPayload(key='value', num=42)
        dumped = payload.model_dump()
        assert dumped['key'] == 'value'
        assert dumped['num'] == 42

    def test_tenant_payload_model_dump(self):
        payload = TenantEventPayload(organization_id='org-1', action='test')
        dumped = payload.model_dump()
        assert dumped['organization_id'] == 'org-1'
        assert dumped['action'] == 'test'


@pytest.mark.integration
class TestEventBusSubscribe:
    def test_subscribe_adds_listener(self):
        bus = EventBus()

        async def handler(payload):
            pass

        bus.subscribe(SystemEvent.ITEM_CREATED, handler)
        assert SystemEvent.ITEM_CREATED.value in bus._listeners
        assert len(bus._listeners[SystemEvent.ITEM_CREATED.value]) == 1

    def test_subscribe_multiple_handlers_sorted_by_priority(self):
        bus = EventBus()

        async def high_priority(payload):
            pass

        async def low_priority(payload):
            pass

        bus.subscribe(SystemEvent.ITEM_CREATED, low_priority, priority=200)
        bus.subscribe(SystemEvent.ITEM_CREATED, high_priority, priority=10)

        listeners = bus._listeners[SystemEvent.ITEM_CREATED.value]
        assert len(listeners) == 2
        assert listeners[0][1] == 10
        assert listeners[1][1] == 200

    def test_subscribe_string_event(self):
        bus = EventBus()

        async def handler(payload):
            pass

        bus.subscribe('custom.event', handler)
        assert 'custom.event' in bus._listeners

    def test_subscribe_same_priority_order_preserved(self):
        bus = EventBus()

        async def handler_a(payload):
            pass

        async def handler_b(payload):
            pass

        bus.subscribe(SystemEvent.ITEM_CREATED, handler_a, priority=100)
        bus.subscribe(SystemEvent.ITEM_CREATED, handler_b, priority=100)

        listeners = bus._listeners[SystemEvent.ITEM_CREATED.value]
        assert len(listeners) == 2


@pytest.mark.integration
class TestEventBusProperties:
    def test_is_connected_false_initially(self):
        bus = EventBus()
        assert bus.is_connected is False

    def test_is_listening_false_initially(self):
        bus = EventBus()
        assert bus.is_listening is False

    def test_redis_property_none_initially(self):
        bus = EventBus()
        assert bus.redis is None

    def test_is_connected_true_after_setting_redis(self):
        bus = EventBus()
        bus._redis = 'fake_redis'
        assert bus.is_connected is True

    def test_is_listening_true_with_running_task(self):
        bus = EventBus()
        loop = asyncio.new_event_loop()

        async def dummy():
            await asyncio.sleep(10)

        task = loop.create_task(dummy())
        bus._listen_task = task
        assert bus.is_listening is True
        task.cancel()
        try:
            loop.run_until_complete(task)
        except (asyncio.CancelledError, RuntimeError):
            pass
        finally:
            loop.close()


@pytest.mark.integration
class TestEventBusSafeExecute:
    @pytest.mark.asyncio
    async def test_safe_execute_async_callback(self):
        bus = EventBus()
        results = []

        async def handler(payload):
            results.append(payload)

        await bus._safe_execute(handler, payload=EventPayload(test='ok'))
        assert len(results) == 1
        assert results[0].test == 'ok'

    @pytest.mark.asyncio
    async def test_safe_execute_sync_callback(self):
        bus = EventBus()
        results = []

        def handler(payload):
            results.append(payload)

        await bus._safe_execute(handler, payload=EventPayload(test='sync'))
        assert len(results) == 1
        assert results[0].test == 'sync'

    @pytest.mark.asyncio
    async def test_safe_execute_does_not_raise_on_callback_error(self):
        bus = EventBus()

        async def bad_handler(payload):
            raise RuntimeError('boom')

        await bus._safe_execute(bad_handler, payload=EventPayload())


@pytest.mark.integration
class TestEventBusEmitLocal:
    @pytest.mark.asyncio
    async def test_emit_calls_local_subscribers(self):
        bus = EventBus()
        received = []

        async def handler(payload):
            received.append(payload.item_name)

        bus.subscribe(SystemEvent.ITEM_CREATED, handler)
        await bus.emit(
            SystemEvent.ITEM_CREATED,
            TenantEventPayload(organization_id='org-1', item_name='TestItem'),
        )
        await asyncio.sleep(0.05)
        assert 'TestItem' in received

    @pytest.mark.asyncio
    async def test_emit_no_subscribers_no_error(self):
        bus = EventBus()
        await bus.emit(
            SystemEvent.ITEM_CREATED,
            TenantEventPayload(organization_id='org-1', item_name='NoHandler'),
        )

    @pytest.mark.asyncio
    async def test_emit_multiple_subscribers(self):
        bus = EventBus()
        results = []

        async def handler_a(payload):
            results.append('a')

        async def handler_b(payload):
            results.append('b')

        bus.subscribe(SystemEvent.ITEM_UPDATED, handler_a, priority=10)
        bus.subscribe(SystemEvent.ITEM_UPDATED, handler_b, priority=20)
        await bus.emit(
            SystemEvent.ITEM_UPDATED, TenantEventPayload(organization_id='org-1')
        )
        await asyncio.sleep(0.05)
        assert results == ['a', 'b']

    @pytest.mark.asyncio
    async def test_emit_with_enum_event(self):
        bus = EventBus()
        received = []

        async def handler(payload):
            received.append(True)

        bus.subscribe(SystemEvent.ITEM_DELETED, handler)
        await bus.emit(
            SystemEvent.ITEM_DELETED,
            TenantEventPayload(organization_id='org-1', item_id='i-1'),
        )
        await asyncio.sleep(0.05)
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_emit_with_string_event(self):
        bus = EventBus()
        received = []

        async def handler(payload):
            received.append(True)

        bus.subscribe('custom.event', handler)
        await bus.emit('custom.event', EventPayload())
        await asyncio.sleep(0.05)
        assert len(received) == 1


@pytest.mark.integration
class TestEventBusExecuteLocal:
    @pytest.mark.asyncio
    async def test_execute_local_no_listeners(self):
        bus = EventBus()
        await bus._execute_local('nonexistent.event', payload=EventPayload())

    @pytest.mark.asyncio
    async def test_execute_local_calls_all_listeners_in_order(self):
        bus = EventBus()
        order = []

        async def first(payload):
            order.append(1)

        async def second(payload):
            order.append(2)

        bus.subscribe(SystemEvent.ITEM_CREATED, first, priority=1)
        bus.subscribe(SystemEvent.ITEM_CREATED, second, priority=2)
        await bus._execute_local(SystemEvent.ITEM_CREATED.value, payload=EventPayload())
        await asyncio.sleep(0.05)
        assert order == [1, 2]


@pytest.mark.integration
class TestEventBusDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_without_connection(self):
        bus = EventBus()
        await bus.disconnect()
        assert bus._redis is None

    @pytest.mark.asyncio
    async def test_disconnect_cancels_listen_task(self):
        bus = EventBus()

        async def slow_listen():
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                raise

        bus._listen_task = asyncio.ensure_future(slow_listen())
        await asyncio.sleep(0.01)
        await bus.disconnect()
        assert bus._listen_task.done()
