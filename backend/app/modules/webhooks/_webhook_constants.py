import json
from datetime import UTC, datetime
from typing import Any

from app.core.events import EventPayload, SystemEvent
from app.core.logging import get_logger
from app.core.public_api import core_api

MASKED_VALUE = core_api.secrets.MASKED

logger = get_logger(__name__)

_DELIVERY_STATUS_SUCCESS = 'success'
_DELIVERY_STATUS_PENDING_RETRY = 'pending_retry'
_DELIVERY_STATUS_FAILED = 'failed'
# In-flight first attempt: row persisted BEFORE the HTTP call so a
# crash mid-delivery leaves a trace the retry worker can requeue.
_DELIVERY_STATUS_PENDING = 'pending'

#: Why the application itself stopped trying — stable values stored on the
#: delivery row and translated in the history view. Nobody answered in these
#: cases, so the row carries the reason instead of a receiver's status code.
_ABANDON_CIRCUIT_BREAKER = 'circuit_breaker'
_ABANDON_WEBHOOK_DISABLED = 'webhook_disabled'
_ABANDON_WEBHOOK_DELETED = 'webhook_deleted'
_ABANDON_MODULE_DISABLED = 'module_disabled'

DEFAULT_CIRCUIT_BREAKER_THRESHOLD = 10
_RETRY_BATCH_LIMIT = 50
_RESPONSE_BODY_MAX_BYTES = 1024


#: This module's name, as the binding sees it.
MODULE_NAME = 'webhooks'

#: The shape of the outbound envelope, not of ``data`` — that follows whatever
#: the payload model for the event declares. Bump only on a change a consumer
#: must react to; additions that a reader can safely ignore stay at the current
#: number and are documented as such in docs/subsystems/WEBHOOKS.md.
SCHEMA_VERSION = 1


def decrypt_secret(stored: str) -> str:
    """Read a signing secret written by this module.

    Values bound to another module are refused; the two legacy shapes
    written before binding existed are still read, so endpoints created
    earlier keep signing without an intervention.
    """
    return core_api.secrets.decrypt_for_module(MODULE_NAME, stored)


def _serialize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(json.dumps(payload, default=str))
    return result


def event_name(event: SystemEvent | str) -> str:
    """Normalize an event to its wire name.

    Events reach the dispatcher as plain strings once modules contribute their
    own (``recipe.created`` and friends live in the payload registry, not in
    ``SystemEvent``), while core events arrive as the enum members that carry
    the same strings. Both shapes arrive here.
    """
    return event.value if isinstance(event, SystemEvent) else str(event)


def build_outbound_payload(
    event: SystemEvent | str, payload: EventPayload
) -> dict[str, Any]:
    return {
        'schema_version': SCHEMA_VERSION,
        'event': event_name(event),
        'timestamp': datetime.now(tz=UTC).isoformat(),
        # delivery_id is NOT set here — it is minted per target together
        # with the delivery row in dispatch_event (webhook_service.py),
        # and every attempt of that delivery — first probe and worker
        # retries alike — reuses it, so a receiver can dedup retries as
        # the same delivery. Two endpoints still never share an id:
        # receivers that follow GitHub's dedup-by-delivery-id pattern
        # would incorrectly drop the second target's delivery if they did.
        'organization_id': str(getattr(payload, 'organization_id', None)),
        'data': payload.model_dump(exclude={'organization_id'}),
    }
