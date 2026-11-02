"""Unit tests for factory dispatch on LlmProtocol (not provider)."""

from __future__ import annotations

from types import SimpleNamespace

from app.core.llm.anthropic_client import AnthropicClient
from app.core.llm.factory import get_client
from app.core.llm.google_client import GoogleClient
from app.core.llm.openai_client import OpenAiCompatibleClient


def _conn(provider: str, **kw):
    """Build a minimal AiConnection-shaped object for factory dispatch."""
    return SimpleNamespace(
        provider=provider,
        api_key_enc='',
        api_base_url=kw.get('api_base_url', ''),
        model_name=kw.get('model_name', ''),
        temperature=None,
        max_tokens=None,
        top_p=None,
        capabilities=[],
    )


class TestFactoryDispatch:
    def test_openai_compatible_providers_return_openai_client(self):
        for provider in (
            'openai',
            'openrouter',
            'groq',
            'deepseek',
            'custom',
            'ollama',
        ):
            client = get_client(_conn(provider))
            assert isinstance(client, OpenAiCompatibleClient), (
                f'{provider} -> {type(client)}'
            )

    def test_anthropic_returns_anthropic_client(self):
        assert isinstance(get_client(_conn('anthropic')), AnthropicClient)

    def test_google_returns_google_client(self):
        assert isinstance(get_client(_conn('google')), GoogleClient)
