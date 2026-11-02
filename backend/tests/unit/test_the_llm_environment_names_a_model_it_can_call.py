"""The environment's model is checked at start-up, not at the first call.

The legacy env fallback is the one key path that reaches an organization
nobody configured — a fresh install, or a demo that rebuilds every night. A
provider this server has no client for, a key aimed at OpenRouter's address
while naming another provider, or a capability nobody can serve are all
mistakes an operator makes once in ``.env``; refusing to start names the
variable, where a call failing later names nothing.
"""

from __future__ import annotations

import pytest

from app.config import check_llm_environment, llm_env_capabilities

pytestmark = pytest.mark.unit

_OPENROUTER = 'https://openrouter.ai/api/v1'


def _check(**kwargs: str | None) -> None:
    check_llm_environment(
        **{
            'provider': 'openrouter',
            'api_key': 'sk-test',
            'base_url': _OPENROUTER,
            'capabilities': '',
            **kwargs,
        }
    )


class TestTheProvider:
    def test_an_unknown_provider_refuses_to_start(self) -> None:
        with pytest.raises(ValueError, match='LLM_PROVIDER'):
            _check(provider='deepsek', base_url='https://api.deepseek.com')

    def test_the_refusal_names_the_allowed_ones(self) -> None:
        with pytest.raises(ValueError, match='deepseek.*mimo.*openrouter'):
            _check(provider='deepsek', base_url='https://api.deepseek.com')

    def test_a_reader_key_is_not_a_model(self) -> None:
        with pytest.raises(ValueError, match='LLM_PROVIDER'):
            _check(provider='jina')

    def test_an_unknown_provider_is_refused_without_a_key_too(self) -> None:
        with pytest.raises(ValueError, match='LLM_PROVIDER'):
            _check(provider='deepsek', api_key=None)

    @pytest.mark.parametrize(
        ('provider', 'base_url'),
        [
            ('openrouter', _OPENROUTER),
            ('deepseek', 'https://api.deepseek.com'),
            ('mimo', 'https://api.xiaomimimo.com/v1'),
        ],
    )
    def test_a_callable_provider_starts(self, provider: str, base_url: str) -> None:
        _check(provider=provider, base_url=base_url)


class TestTheAddress:
    def test_another_providers_key_is_not_sent_to_openrouter(self) -> None:
        with pytest.raises(ValueError, match='LLM_API_BASE_URL'):
            _check(provider='deepseek', base_url=_OPENROUTER + '/')

    def test_a_key_with_no_address_refuses_to_start(self) -> None:
        with pytest.raises(ValueError, match='LLM_API_BASE_URL'):
            _check(base_url='')

    def test_no_key_means_no_address_is_needed(self) -> None:
        _check(provider='deepseek', api_key=None, base_url=_OPENROUTER)


class TestTheCapabilities:
    def test_openrouter_keeps_what_it_served_before(self) -> None:
        assert llm_env_capabilities('openrouter', '') == {'text', 'vision'}

    def test_another_provider_reads_no_photographs_until_told(self) -> None:
        assert llm_env_capabilities('deepseek', '') == {'text'}

    def test_a_declaration_is_taken_as_written(self) -> None:
        assert llm_env_capabilities('mimo', ' text, vision ') == {'text', 'vision'}
        assert llm_env_capabilities('openrouter', 'text') == {'text'}

    def test_an_unknown_capability_refuses_to_start(self) -> None:
        with pytest.raises(ValueError, match='LLM_CAPABILITIES.*text, vision'):
            _check(capabilities='text,images')

    def test_a_reader_capability_is_not_a_model_capability(self) -> None:
        with pytest.raises(ValueError, match='LLM_CAPABILITIES'):
            _check(capabilities='url_fetch')
