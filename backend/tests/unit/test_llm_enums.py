"""Unit tests for the widened LlmProvider / LlmProtocol enums."""

from __future__ import annotations

import pytest

from app.core.llm.enums import LlmProtocol, LlmProvider, protocol_for


class TestLlmProviderValues:
    def test_all_17_providers_present(self):
        values = {p.value for p in LlmProvider}
        expected = {
            'openai',
            'anthropic',
            'google',
            'openrouter',
            'groq',
            'deepseek',
            'mistral',
            'together',
            'xai',
            'minimax',
            'glm',
            'mimo',
            'ollama',
            'lm_studio',
            'vllm',
            'custom',
            # A reader, not a model: no LLM protocol, never built into a
            # client — its connection is a page-fetch credential.
            'jina',
        }
        assert values == expected, (
            f'missing: {expected - values}, extra: {values - expected}'
        )

    def test_legacy_alias_custom_still_works(self):
        # The migration mapped legacy lm_studio/ollama -> custom; that value MUST stay.
        assert LlmProvider.OPENAI_COMPATIBLE.value == 'custom'


class TestProtocolFor:
    @pytest.mark.parametrize(
        'provider,expected',
        [
            ('openai', LlmProtocol.OPENAI_COMPATIBLE),
            ('openrouter', LlmProtocol.OPENAI_COMPATIBLE),
            ('groq', LlmProtocol.OPENAI_COMPATIBLE),
            ('deepseek', LlmProtocol.OPENAI_COMPATIBLE),
            ('mistral', LlmProtocol.OPENAI_COMPATIBLE),
            ('together', LlmProtocol.OPENAI_COMPATIBLE),
            ('xai', LlmProtocol.OPENAI_COMPATIBLE),
            ('minimax', LlmProtocol.OPENAI_COMPATIBLE),
            ('glm', LlmProtocol.OPENAI_COMPATIBLE),
            ('mimo', LlmProtocol.OPENAI_COMPATIBLE),
            ('ollama', LlmProtocol.OPENAI_COMPATIBLE),
            ('lm_studio', LlmProtocol.OPENAI_COMPATIBLE),
            ('vllm', LlmProtocol.OPENAI_COMPATIBLE),
            ('custom', LlmProtocol.OPENAI_COMPATIBLE),
            ('anthropic', LlmProtocol.ANTHROPIC),
            ('google', LlmProtocol.GOOGLE),
        ],
    )
    def test_protocol_mapping(self, provider, expected):
        assert protocol_for(provider) == expected

    def test_unknown_provider_defaults_to_openai_compatible(self):
        assert protocol_for('some-new-provider') == LlmProtocol.OPENAI_COMPATIBLE
