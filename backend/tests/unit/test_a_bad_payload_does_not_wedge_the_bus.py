"""A message that can never be parsed must not come back forever.

The stream consumer acknowledges a message only after the handler returns,
and reclaim exists to redeliver anything a crashed consumer left pending.
Between them they assume a failure is worth retrying. Building the payload
from JSON raises pydantic's ``ValidationError``, which was not in the
handler's except clause -- so a payload that does not fit the contract left
the method by exception, was never acknowledged, and came back on every
reclaim, forever, for a message no retry could ever fix.

Typed contracts are enforced when an event is emitted and were not when it
was delivered, which is exactly where the sender's own code stops being in
control -- the sender may be another node, another version, or a module.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core import _event_bus as event_bus_module
from app.core._event_bus import EventBus
from app.core.contracts import EventPayload

pytestmark = pytest.mark.unit


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.mark.unit
class TestAPayloadThatCannotBeParsed:
    async def test_broken_json_is_swallowed(self, bus: EventBus) -> None:
        bus._execute_local = AsyncMock()  # type: ignore[method-assign]

        await bus._handle_stream_message(
            '1-0', {'event': 'item.created', 'payload': '{not json'}
        )

        bus._execute_local.assert_not_called()

    async def test_a_payload_that_fails_the_contract_is_swallowed(
        self, bus: EventBus
    ) -> None:
        """Valid JSON, wrong shape: the case the except clause missed."""
        bus._execute_local = AsyncMock()  # type: ignore[method-assign]

        await bus._handle_stream_message(
            '1-0',
            {
                'event': 'item.created',
                # organization_id picks the tenant payload, and a list is
                # not a tenant id.
                'payload': '{"organization_id": ["not", "an", "id"]}',
            },
        )

        bus._execute_local.assert_not_called()

    async def test_it_is_logged_loudly_enough_to_notice(self, bus: EventBus) -> None:
        bus._execute_local = AsyncMock()  # type: ignore[method-assign]

        with patch.object(event_bus_module.logger, 'error') as logged:
            await bus._handle_stream_message(
                '1-0',
                {'event': 'item.created', 'payload': '{"organization_id": []}'},
            )

        logged.assert_called()


@pytest.mark.unit
class TestWhatStillGoesThrough:
    async def test_a_well_formed_payload_is_dispatched(self, bus: EventBus) -> None:
        """The control: the guard must not eat good messages."""
        received: list[EventPayload] = []

        async def handler(payload: EventPayload) -> None:
            received.append(payload)

        bus._listeners['item.created'] = [(handler, 100, None)]

        await bus._handle_stream_message(
            '1-0',
            {
                'event': 'item.created',
                'payload': '{"organization_id": "11111111-1111-1111-1111-111111111111"}',
            },
        )

        assert len(received) == 1
