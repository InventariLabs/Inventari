"""A delivery that got no answer carries a code for its cause.

The stored sentence is English. The screen words the cause itself, in the
reader's language, from the code the API reports beside it — so every
sentence the delivery builds must be recognised, and a receiver's own reply
must never be mistaken for one of ours.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.modules.webhooks import schemas
from app.modules.webhooks._webhook_delivery import (
    _UNREADABLE_SIGNING_VALUE,
    _request_failure_sentence,
    failure_cause,
)
from app.modules.webhooks.models import WebhookEndpoint


def _endpoint() -> WebhookEndpoint:
    return WebhookEndpoint(
        name='Listener',
        url='https://93.184.216.34:8443/hook',
        event_types=['item.created'],
        http_method='POST',
        timeout_seconds=5,
    )


@pytest.mark.parametrize(
    ('exc', 'code'),
    [
        (httpx.ConnectError('All connection attempts failed'), 'connect_failed'),
        (
            httpx.ConnectError('[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify'),
            'tls_refused',
        ),
        (httpx.ReadError('peer closed'), 'connection_broken'),
    ],
)
def test_every_connection_sentence_is_recognised(
    exc: httpx.RequestError, code: str
) -> None:
    sentence = _request_failure_sentence(exc, _endpoint())

    assert failure_cause(None, sentence) == code


def test_the_timeout_and_the_unreadable_signing_value_are_recognised() -> None:
    assert failure_cause(None, 'Timeout after 5s') == 'timeout'
    assert failure_cause(None, _UNREADABLE_SIGNING_VALUE) == 'signing_unreadable'


def test_a_receivers_own_reply_is_never_classified() -> None:
    assert failure_cause(500, 'Timeout after 5s') is None
    assert failure_cause(None, None) is None
    assert failure_cause(None, 'Something nobody wrote') is None


def _delivery(**overrides: Any) -> dict[str, Any]:
    return {
        'id': '00000000-0000-0000-0000-000000000001',
        'event_type': 'item.created',
        'payload_json': {},
        'status_code': None,
        'response_body': None,
        'error_message': None,
        'attempt_number': 1,
        'delivery_status': 'failed',
        'created_at': '2026-11-01T10:00:00Z',
        **overrides,
    }


def test_the_delivery_log_reports_the_cause_beside_the_sentence() -> None:
    row = schemas.WebhookDeliveryResponse.model_validate(
        _delivery(error_message='Timeout after 5s')
    )

    assert row.error_cause == 'timeout'
    assert row.error_message == 'Timeout after 5s'
    assert row.model_dump()['error_cause'] == 'timeout'


def test_the_test_ping_reports_the_cause_too() -> None:
    result = schemas.TestWebhookResponse(
        success=False,
        status_code=None,
        error=_UNREADABLE_SIGNING_VALUE,
        delivery_id='00000000-0000-0000-0000-000000000002',
    )

    assert result.error_cause == 'signing_unreadable'
