import asyncio
from unittest.mock import MagicMock

import pytest

from app.core._event_bus import EventBus
from app.core.context import ModuleContext
from app.core.events import EventPayload, SystemEvent, TenantEventPayload


@pytest.mark.asyncio
async def test_module_context_tenant_emit():
    mock_bus = MagicMock(spec=EventBus)
    mock_bus.emit = MagicMock(return_value=asyncio.Future())
    mock_bus.emit.return_value.set_result(None)

    # Initialize context with an organization (tenant)
    context = ModuleContext(event_bus=mock_bus, organization_id='tenant-123')

    await context.emit(SystemEvent.ITEM_CREATED, {'name': 'Test Item'})

    # Verify that the emit was wrapped in TenantEventPayload with the correct org ID
    mock_bus.emit.assert_called_once()
    args, _ = mock_bus.emit.call_args
    assert args[0] == SystemEvent.ITEM_CREATED
    payload = args[1]
    assert isinstance(payload, TenantEventPayload)
    assert payload.organization_id == 'tenant-123'
    assert payload.name == 'Test Item'


@pytest.mark.asyncio
async def test_module_context_global_emit():
    mock_bus = MagicMock(spec=EventBus)
    mock_bus.emit = MagicMock(return_value=asyncio.Future())
    mock_bus.emit.return_value.set_result(None)

    # Initialize context without an organization (e.g. core system background tasks)
    context = ModuleContext(event_bus=mock_bus, organization_id=None)

    await context.emit(SystemEvent.ITEM_CREATED, {'name': 'Global Item'})

    # Verify that it uses standard EventPayload
    mock_bus.emit.assert_called_once()
    args, _ = mock_bus.emit.call_args
    assert args[0] == SystemEvent.ITEM_CREATED
    payload = args[1]
    assert not isinstance(payload, TenantEventPayload)
    assert isinstance(payload, EventPayload)
    assert not hasattr(payload, 'organization_id')
    assert payload.name == 'Global Item'
