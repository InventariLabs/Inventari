"""Unit tests for the core_api.events facade."""

import pytest

from app.core._event_bus import event_bus
from app.core.contracts.events import (
    EventPayload,
    EventValidationError,
    ItemQuantityEventPayload,
    TenantEventPayload,
)
from app.core.exceptions import ContractViolationError
from app.core.public_api import core_api


@pytest.fixture
def cleanup_listeners():
    """Remove listeners registered during a test."""
    before = {k: len(v) for k, v in event_bus._listeners.items()}
    yield
    for name in list(event_bus._listeners):
        keep = before.get(name, 0)
        event_bus._listeners[name] = event_bus._listeners[name][:keep]


class _FakeDb:
    """Minimal stand-in for AsyncSession in TESTING buffered mode."""

    def __init__(self):
        self.info = {}


@pytest.mark.asyncio
class TestEmit:
    async def test_emit_valid_payload_dispatches_typed(self, cleanup_listeners):
        received = []
        core_api.events.subscribe('item.used', received.append)

        await core_api.events.emit_async(
            'item.used',
            {
                'organization_id': 'org-1',
                'item': {'id': 'x'},
                'quantity': 2.0,
                'user_id': 'u-1',
            },
        )

        assert len(received) == 1
        assert isinstance(received[0], ItemQuantityEventPayload)
        assert received[0].organization_id == 'org-1'
        assert received[0].quantity == 2.0

    async def test_emit_invalid_payload_rejected(self, cleanup_listeners):
        received = []
        core_api.events.subscribe('item.used', received.append)

        with pytest.raises(EventValidationError):
            await core_api.events.emit_async(
                'item.used',
                {'organization_id': 'org-1', 'quantity': 'a lot', 'user_id': 'u-1'},
            )
        assert received == []

    async def test_emit_rejects_non_namespaced_custom_event(self, cleanup_listeners):
        with pytest.raises(ContractViolationError, match='namespaced|<module>'):
            await core_api.events.emit_async('plainname', {'x': 1})

    async def test_emit_custom_namespaced_event_fails_open(self, cleanup_listeners):
        received = []
        core_api.events.subscribe('rental.reservation_created', received.append)

        await core_api.events.emit_async('rental.reservation_created', {'x': 1})

        assert len(received) == 1
        assert type(received[0]) is EventPayload

    async def test_emit_system_event_enum_accepted(self, cleanup_listeners):
        from app.core._event_types import SystemEvent

        received = []
        core_api.events.subscribe(SystemEvent.MODULE_ENABLED, received.append)

        await core_api.events.emit_async(
            SystemEvent.MODULE_ENABLED,
            {'organization_id': 'org-1', 'module_name': 'recipes'},
        )

        assert len(received) == 1
        assert received[0].module_name == 'recipes'


@pytest.mark.asyncio
class TestSubscribeOrgFilter:
    async def test_other_org_event_skipped(self, cleanup_listeners):
        received = []
        core_api.events.subscribe('module.enabled', received.append, org_filter='org-1')

        await core_api.events.emit_async(
            'module.enabled', {'organization_id': 'org-2', 'module_name': 'm'}
        )

        assert received == []

    async def test_same_org_event_delivered(self, cleanup_listeners):
        received = []
        core_api.events.subscribe('module.enabled', received.append, org_filter='org-1')

        await core_api.events.emit_async(
            'module.enabled', {'organization_id': 'org-1', 'module_name': 'm'}
        )

        assert len(received) == 1

    async def test_unfiltered_subscription_receives_all_orgs(self, cleanup_listeners):
        received = []
        core_api.events.subscribe('module.enabled', received.append)

        await core_api.events.emit_async(
            'module.enabled', {'organization_id': 'org-2', 'module_name': 'm'}
        )

        assert len(received) == 1

    async def test_non_tenant_payload_skipped_when_filtered(self, cleanup_listeners):
        received = []
        core_api.events.subscribe('rental.ping', received.append, org_filter='org-1')

        await core_api.events.emit_async('rental.ping', {'x': 1})

        assert received == []

    async def test_sync_handler_supported(self, cleanup_listeners):
        received = []
        core_api.events.subscribe('module.enabled', lambda p: received.append(p))

        await core_api.events.emit_async(
            'module.enabled', {'organization_id': 'o', 'module_name': 'm'}
        )

        assert len(received) == 1


@pytest.mark.asyncio
class TestEmitTransactional:
    async def test_buffered_and_flushed_after_commit(self, cleanup_listeners):
        received = []
        core_api.events.subscribe('document.completed', received.append)
        db = _FakeDb()

        await core_api.events.emit_transactional_async(
            db,
            'document.completed',
            {
                'organization_id': 'org-1',
                'document_id': 'd-1',
                'document_type': 'RECEIPT',
                'lines': [],
            },
        )
        # TESTING: buffered on the session, not dispatched yet
        assert received == []

        await core_api.events.flush_pending_async(db)
        assert len(received) == 1
        assert isinstance(received[0], TenantEventPayload)
        assert received[0].document_id == 'd-1'

    async def test_invalid_payload_rejected_before_buffering(self):
        db = _FakeDb()
        with pytest.raises(EventValidationError):
            await core_api.events.emit_transactional_async(
                db, 'document.completed', {'document_type': 'RECEIPT'}
            )
        assert db.info == {}


class TestRegisteredEvents:
    def test_returns_sorted_mapping(self):
        catalog = core_api.events.registered_events()
        assert catalog['item.used'] == 'ItemQuantityEventPayload'
        assert list(catalog) == sorted(catalog)
