"""Pydantic v2 schemas for the Webhooks module."""

import re
from datetime import datetime
from functools import cache
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from app.core.events import SystemEvent
from app.core.exceptions import ServiceRejectionError
from app.core.ssrf_guard import WebhookUrlRejectedError

from ._webhook_delivery import (
    _CONNECT_FAILED_PREFIX,
    _CONNECTION_BROKEN_INFIX,
    _CONNECTION_PREFIX,
    _TIMEOUT_PREFIX,
    _TLS_REFUSED_INFIX,
    _UNREADABLE_SIGNING_VALUE,
)

#: Names in ``SystemEvent`` and the payload registry that nothing emits:
#: they stand in the core contract, and a webhook subscribed to one never
#: fires. The catalogue leaves them out, so the form does not offer them and
#: the API refuses a new subscription; a row that already names one reads as
#: a withdrawn subscription, which the form lets the administrator remove.
NEVER_EMITTED: frozenset[str] = frozenset(
    {'item.transferred', 'item.deactivated', 'item.status_changed'}
)


def valid_event_types() -> set[str]:
    """Event names a webhook may subscribe to.

    The union of the payload registry — where modules contribute their events,
    so every ``recipe.*`` name lives there and nowhere else — and
    ``SystemEvent``. Neither set alone covers what the bus actually emits.

    The eleven aliases that left ``SystemEvent`` before the first release — nine
    vertical names and the two old neutral-vocabulary spellings — did not
    narrow what may be subscribed by one live event: the survivors sit in
    the core payload table, the first half of the union. That is measured,
    not assumed — see ``test_event_deprecations``.

    Computed per call rather than frozen at import: the registry becomes
    runtime-populated in the module-events work, and a snapshot taken here
    would silently stop seeing late registrations.
    """
    from app.core.public_api import core_api

    subscribable = set(core_api.events.registered_events()) | {
        e.value for e in SystemEvent
    }
    return subscribable - NEVER_EMITTED


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


#: The refusals of the URL guard, as the codes the API reports: the tail of
#: each ``webhook_url_<reason>`` catalogue key. The stored sentence is the
#: English catalogue text whatever language the request that triggered the
#: delivery was in, so one set of patterns recognises it.
_URL_REFUSAL_REASONS = ('loopback', 'private', 'unresolved', 'rebinding')
_PLACEHOLDER = '\x00'


@cache
def _url_refusal_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """One pattern per refusal: the English template with its slots as wildcards."""
    refusals: dict[str, WebhookUrlRejectedError | ServiceRejectionError] = {
        f'url_{reason}': WebhookUrlRejectedError(
            reason, host=_PLACEHOLDER, resolved=_PLACEHOLDER
        )
        for reason in _URL_REFUSAL_REASONS
    }
    refusals['url_malformed'] = ServiceRejectionError('webhook_url_malformed')
    refusals['url_scheme'] = ServiceRejectionError(
        'webhook_url_scheme', schemes=_PLACEHOLDER
    )
    refusals['url_no_hostname'] = ServiceRejectionError('webhook_url_no_hostname')
    patterns = []
    for code, refusal in refusals.items():
        template = refusal.sentence('en')
        body = '.+'.join(re.escape(part) for part in template.split(_PLACEHOLDER))
        patterns.append((code, re.compile(body, re.DOTALL)))
    return tuple(patterns)


def url_refusal_code(error_message: str) -> str | None:
    """The code of the URL-guard refusal that *error_message* is, or ``None``."""
    for code, pattern in _url_refusal_patterns():
        if pattern.fullmatch(error_message):
            return code
    return None


def failure_cause(status_code: int | None, error_message: str | None) -> str | None:
    """The code of the cause behind a delivery that got no answer, or ``None``.

    A delivery the target answered carries the target's own reply as its
    error, and that text is never classified: a receiver whose page starts
    with "Timeout after" is not a timeout of ours.
    """
    if not error_message or status_code is not None:
        return None
    if error_message == _UNREADABLE_SIGNING_VALUE:
        return 'signing_unreadable'
    if error_message.startswith(_TIMEOUT_PREFIX):
        return 'timeout'
    if error_message.startswith(_CONNECT_FAILED_PREFIX):
        return 'connect_failed'
    if error_message.startswith(_CONNECTION_PREFIX):
        if _TLS_REFUSED_INFIX in error_message:
            return 'tls_refused'
        if _CONNECTION_BROKEN_INFIX in error_message:
            return 'connection_broken'
    return url_refusal_code(error_message)


class WebhookEndpointCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    url: HttpUrl
    secret: str | None = Field(None, max_length=512)
    http_method: Literal['POST', 'PUT'] = 'POST'
    event_types: list[str] = Field(..., min_length=1)
    max_retries: int = Field(3, ge=0, le=10)
    retry_backoff_seconds: int = Field(10, ge=1, le=300)
    timeout_seconds: int = Field(10, ge=1, le=30)
    is_active: bool = True

    @field_validator('event_types')
    @classmethod
    def validate_event_types(cls, v: list[str]) -> list[str]:
        allowed = valid_event_types()
        unknown = [e for e in v if e not in allowed]
        if unknown:
            raise ValueError(
                f'Unknown event type(s): {", ".join(unknown)}. '
                f'Valid values: {", ".join(sorted(allowed))}'
            )
        return list(set(v))  # deduplicate


class WebhookEndpointUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    url: HttpUrl | None = None
    # Sending "**********" means "do not change the secret"
    secret: str | None = Field(None, max_length=512)
    http_method: Literal['POST', 'PUT'] | None = None
    event_types: list[str] | None = None
    max_retries: int | None = Field(None, ge=0, le=10)
    retry_backoff_seconds: int | None = Field(None, ge=1, le=300)
    timeout_seconds: int | None = Field(None, ge=1, le=30)
    is_active: bool | None = None

    @field_validator('event_types')
    @classmethod
    def validate_event_types(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        unknown = [e for e in v if e not in valid_event_types()]
        if unknown:
            raise ValueError(f'Unknown event type(s): {", ".join(unknown)}.')
        return list(set(v))


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class WebhookEndpointResponse(BaseModel):
    model_config = {'from_attributes': True}

    id: UUID
    name: str
    url: str
    has_secret: bool  # Never expose the actual secret
    http_method: str
    event_types: list[str]
    max_retries: int
    retry_backoff_seconds: int
    timeout_seconds: int
    is_active: bool
    last_triggered_at: datetime | None
    last_status_code: int | None
    consecutive_failures: int
    #: Set only when the circuit breaker switched the endpoint off. An
    #: endpoint an administrator paused is inactive with this left null —
    #: the two are not the same thing to say to whoever reads the list.
    auto_disabled_at: datetime | None = None
    #: True when every event this endpoint subscribes to belongs to a module
    #: that is currently disabled — nothing it listens for can ever fire, yet
    #: ``is_active`` still reads true and the card looks healthy. Computed per
    #: response rather than stored: it follows the module switches, so turning
    #: a module back on clears it with no write. An endpoint that also listens
    #: to a core event, or to a module still enabled, stays False — it can
    #: still fire.
    events_all_module_disabled: bool = False
    #: True when at least one subscribed name is no longer in the catalogue:
    #: the row holds it in ``event_types``, yet ``valid_event_types()`` would
    #: refuse it today, so nothing it names can match an emission. The rows
    #: are not migrated (the stores carrying them are disposable), so the
    #: fact is reported instead — a subscription that died with its catalogue
    #: entry must not be invisible while the card looks healthy.
    events_unknown: bool = False
    created_at: datetime
    updated_at: datetime


class WebhookDeliveryResponse(BaseModel):
    model_config = {'from_attributes': True}

    id: UUID
    event_type: str
    payload_json: dict[str, Any]
    delivery_id: str | None = None
    abandon_reason: str | None = None
    status_code: int | None
    response_body: str | None
    error_message: str | None
    attempt_number: int
    delivery_status: str
    next_retry_at: datetime | None = None
    created_at: datetime
    last_attempt_at: datetime | None = None
    #: Why the delivery got no answer, as a code the screen words itself in
    #: the reader's language; filled from the stored sentence on every read.
    error_cause: str | None = None

    @model_validator(mode='after')
    def _name_the_cause(self) -> 'WebhookDeliveryResponse':
        self.error_cause = failure_cause(self.status_code, self.error_message)
        return self


class AvailableEventResponse(BaseModel):
    event_type: str
    description: str
    #: Module that emits this event, or ``None`` for a core event.
    source_module: str | None = None
    #: Whether that module is enabled here. Events of a disabled module stay
    #: in the catalog — subscribing before switching a module on is a real
    #: case — but the form marks them instead of offering them as equals.
    available: bool = True


class TestWebhookResponse(BaseModel):
    success: bool
    status_code: int | None
    error: str | None
    delivery_id: UUID
    #: Why the test got no answer, as a code the screen words itself.
    error_cause: str | None = None

    @model_validator(mode='after')
    def _name_the_cause(self) -> 'TestWebhookResponse':
        self.error_cause = failure_cause(self.status_code, self.error)
        return self
