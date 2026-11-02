"""Unit tests for app.core.llm.factory.

After the protocol-dispatch refactor (Task 2 of the provider-expansion
plan), the factory dispatches on ``LlmProtocol`` (3 cases) rather than
on provider strings, and ``protocol_for()`` defaults unknown providers
to OPENAI_COMPATIBLE. These tests pin the new contract:

- OpenRouter / Custom / Groq / DeepSeek / Ollama / vLLM all collapse onto
  the OpenAi-compatible adapter (one protocol, many providers).
- Anthropic routes to the native Messages-API client.
- Google routes to the native Gemini-SDK client.
- An unknown provider string defaults to OpenAI-compatible (safest), not
  ValueError — because ``protocol_for`` is the single source of truth and
  defaults are intentional.
"""

from types import SimpleNamespace

from app.core.llm.anthropic_client import AnthropicClient
from app.core.llm.factory import get_client
from app.core.llm.google_client import GoogleClient
from app.core.llm.openai_client import OpenAiCompatibleClient


def _conn(provider: str):
    """Minimal AiConnection-shaped object — only ``provider`` is read by
    the factory dispatch (clients read the other fields lazily)."""
    return SimpleNamespace(
        provider=provider,
        api_key_enc='',
        api_base_url='',
        model_name='',
        temperature=None,
        max_tokens=None,
        top_p=None,
        capabilities=[],
    )


class TestFactoryDispatch:
    def test_openrouter_returns_openai_compatible(self):
        client = get_client(_conn('openrouter'))
        assert isinstance(client, OpenAiCompatibleClient)

    def test_custom_returns_openai_compatible(self):
        """'custom' covers LM Studio / Ollama / vLLM /
        OpenAI itself — they all speak the OpenAI chat/completions
        protocol with different base URLs."""
        client = get_client(_conn('custom'))
        assert isinstance(client, OpenAiCompatibleClient)

    def test_google_returns_google_client(self):
        client = get_client(_conn('google'))
        assert isinstance(client, GoogleClient)

    def test_anthropic_returns_anthropic_client(self):
        client = get_client(_conn('anthropic'))
        assert isinstance(client, AnthropicClient)

    def test_specialist_providers_collapse_to_openai_client(self):
        """Groq / DeepSeek / Mistral / Together / xAI / MiniMax / GLM / MiMo
        are OpenAI-compatible — adding them requires no new client code."""
        for provider in (
            'groq',
            'deepseek',
            'mistral',
            'together',
            'xai',
            'minimax',
            'glm',
            'mimo',
        ):
            client = get_client(_conn(provider))
            assert isinstance(client, OpenAiCompatibleClient), provider

    def test_local_runtimes_collapse_to_openai_client(self):
        for provider in ('ollama', 'lm_studio', 'vllm'):
            client = get_client(_conn(provider))
            assert isinstance(client, OpenAiCompatibleClient), provider

    def test_unknown_provider_defaults_to_openai_compatible(self):
        """Unknown providers default to OPENAI_COMPATIBLE (the de-facto
        standard) rather than raising — ``protocol_for`` is the single
        source of truth, and a hard failure here would break every
        pre-migration row."""
        client = get_client(_conn('some-new-provider'))
        assert isinstance(client, OpenAiCompatibleClient)
