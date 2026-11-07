"""A delivery that never reached the receiver says why in a sentence.

httpx words a refused or unreachable connection "All connection attempts
failed" — a quotation from a library that does not say whether the address is
wrong, a firewall is in the way or the receiver is down. The delivery log is
read by the administrator who has to act on it, so it names the address and
the three things worth checking.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.modules.webhooks._webhook_delivery import _attempt_delivery
from app.modules.webhooks.models import WebhookEndpoint


def _endpoint() -> WebhookEndpoint:
    return WebhookEndpoint(
        name='Listener',
        url='https://93.184.216.34:8443/hook',
        event_types=['item.created'],
        http_method='POST',
        timeout_seconds=5,
    )


def _raising(exc: Exception) -> Any:
    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *exc_info: Any) -> None:
            return None

        async def request(self, *args: Any, **kwargs: Any) -> None:
            raise exc

    return _Client


async def _error_for(exc: Exception, monkeypatch: pytest.MonkeyPatch) -> str | None:
    monkeypatch.setattr(
        'app.modules.webhooks._webhook_delivery.httpx.AsyncClient', _raising(exc)
    )
    ok, status_code, _, error = await _attempt_delivery(
        _endpoint(), b'{}', {'event': 'item.created'}, delivery_id='d-1'
    )
    assert not ok
    assert status_code is None
    return error


@pytest.mark.asyncio
async def test_a_refused_connection_names_the_address_and_what_to_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = await _error_for(
        httpx.ConnectError('All connection attempts failed'), monkeypatch
    )

    assert error is not None
    assert 'All connection attempts failed' not in error
    assert '93.184.216.34:8443' in error
    assert 'firewall' in error


@pytest.mark.asyncio
async def test_a_certificate_the_receiver_cannot_prove_is_said_as_such(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = await _error_for(
        httpx.ConnectError(
            '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed'
        ),
        monkeypatch,
    )

    assert error is not None
    assert 'certificate' in error
    assert 'CERTIFICATE_VERIFY_FAILED' not in error


@pytest.mark.asyncio
async def test_a_connection_that_breaks_midway_is_not_a_quotation_either(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = await _error_for(httpx.ReadError('peer closed'), monkeypatch)

    assert error is not None
    assert 'peer closed' not in error
    assert '93.184.216.34:8443' in error
