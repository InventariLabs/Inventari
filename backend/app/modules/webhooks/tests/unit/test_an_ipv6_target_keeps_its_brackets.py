"""A receiver at an IPv6 address is reached, not refused at URL parsing.

The delivery connects to the address the guard pinned, and builds the request
URL from it. The guard hands an IPv6 address back bare; a bare address in the
authority of a URL is read as `host:port`, so the request failed before it was
sent. The URL now carries the brackets its authority requires, and keeps the
port, path and query of the stored one.
"""

from typing import Any

import httpx
import pytest

from app.modules.webhooks._webhook_delivery import _attempt_delivery
from app.modules.webhooks.models import WebhookEndpoint

from .._signing_helpers import recording_transport


def _endpoint(url: str) -> WebhookEndpoint:
    return WebhookEndpoint(
        name='Listener',
        url=url,
        event_types=['item.created'],
        http_method='POST',
        timeout_seconds=5,
    )


async def _deliver(url: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(
        'app.modules.webhooks._webhook_delivery.httpx.AsyncClient',
        recording_transport(sent),
    )
    ok, *_ = await _attempt_delivery(
        _endpoint(url), b'{}', {'event': 'item.created'}, delivery_id='d-1'
    )
    assert ok
    assert len(sent) == 1
    return sent[0]


@pytest.mark.asyncio
async def test_the_request_goes_to_the_bracketed_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = await _deliver(
        'https://[2606:4700:4700::1111]:8443/hook?x=1', monkeypatch
    )

    assert request['url'] == 'https://[2606:4700:4700::1111]:8443/hook?x=1'
    parsed = httpx.URL(request['url'])
    assert parsed.host == '2606:4700:4700::1111'
    assert parsed.port == 8443


@pytest.mark.asyncio
async def test_an_ipv4_address_stays_unbracketed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = await _deliver('https://93.184.216.34/hook', monkeypatch)

    assert request['url'] == 'https://93.184.216.34/hook'
