"""Unit tests for ``emit_safe`` / ``emit_transactional_safe`` (dedup 4.3).

These replace eight hand-rolled ``try: await event_bus.emit(...) except ...:
logger.warning(...)`` blocks. The contract they must hold is narrow but
load-bearing: a broken subscriber must never roll back the business
operation that published the event.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core._event_types import EventPayload
from app.core.events import emit_safe, emit_transactional_safe

pytestmark = pytest.mark.asyncio


#: A namespaced event with no registered contract type, so the registry lets
#: it through permissively. Using a *registered* event here (ITEM_CREATED) made
#: the swallow tests pass for the wrong reason: validation rejected the payload
#: before the patched bus was ever reached, so they proved nothing about a
#: failing subscriber.
PROBE_EVENT = 'dedup.probe'


@pytest.fixture
def payload() -> dict[str, str]:
    return {'organization_id': str(uuid4())}


class TestEmitSafe:
    async def test_forwards_to_the_event_bus(self, payload: dict[str, str]) -> None:
        with patch('app.core.events.event_bus.emit', new=AsyncMock()) as emit:
            await emit_safe(PROBE_EVENT, payload)
        # Routed through core_api.events (4.5), so the bus receives the
        # resolved event *name* and a registry-validated payload.
        emit.assert_awaited_once()
        assert emit.await_args.args[0] == PROBE_EVENT

    async def test_a_mapping_is_coerced_to_its_registered_contract_type(self) -> None:
        """The reason to go through the facade rather than the raw bus.

        Passing a dict lets the registry build the specific payload class;
        the raw bus would have shipped whatever generic model the caller
        happened to construct. Note the asymmetry this creates: a generic
        ``EventPayload`` instance is *rejected* where a specific type is
        registered, because pydantic will not re-validate one model class
        into another — call sites must pass mappings.
        """
        from app.modules.equipment.events import EquipmentEvent

        with patch('app.core.events.event_bus.emit', new=AsyncMock()) as emit:
            await emit_safe(
                EquipmentEvent.CHECKOUT,
                {
                    'organization_id': str(uuid4()),
                    'assignment_id': str(uuid4()),
                    'item_id': str(uuid4()),
                    'item_name': 'Drill',
                    'assigned_to_name': 'Ada',
                    'user_id': str(uuid4()),
                },
            )
        emit.assert_awaited_once()
        assert type(emit.await_args.args[1]).__name__ == 'EquipmentCheckoutPayload'

    async def test_swallows_a_failing_subscriber(self, payload: dict[str, str]) -> None:
        """The whole point: emission failure must not reach the caller."""
        failing = AsyncMock(side_effect=RuntimeError('subscriber exploded'))
        with patch('app.core.events.event_bus.emit', new=failing):
            await emit_safe(PROBE_EVENT, payload)  # must not raise

    @pytest.mark.parametrize(
        'exc', [RuntimeError('boom'), ValueError('bad'), TypeError('worse')]
    )
    async def test_swallows_every_exception_type(
        self, payload: dict[str, str], exc: Exception
    ) -> None:
        """Wider than the `(RuntimeError, ValueError, TypeError)` tuple the
        warehouse module used — a delivery failure of any kind is still a
        delivery failure."""
        with patch('app.core.events.event_bus.emit', new=AsyncMock(side_effect=exc)):
            await emit_safe(PROBE_EVENT, payload)

    async def test_logs_the_label_when_given(self, payload: dict[str, str]) -> None:
        with (
            patch(
                'app.core.events.event_bus.emit',
                new=AsyncMock(side_effect=RuntimeError('boom')),
            ),
            patch('app.core.events.logger.warning') as warn,
        ):
            await emit_safe(PROBE_EVENT, payload, label='[eq] CHECKOUT')
        assert warn.call_args.args[1] == '[eq] CHECKOUT'

    async def test_falls_back_to_the_event_name_without_a_label(
        self, payload: dict[str, str]
    ) -> None:
        with (
            patch(
                'app.core.events.event_bus.emit',
                new=AsyncMock(side_effect=RuntimeError('boom')),
            ),
            patch('app.core.events.logger.warning') as warn,
        ):
            await emit_safe(PROBE_EVENT, payload)
        assert warn.call_args.args[1] == PROBE_EVENT


class TestEmitTransactionalSafe:
    async def test_forwards_db_and_event(self, payload: dict[str, str]) -> None:
        db = object()
        with patch(
            'app.core.events.event_bus.emit_transactional', new=AsyncMock()
        ) as emit:
            await emit_transactional_safe(db, PROBE_EVENT, payload)  # type: ignore[arg-type]
        emit.assert_awaited_once()
        assert emit.await_args.args[0] is db
        assert emit.await_args.args[1] == PROBE_EVENT

    async def test_swallows_failures(self, payload: dict[str, str]) -> None:
        with patch(
            'app.core.events.event_bus.emit_transactional',
            new=AsyncMock(side_effect=RuntimeError('outbox down')),
        ):
            await emit_transactional_safe(None, PROBE_EVENT, payload)  # type: ignore[arg-type]


class TestPayloadConstructionIsNotCovered:
    """Deliberate narrowing versus the blocks these helpers replaced.

    Those wrapped payload construction inside the same ``try``, so a coding
    mistake in the payload was logged at WARNING and the event silently
    dropped. Building the payload at the call site means such a bug now fails
    loudly, which is what a bug should do.
    """

    async def test_a_payload_bug_raises_before_emit_is_reached(self) -> None:
        def build_payload() -> EventPayload:
            raise TypeError('bug while building the payload')

        with patch('app.core.events.event_bus.emit', new=AsyncMock()) as emit:
            # The argument is evaluated before the helper is entered, so the
            # helper's try/except cannot and must not cover it.
            with pytest.raises(TypeError, match='bug while building'):
                await emit_safe(PROBE_EVENT, build_payload())
        emit.assert_not_awaited()
