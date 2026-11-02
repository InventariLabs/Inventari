"""LLM stand-in for the vision integration tests.

Both vision endpoints end in one call to the provider client, so that call is
the only boundary a test needs to control. Patching it turns "does the vision
API work" into a question with a single answer — before this existed, the API
tests asserted ``status_code in [200, 500]`` and a server error counted as a
pass.
"""

from __future__ import annotations

import io
from contextlib import AbstractContextManager
from unittest.mock import AsyncMock, patch

from PIL import Image

from app.core.llm.base import LlmResponse
from app.core.llm.errors import (
    LlmTimeoutError,
    LlmTransportError,
    provider_refusal,
)


def jpeg_bytes(size: tuple[int, int] = (8, 8)) -> bytes:
    """A real (tiny) JPEG — the nutrition path re-compresses before sending."""
    buf = io.BytesIO()
    Image.new('RGB', size, (200, 200, 200)).save(buf, format='JPEG')
    return buf.getvalue()


def answering(*contents: str) -> AsyncMock:
    """A client that returns *contents*, one per call, in order."""
    client = AsyncMock()
    client.connection_name = 'Label Reader'
    client.model_name = 'gpt-4o-mini'
    client.complete = AsyncMock(
        side_effect=[LlmResponse(content=c, usage={}) for c in contents]
    )
    return client


def answering_without_connection(*contents: str) -> AsyncMock:
    """Like :func:`answering`, but the client carries no connection metadata —
    the enrichment cannot name a connection it never saw."""
    client = AsyncMock()
    client.connection_name = None
    client.model_name = None
    client.complete = AsyncMock(
        side_effect=[LlmResponse(content=c, usage={}) for c in contents]
    )
    return client


def unreachable(error: Exception | None = None) -> AsyncMock:
    """A client whose call fails before an answer exists."""
    client = AsyncMock()
    client.complete = AsyncMock(side_effect=error or OSError('connection reset'))
    return client


def ran_out_of_time() -> AsyncMock:
    """A client whose provider answered nothing inside the time allowed.

    Reached, and still thinking — which is what a model on the user's own
    graphics card does for minutes at a time. A different errand from a
    refused connection, so a different message.
    """
    client = AsyncMock()
    client.connection_name = 'Label Reader'
    client.model_name = 'qwen3-vl:8b'
    client.complete = AsyncMock(
        side_effect=LlmTimeoutError(
            'The model did not answer within the time allowed (ReadTimeout): timed out',
            connection_name='Label Reader',
            model_name='qwen3-vl:8b',
        )
    )
    return client


def never_reached() -> AsyncMock:
    """A client that could not get through to the provider at all.

    What ``httpx`` reports for a refused connection or a certificate it would
    not accept — translated by the adapter into the one type that says "no
    answer exists", rather than left as a class no router catches. A timeout
    is its own subclass; see ``ran_out_of_time``.
    """
    client = AsyncMock()
    client.connection_name = 'Label Reader'
    client.model_name = 'gpt-4o-mini'
    client.complete = AsyncMock(
        side_effect=LlmTransportError(
            'Could not reach the model provider (ConnectError): refused',
            connection_name='Label Reader',
            model_name='gpt-4o-mini',
        )
    )
    return client


def refused(status_code: int) -> AsyncMock:
    """A client whose provider answered, refusing the request itself.

    The usual first-setup state: a key the provider will not accept, a
    spent limit, a model name it does not know. Built through the real
    ``provider_refusal`` so the double stays faithful: a code the
    classifier does not name (500) degrades to the plain RuntimeError the
    production client would raise, not to a typed refusal.
    """
    client = AsyncMock()
    client.connection_name = 'Label Reader'
    client.model_name = 'gpt-4o-mini'
    client.complete = AsyncMock(
        side_effect=provider_refusal(
            status_code,
            '{"error": "invalid api key"}',
            what='OpenAI-compatible provider',
            connection_name='Label Reader',
            model_name='gpt-4o-mini',
        )
    )
    return client


def patch_client(client: AsyncMock) -> AbstractContextManager[AsyncMock]:
    """Swap the provider client the vision service resolves for its purpose."""
    return patch(
        'app.core.public_api.llm.CoreLlmAPI.get_client_for_purpose_async',
        new_callable=AsyncMock,
        return_value=client,
    )
