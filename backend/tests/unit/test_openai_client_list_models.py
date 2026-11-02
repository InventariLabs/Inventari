"""list_models() on the OpenAI-compatible + Google clients."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.core.llm.openai_client import OpenAiCompatibleClient


def _conn(provider='openrouter', base_url='https://openrouter.ai/api/v1'):
    return SimpleNamespace(
        provider=provider,
        api_key_enc='sk-test',
        api_base_url=base_url,
        model_name='m',
        temperature=None,
        max_tokens=None,
        top_p=None,
        capabilities=[],
    )


class TestOpenAiListModels:
    @pytest.mark.asyncio
    async def test_list_models_returns_ids(self, stub_dns):
        def handler(request: httpx.Request) -> httpx.Response:
            # The request goes to the pinned address, not the name; the name
            # travels in the Host header (see test_llm_outbound_pinning).
            assert request.url.path == '/api/v1/models'
            assert request.headers['Host'] == 'openrouter.ai'
            return httpx.Response(200, json={'data': [{'id': 'a'}, {'id': 'b'}]})

        with patch(
            'app.core.llm.secrets.decrypt_connection_secret',
            return_value='sk-test',
        ):
            client = OpenAiCompatibleClient(
                _conn(), _transport=httpx.MockTransport(handler)
            )
            models = await client.list_models()

        assert models == ['a', 'b']

    @pytest.mark.asyncio
    async def test_list_models_permissive_for_local_shape(self, monkeypatch):
        """Local servers (LM Studio, llama.cpp) return {models: [{name: ...}]}."""
        # A local server sits on a private address — the SSRF guard only lets
        # it through when the operator opted in.
        from app.config import settings

        monkeypatch.setattr(settings, 'LLM_ALLOW_PRIVATE_NETWORKS', True)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={'models': [{'name': 'llama3.2'}, {'id': 'qwen2'}]},
            )

        with patch(
            'app.core.llm.secrets.decrypt_connection_secret',
            return_value='',
        ):
            client = OpenAiCompatibleClient(
                _conn('lm_studio', 'http://localhost:1234/v1'),
                _transport=httpx.MockTransport(handler),
            )
            models = await client.list_models()

        assert models == ['llama3.2', 'qwen2']

    @pytest.mark.asyncio
    async def test_list_models_error_raises_runtime_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text='unauthorized')

        with patch(
            'app.core.llm.secrets.decrypt_connection_secret',
            return_value='bad',
        ):
            client = OpenAiCompatibleClient(
                _conn(), _transport=httpx.MockTransport(handler)
            )
            with pytest.raises(RuntimeError, match='401'):
                await client.list_models()
