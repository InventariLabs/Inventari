"""Outbound LLM requests go to the address the SSRF guard actually vetted.

Validating a URL and then letting httpx resolve the name again leaves a
DNS-rebinding window: the authoritative server can answer with a public
address for the check and a private one for the request. Webhook delivery
already pins the resolved address; these tests hold the LLM clients to the
same contract.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.core.llm._outbound import pin_llm_url
from app.core.llm.anthropic_client import AnthropicClient
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


class TestPinLlmUrl:
    def test_rewrites_host_to_the_resolved_address(self, stub_dns):
        stub_dns.resolves('api.example.com', '93.184.216.34')

        target = pin_llm_url('https://api.example.com/v1/chat/completions')

        assert target.url == 'https://93.184.216.34/v1/chat/completions'
        assert target.hostname == 'api.example.com'

    def test_keeps_port_and_query(self, stub_dns):
        stub_dns.resolves('api.example.com', '93.184.216.34')

        target = pin_llm_url('https://api.example.com:8443/v1/models?verbose=1')

        assert target.url == 'https://93.184.216.34:8443/v1/models?verbose=1'

    def test_brackets_ipv6_literals(self, stub_dns):
        stub_dns.resolves('api.example.com', '2606:4700::1111')

        target = pin_llm_url('https://api.example.com/v1/models')

        assert target.url == 'https://[2606:4700::1111]/v1/models'

    def test_host_header_and_sni_carry_the_original_name(self, stub_dns):
        stub_dns.resolves('api.example.com', '93.184.216.34')

        target = pin_llm_url('https://api.example.com/v1/models')

        assert target.with_host_header({'X-Other': 'kept'}) == {
            'X-Other': 'kept',
            'Host': 'api.example.com',
        }
        assert target.extensions == {
            'sni_hostname': 'api.example.com',
            'target_hostname': 'api.example.com',
        }

    def test_private_address_is_still_rejected(self, stub_dns, monkeypatch):
        from app.config import settings

        # The test examines the guard's rule, not the machine's
        # configuration: an operator running with the local-model flag on
        # must not watch this rejection evaporate.
        monkeypatch.setattr(settings, 'LLM_ALLOW_PRIVATE_NETWORKS', False)
        stub_dns.resolves('sneaky.example.com', '169.254.169.254')

        with pytest.raises(ValueError, match='private'):
            pin_llm_url('https://sneaky.example.com/v1/models')

    def test_unresolvable_name_left_alone_on_self_hosted(self, stub_dns, monkeypatch):
        """With private networks allowed the guard returns the hostname —
        there is no address to pin, so the URL must survive untouched."""
        from app.config import settings

        monkeypatch.setattr(settings, 'LLM_ALLOW_PRIVATE_NETWORKS', True)
        stub_dns.fails('ollama.lan')

        target = pin_llm_url('http://ollama.lan:11434/v1/models')

        assert target.url == 'http://ollama.lan:11434/v1/models'
        assert target.hostname == 'ollama.lan'


class TestClientsUseThePinnedAddress:
    @pytest.mark.asyncio
    async def test_openai_complete_connects_to_the_vetted_ip(self, stub_dns):
        stub_dns.resolves('openrouter.ai', '93.184.216.34')
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen['url'] = str(request.url)
            seen['host'] = request.headers.get('Host', '')
            return httpx.Response(
                200, json={'choices': [{'message': {'content': 'ok'}}]}
            )

        from app.core.llm.base import LlmRequest

        with patch(
            'app.core.llm.secrets.decrypt_connection_secret', return_value='sk-test'
        ):
            client = OpenAiCompatibleClient(
                _conn(), _transport=httpx.MockTransport(handler)
            )
            await client.complete(LlmRequest(prompt='hi'))

        assert seen['url'] == 'https://93.184.216.34/api/v1/chat/completions'
        assert seen['host'] == 'openrouter.ai'

    @pytest.mark.asyncio
    async def test_openai_list_models_connects_to_the_vetted_ip(self, stub_dns):
        stub_dns.resolves('openrouter.ai', '93.184.216.34')
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen['url'] = str(request.url)
            seen['host'] = request.headers.get('Host', '')
            return httpx.Response(200, json={'data': [{'id': 'a'}]})

        with patch(
            'app.core.llm.secrets.decrypt_connection_secret', return_value='sk-test'
        ):
            client = OpenAiCompatibleClient(
                _conn(), _transport=httpx.MockTransport(handler)
            )
            await client.list_models()

        assert seen['url'] == 'https://93.184.216.34/api/v1/models'
        assert seen['host'] == 'openrouter.ai'

    @pytest.mark.asyncio
    async def test_anthropic_complete_connects_to_the_vetted_ip(self, stub_dns):
        stub_dns.resolves('api.anthropic.com', '93.184.216.35')
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen['url'] = str(request.url)
            seen['host'] = request.headers.get('Host', '')
            return httpx.Response(
                200, json={'content': [{'type': 'text', 'text': 'ok'}]}
            )

        from app.core.llm.base import LlmRequest

        with patch(
            'app.core.llm.secrets.decrypt_connection_secret', return_value='sk-test'
        ):
            client = AnthropicClient(
                _conn('anthropic', 'https://api.anthropic.com'),
                _transport=httpx.MockTransport(handler),
            )
            await client.complete(LlmRequest(prompt='hi'))

        assert seen['url'] == 'https://93.184.216.35/v1/messages'
        assert seen['host'] == 'api.anthropic.com'

    @pytest.mark.asyncio
    async def test_rebinding_after_validation_cannot_move_the_request(self, stub_dns):
        """The attack this closes: the name flips to an internal address
        between the guard's lookup and the request."""
        stub_dns.resolves('rebind.example.com', '93.184.216.34')
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            # A second resolution at delivery time would land here on
            # 169.254.169.254 — the cloud metadata endpoint.
            stub_dns.resolves('rebind.example.com', '169.254.169.254')
            seen['url'] = str(request.url)
            return httpx.Response(200, json={'data': [{'id': 'a'}]})

        with patch(
            'app.core.llm.secrets.decrypt_connection_secret', return_value='sk-test'
        ):
            client = OpenAiCompatibleClient(
                _conn('custom', 'https://rebind.example.com/v1'),
                _transport=httpx.MockTransport(handler),
            )
            await client.list_models()

        assert seen['url'] == 'https://93.184.216.34/v1/models'
        assert '169.254' not in seen['url']
