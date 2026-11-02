"""Waiting for a local model is not the same as failing to reach a provider.

Sixty seconds was written into the client, with no setting and no variable.
For a cloud provider it is generous; for a model running on somebody's own
graphics card it is not enough — a small vision model on a consumer card
can take just over a minute for one photograph, and the person who chose a
local model precisely so their pantry photos stay at home was told the
provider could not be reached. It could. It was thinking.

Two things follow: the limit is configuration, with a default that fits a
local runtime, and the refusal after it says what actually happened.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.config import settings
from app.core.llm.base import LlmRequest
from app.core.llm.errors import LlmTimeoutError, LlmTransportError
from app.core.llm.openai_client import OpenAiCompatibleClient
from app.core.llm.timeouts import request_timeout

pytestmark = pytest.mark.unit


def _connection(provider: str = 'openrouter'):
    from app.models.ai_connection import AiConnection

    return AiConnection(
        organization_id=uuid.UUID('00000000-0000-0000-0000-000000000001'),
        name='label reader',
        provider=provider,
        api_key_enc='sk-test',
        api_base_url='https://openrouter.ai/api/v1',
        model_name='qwen3-vl:8b',
        capabilities=['vision', 'text'],
    )


class TestHowLongTheCallMayTake:
    def test_a_cloud_provider_gets_the_configured_limit(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, 'LLM_REQUEST_TIMEOUT_SECONDS', 42.0)

        assert request_timeout('openrouter') == 42.0

    def test_a_local_runtime_gets_its_own_default(self) -> None:
        # Ollama, LM Studio and vLLM are the three the enum groups as local
        # runtimes, and all three run on hardware the user owns.
        for provider in ('ollama', 'lm_studio', 'vllm'):
            assert request_timeout(provider) > request_timeout('openai')

    def test_a_local_limit_is_configuration_too(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, 'LLM_LOCAL_REQUEST_TIMEOUT_SECONDS', 900.0)

        assert request_timeout('ollama') == 900.0

    def test_an_unknown_provider_is_treated_as_remote(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, 'LLM_REQUEST_TIMEOUT_SECONDS', 42.0)

        assert request_timeout('something-new') == 42.0
        assert request_timeout(None) == 42.0

    async def test_the_client_asks_for_the_limit_its_provider_gets(
        self, monkeypatch
    ) -> None:
        """The setting has to reach `httpx`, not merely exist."""
        monkeypatch.setattr(settings, 'LLM_LOCAL_REQUEST_TIMEOUT_SECONDS', 123.0)
        seen: dict[str, object] = {}
        original = httpx.AsyncClient.__init__

        def spy(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            seen['timeout'] = kwargs.get('timeout')
            return original(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, '__init__', spy)

        def answering(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={'choices': [{'message': {'content': 'ok'}}], 'usage': {}}
            )

        client = OpenAiCompatibleClient(
            _connection('ollama'), _transport=httpx.MockTransport(answering)
        )
        await client.complete(LlmRequest(prompt='Read the label.'))

        assert seen['timeout'] == 123.0


class TestWhatTheReaderIsTold:
    async def test_connection_timeout_reports_provider_unreachable(self) -> None:
        def timing_out(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout('timed out', request=request)

        client = OpenAiCompatibleClient(
            _connection('ollama'), _transport=httpx.MockTransport(timing_out)
        )
        with pytest.raises(LlmTransportError) as caught:
            await client.complete(LlmRequest(prompt='Read the label.'))
        assert not isinstance(caught.value, LlmTimeoutError)
        assert 'reach' in str(caught.value).lower()

    async def test_a_model_that_ran_out_of_time_is_not_reported_as_unreachable(
        self,
    ) -> None:
        def timing_out(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout('timed out', request=request)

        client = OpenAiCompatibleClient(
            _connection('ollama'), _transport=httpx.MockTransport(timing_out)
        )

        with pytest.raises(LlmTimeoutError) as caught:
            await client.complete(LlmRequest(prompt='Read the label.'))

        message = str(caught.value)
        assert 'reach' not in message.lower()
        assert 'time' in message.lower()

    async def test_it_is_still_a_transport_failure_for_older_callers(self) -> None:
        """Recipe import degrades on `LlmTransportError`; it keeps degrading."""

        def timing_out(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout('timed out', request=request)

        client = OpenAiCompatibleClient(
            _connection('ollama'), _transport=httpx.MockTransport(timing_out)
        )

        with pytest.raises(LlmTransportError):
            await client.complete(LlmRequest(prompt='Read the label.'))

    async def test_a_refused_connection_is_still_unreachable(self) -> None:
        def refusing(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError('no route', request=request)

        client = OpenAiCompatibleClient(
            _connection('ollama'), _transport=httpx.MockTransport(refusing)
        )

        with pytest.raises(LlmTransportError) as caught:
            await client.complete(LlmRequest(prompt='Read the label.'))

        assert not isinstance(caught.value, LlmTimeoutError)
