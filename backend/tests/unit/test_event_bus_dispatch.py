"""Unit tests for EventBus emit dispatch semantics.

Production mode is stream-only: ``emit`` performs a single XADD and handler
execution happens exclusively on the consumer-group worker that picks the
message up. TESTING keeps inline local dispatch. No Redis / Redis failure
falls back to in-process dispatch with a once-per-process warning.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import RedisError

import app.core._event_bus as event_bus_module
from app.config import settings
from app.core._event_bus import EventBus
from app.core._event_types import EventPayload, TenantEventPayload


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture(autouse=True)
def _reset_fallback_warning():
    event_bus_module._fallback_warned = False
    event_bus_module._unregistered_warned.clear()
    yield
    event_bus_module._fallback_warned = False
    event_bus_module._unregistered_warned.clear()


@pytest.mark.unit
class TestEmitPayloadValidation:
    """emit validates against the payload registry — one place, not
    emitter discipline. Registered names are coerced (fail-closed on a bad
    payload), unregistered names fail open with a once-per-name warning."""

    async def test_registered_event_payload_is_coerced(self, bus: EventBus):
        received = []

        async def handler(payload: EventPayload) -> None:
            received.append(payload)

        bus._listeners['module.enabled'] = [(handler, 100, None)]

        with patch.object(settings, 'TESTING', True):
            await bus.emit(
                'module.enabled',
                TenantEventPayload(organization_id='org-1', module_name='m'),
            )

        assert len(received) == 1
        assert type(received[0]).__name__ == 'ModuleEnabledPayload'

    async def test_registered_event_invalid_payload_raises(self, bus: EventBus):
        from app.core.contracts.events import EventValidationError

        with (
            patch.object(settings, 'TESTING', True),
            pytest.raises(EventValidationError),
        ):
            # module_name is required by the registered contract.
            await bus.emit('module.enabled', TenantEventPayload(organization_id='o'))

    async def test_unregistered_event_warns_once_and_dispatches(self, bus: EventBus):
        received = []

        async def handler(payload: EventPayload) -> None:
            received.append(payload)

        bus._listeners['custom.thing'] = [(handler, 100, None)]

        with (
            patch.object(settings, 'TESTING', True),
            patch.object(event_bus_module.logger, 'warning') as mock_warning,
        ):
            await bus.emit('custom.thing', EventPayload())
            await bus.emit('custom.thing', EventPayload())

        assert len(received) == 2
        contract_warnings = [
            c for c in mock_warning.call_args_list if 'payload contract' in str(c)
        ]
        assert len(contract_warnings) == 1

    async def test_emit_transactional_buffers_the_coerced_payload(self, bus: EventBus):
        db = MagicMock()
        db.info = {}

        with patch.object(settings, 'TESTING', True):
            await bus.emit_transactional(
                db,
                'module.enabled',
                TenantEventPayload(organization_id='org-1', module_name='m'),
            )

        _event, buffered = db.info['_pending_outbox_events'][0]
        assert type(buffered).__name__ == 'ModuleEnabledPayload'

    async def test_emit_transactional_invalid_payload_raises_before_buffering(
        self, bus: EventBus
    ):
        from app.core.contracts.events import EventValidationError

        db = MagicMock()
        db.info = {}

        with (
            patch.object(settings, 'TESTING', True),
            pytest.raises(EventValidationError),
        ):
            await bus.emit_transactional(
                db, 'module.enabled', TenantEventPayload(organization_id='o')
            )

        assert '_pending_outbox_events' not in db.info


@pytest.mark.unit
class TestEmitStreamOnly:
    async def test_prod_emit_only_xadds(self, bus: EventBus):
        """Prod + Redis: no local execution, exactly one XADD."""
        bus._redis = AsyncMock()
        bus._execute_local = AsyncMock()

        with patch.object(settings, 'TESTING', False):
            await bus.emit('test.event', EventPayload())

        bus._redis.xadd.assert_awaited_once()
        bus._execute_local.assert_not_called()

    async def test_prod_emit_xadd_failure_falls_back_local(self, bus: EventBus):
        bus._redis = AsyncMock()
        bus._redis.xadd.side_effect = RedisError('down')
        bus._execute_local = AsyncMock()

        with patch.object(settings, 'TESTING', False):
            await bus.emit('test.event', EventPayload())

        bus._execute_local.assert_awaited_once()
        assert event_bus_module._fallback_warned is True

    async def test_prod_emit_without_redis_falls_back_local(self, bus: EventBus):
        bus._redis = None
        bus._execute_local = AsyncMock()

        with patch.object(settings, 'TESTING', False):
            await bus.emit('test.event', EventPayload())

        bus._execute_local.assert_awaited_once()
        assert event_bus_module._fallback_warned is True

    async def test_fallback_warning_logged_once_per_process(self, bus: EventBus):
        bus._redis = None
        bus._execute_local = AsyncMock()

        with (
            patch.object(settings, 'TESTING', False),
            patch.object(event_bus_module.logger, 'warning') as mock_warning,
        ):
            await bus.emit('a', EventPayload())
            await bus.emit('b', EventPayload())

        fallback_warnings = [
            c for c in mock_warning.call_args_list if 'in-process' in str(c)
        ]
        assert len(fallback_warnings) == 1

    async def test_testing_emit_inline_no_xadd(self, bus: EventBus):
        """TESTING keeps the legacy inline dispatch and never touches Redis."""
        bus._redis = AsyncMock()
        calls: list[str] = []

        async def handler(payload: EventPayload) -> None:
            calls.append('ran')

        bus._listeners['test.event'] = [(handler, 100, None)]

        with patch.object(settings, 'TESTING', True):
            await bus.emit('test.event', EventPayload())

        bus._redis.xadd.assert_not_called()
        assert calls == ['ran']

    async def test_testing_fallback_does_not_warn(self, bus: EventBus):
        bus._redis = None
        bus._execute_local = AsyncMock()

        with patch.object(settings, 'TESTING', True):
            await bus.emit('test.event', EventPayload())

        assert event_bus_module._fallback_warned is False


@pytest.mark.unit
class TestStreamMessageSenderHandled:
    async def test_own_sender_id_message_is_processed(self, bus: EventBus):
        """The sender-skip was removed: with stream-only emit the consumer
        must also handle its own messages (it may be the only live node)."""
        executed: list[str] = []

        async def handler(payload: EventPayload) -> None:
            executed.append('ran')

        bus._listeners['item.created'] = [(handler, 100, None)]

        await bus._handle_stream_message(
            '1-0',
            {
                'event': 'item.created',
                'sender_id': bus._node_id,  # own message
                'payload': '{}',
            },
        )
        assert executed == ['ran']


@pytest.mark.unit
class TestTheEmitterIsNamed:
    """A stream message says which module emitted it, and a subscribed
    handler runs under the identity it registered with — the failure of a
    module's event can be traced back to the module, not just to the node
    that relayed it."""

    async def test_prod_xadd_names_the_emitting_module(self, bus: EventBus):
        from app.core.module_identity import module_scope

        bus._redis = AsyncMock()

        with patch.object(settings, 'TESTING', False), module_scope('webhooks'):
            await bus.emit('test.event', EventPayload())

        message = bus._redis.xadd.call_args.args[1]
        assert message['module'] == 'webhooks'

    async def test_core_emit_names_nobody(self, bus: EventBus):
        bus._redis = AsyncMock()

        with patch.object(settings, 'TESTING', False):
            await bus.emit('test.event', EventPayload())

        message = bus._redis.xadd.call_args.args[1]
        assert message['module'] == ''

    async def test_a_handler_runs_under_its_subscribers_identity(self, bus: EventBus):
        from app.core.module_identity import current_module, module_scope

        seen: list[str | None] = []

        async def handler(payload: EventPayload) -> None:
            seen.append(current_module())

        with module_scope('webhooks'):
            bus.subscribe('test.event', handler)

        with patch.object(settings, 'TESTING', True):
            await bus.emit('test.event', EventPayload())

        assert seen == ['webhooks']
        assert current_module() is None


@pytest.mark.unit
class TestEmitTransactionalTestingBuffer:
    """TESTING: emit_transactional buffers on the session; flush_pending
    dispatches inline AFTER the caller's commit (handlers read committed
    state from their own sessions)."""

    async def test_buffers_without_dispatch(self, bus: EventBus):
        executed: list[str] = []

        async def handler(payload: EventPayload) -> None:
            executed.append('ran')

        bus._listeners['item.created'] = [(handler, 100, None)]
        db = MagicMock()
        db.info = {}

        with patch.object(settings, 'TESTING', True):
            await bus.emit_transactional(
                db, 'item.created', TenantEventPayload(organization_id='org-1')
            )

        assert executed == []
        assert len(db.info['_pending_outbox_events']) == 1

    async def test_flush_pending_dispatches_inline_and_clears(self, bus: EventBus):
        executed: list[str] = []

        async def handler(payload: EventPayload) -> None:
            executed.append('ran')

        bus._listeners['item.created'] = [(handler, 100, None)]
        db = MagicMock()
        db.info = {}

        with patch.object(settings, 'TESTING', True):
            await bus.emit_transactional(
                db, 'item.created', TenantEventPayload(organization_id='org-1')
            )
            await bus.flush_pending(db)

        assert executed == ['ran']
        assert '_pending_outbox_events' not in db.info

    async def test_flush_pending_prod_is_noop(self, bus: EventBus):
        bus._execute_local = AsyncMock()
        db = MagicMock()
        db.info = {'_pending_outbox_events': [('item.created', EventPayload())]}

        with patch.object(settings, 'TESTING', False):
            await bus.flush_pending(db)

        bus._execute_local.assert_not_called()
        assert '_pending_outbox_events' not in db.info


@pytest.mark.unit
class TestEventNameResolution:
    async def test_unknown_event_dispatched_not_dropped(self, bus: EventBus):
        """Custom module events outside SystemEvent must flow too."""
        bus._execute_local = AsyncMock()

        await bus._handle_stream_message(
            '1-0', {'event': 'no.such.event', 'payload': '{}'}
        )

        bus._execute_local.assert_called_once()
        assert bus._execute_local.call_args.args[0] == 'no.such.event'

    async def test_missing_event_name_logged(self, bus: EventBus):
        with patch.object(event_bus_module.logger, 'warning') as mock_warning:
            await bus._handle_stream_message('1-0', {'payload': '{}'})
        mock_warning.assert_called()


@pytest.mark.unit
class TestOrgFilterGating:
    """Native per-org listener gating at dispatch time."""

    async def test_matching_org_delivered(self, bus: EventBus):
        received = []

        async def handler(payload: EventPayload) -> None:
            received.append(payload)

        bus.subscribe('module.enabled', handler, org_filter='org-1')

        await bus._execute_local(
            'module.enabled',
            payload=TenantEventPayload(organization_id='org-1', module_name='m'),
        )

        assert len(received) == 1

    async def test_other_org_skipped(self, bus: EventBus):
        received = []

        async def handler(payload: EventPayload) -> None:
            received.append(payload)

        bus.subscribe('module.enabled', handler, org_filter='org-1')

        await bus._execute_local(
            'module.enabled',
            payload=TenantEventPayload(organization_id='org-2', module_name='m'),
        )

        assert received == []

    async def test_non_tenant_payload_skipped_when_filtered(self, bus: EventBus):
        received = []

        async def handler(payload: EventPayload) -> None:
            received.append(payload)

        bus.subscribe('module.enabled', handler, org_filter='org-1')

        await bus._execute_local('module.enabled', payload=EventPayload())

        assert received == []

    async def test_unfiltered_listener_receives_everything(self, bus: EventBus):
        received = []

        async def handler(payload: EventPayload) -> None:
            received.append(payload)

        bus.subscribe('module.enabled', handler)

        await bus._execute_local(
            'module.enabled',
            payload=TenantEventPayload(organization_id='org-2', module_name='m'),
        )
        await bus._execute_local('module.enabled', payload=EventPayload())

        assert len(received) == 2
