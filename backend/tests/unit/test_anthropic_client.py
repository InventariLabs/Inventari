"""Unit tests for the AnthropicClient native Messages API adapter."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.core.llm.anthropic_client import AnthropicClient
from app.core.llm.base import LlmRequest


@pytest.fixture(autouse=True)
def _no_real_dns(stub_dns):
    """These tests are about the request payload; the SSRF guard resolves
    the host first, and that must never reach the network."""


def _conn(**kw):
    return SimpleNamespace(
        id=kw.get('id', uuid.uuid4()),  # a saved row: the memory keys on it
        provider='anthropic',
        api_key_enc='sk-ant-test',
        api_base_url=kw.get('api_base_url', 'https://api.anthropic.com'),
        model_name=kw.get('model_name', 'claude-sonnet-4-5'),
        temperature=kw.get('temperature', None),
        max_tokens=kw.get('max_tokens', None),
        top_p=kw.get('top_p', None),
        capabilities=['vision', 'text'],
    )


def _ok_payload(content: str = 'hello') -> dict:
    return {
        'content': [{'type': 'text', 'text': content}],
        'usage': {'input_tokens': 5, 'output_tokens': 3},
    }


class TestAnthropicClientPayload:
    @pytest.mark.asyncio
    async def test_text_complete_sends_messages_payload(self, stub_dns):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured['url'] = str(request.url)
            captured['path'] = request.url.path
            captured['headers'] = dict(request.headers)
            captured['body'] = json.loads(request.content)
            return httpx.Response(200, json=_ok_payload('pong'))

        transport = httpx.MockTransport(handler)
        with patch(
            'app.core.llm.secrets.decrypt_connection_secret',
            return_value='sk-ant-test',
        ):
            client = AnthropicClient(_conn(), _transport=transport)
            response = await client.complete(LlmRequest(prompt='ping'))

        # The URL carries the pinned address; the name rides in Host.
        assert captured['path'] == '/v1/messages'
        assert captured['headers']['host'] == 'api.anthropic.com'
        # Auth header is x-api-key, NOT Authorization: Bearer
        assert captured['headers']['x-api-key'] == 'sk-ant-test'
        assert captured['headers']['anthropic-version'] == '2023-06-01'
        # Body shape
        assert captured['body']['model'] == 'claude-sonnet-4-5'
        assert captured['body']['messages'] == [{'role': 'user', 'content': 'ping'}]
        # max_tokens is REQUIRED by Anthropic — falls back to 4096 when unset
        assert captured['body']['max_tokens'] == 4096
        assert response.content == 'pong'
        assert response.usage['prompt_tokens'] == 5

    @pytest.mark.asyncio
    async def test_system_prompt_goes_to_top_level(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured['body'] = json.loads(request.content)
            return httpx.Response(200, json=_ok_payload())

        with patch(
            'app.core.llm.secrets.decrypt_connection_secret',
            return_value='k',
        ):
            client = AnthropicClient(_conn(), _transport=httpx.MockTransport(handler))
            await client.complete(LlmRequest(prompt='hi', system_prompt='be brief'))

        # Anthropic: system is a top-level param, NOT a message
        assert captured['body']['system'] == 'be brief'
        assert captured['body']['messages'] == [{'role': 'user', 'content': 'hi'}]

    @pytest.mark.asyncio
    async def test_connection_max_tokens_used_when_set(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured['body'] = json.loads(request.content)
            return httpx.Response(200, json=_ok_payload())

        with patch(
            'app.core.llm.secrets.decrypt_connection_secret',
            return_value='k',
        ):
            client = AnthropicClient(
                _conn(max_tokens=1024), _transport=httpx.MockTransport(handler)
            )
            await client.complete(LlmRequest(prompt='hi'))

        assert captured['body']['max_tokens'] == 1024

    @pytest.mark.asyncio
    async def test_per_call_max_tokens_override(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured['body'] = json.loads(request.content)
            return httpx.Response(200, json=_ok_payload())

        with patch(
            'app.core.llm.secrets.decrypt_connection_secret',
            return_value='k',
        ):
            client = AnthropicClient(
                _conn(max_tokens=1024), _transport=httpx.MockTransport(handler)
            )
            await client.complete(LlmRequest(prompt='hi', max_tokens=512))

        assert captured['body']['max_tokens'] == 512

    @pytest.mark.asyncio
    async def test_multimodal_sends_image_content_blocks(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured['body'] = json.loads(request.content)
            return httpx.Response(200, json=_ok_payload())

        with patch(
            'app.core.llm.secrets.decrypt_connection_secret',
            return_value='k',
        ):
            client = AnthropicClient(_conn(), _transport=httpx.MockTransport(handler))
            await client.complete(
                LlmRequest(prompt='describe', images=[b'\x89PNGfake'])
            )

        content = captured['body']['messages'][0]['content']
        assert isinstance(content, list)
        assert content[0] == {'type': 'text', 'text': 'describe'}
        assert content[1]['type'] == 'image'
        assert content[1]['source']['type'] == 'base64'
        assert content[1]['source']['media_type'] == 'image/png'

    @pytest.mark.asyncio
    async def test_http_error_raises_runtime_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text='unauthorized')

        with patch(
            'app.core.llm.secrets.decrypt_connection_secret',
            return_value='k',
        ):
            client = AnthropicClient(_conn(), _transport=httpx.MockTransport(handler))
            with pytest.raises(RuntimeError, match='401'):
                await client.complete(LlmRequest(prompt='hi'))


class TestAnthropicListModels:
    @pytest.mark.asyncio
    async def test_list_models_returns_ids(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    'data': [
                        {'id': 'claude-sonnet-4-5'},
                        {'id': 'claude-opus-4-1'},
                    ],
                },
            )

        with patch(
            'app.core.llm.secrets.decrypt_connection_secret',
            return_value='k',
        ):
            client = AnthropicClient(_conn(), _transport=httpx.MockTransport(handler))
            models = await client.list_models()

        assert models == ['claude-sonnet-4-5', 'claude-opus-4-1']


class TestAnthropicStructuredOutput:
    @pytest.mark.asyncio
    async def test_json_schema_sets_tools_and_tool_choice(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured['body'] = json.loads(request.content)
            return httpx.Response(200, json=_ok_payload())

        schema = {
            'type': 'object',
            'properties': {'name': {'type': 'string'}},
        }
        with patch(
            'app.core.llm.secrets.decrypt_connection_secret',
            return_value='k',
        ):
            client = AnthropicClient(_conn(), _transport=httpx.MockTransport(handler))
            await client.complete(LlmRequest(prompt='hi', json_schema=schema))

        assert captured['body']['tools'] == [
            {
                'name': 'structured_response',
                'description': 'Return the structured answer',
                'input_schema': schema,
            }
        ]
        assert captured['body']['tool_choice'] == {
            'type': 'tool',
            'name': 'structured_response',
        }

    @pytest.mark.asyncio
    async def test_tool_use_response_becomes_json_content(self):
        payload = {
            'content': [
                {
                    'type': 'tool_use',
                    'id': 'toolu_1',
                    'name': 'structured_response',
                    'input': {'name': 'Milk'},
                }
            ],
            'usage': {'input_tokens': 5, 'output_tokens': 3},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        with patch(
            'app.core.llm.secrets.decrypt_connection_secret',
            return_value='k',
        ):
            client = AnthropicClient(_conn(), _transport=httpx.MockTransport(handler))
            response = await client.complete(
                LlmRequest(prompt='hi', json_schema={'type': 'object'})
            )

        assert response.content == json.dumps({'name': 'Milk'})

    @pytest.mark.asyncio
    async def test_no_tool_use_falls_back_to_text_concatenation(self):
        payload = _ok_payload('plain text answer')

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        with patch(
            'app.core.llm.secrets.decrypt_connection_secret',
            return_value='k',
        ):
            client = AnthropicClient(_conn(), _transport=httpx.MockTransport(handler))
            response = await client.complete(
                LlmRequest(prompt='hi', json_schema={'type': 'object'})
            )

        assert response.content == 'plain text answer'

    @pytest.mark.asyncio
    async def test_disable_reasoning_with_tools_keeps_thinking(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured['body'] = json.loads(request.content)
            return httpx.Response(200, json=_ok_payload())

        with patch(
            'app.core.llm.secrets.decrypt_connection_secret',
            return_value='k',
        ):
            client = AnthropicClient(_conn(), _transport=httpx.MockTransport(handler))
            await client.complete(
                LlmRequest(
                    prompt='hi',
                    json_schema={'type': 'object'},
                    disable_reasoning=True,
                )
            )

        assert captured['body']['thinking'] == {'type': 'disabled'}
        assert 'tools' in captured['body']
        assert 'tool_choice' in captured['body']


class TestARefusalIsRememberedNotRepaid:
    """The Anthropic adapter shares the refusal memory with the rest of
    the LLM layer: once this connection's route answered 400 to the
    thinking switch, the next call does not pay for the refusal again —
    and a refusal it voiced is the only one it stops sending."""

    @pytest.fixture(autouse=True)
    def _clean_memory(self):
        from app.core.llm import _optional_payload

        _optional_payload._refused_since.clear()
        yield
        _optional_payload._refused_since.clear()

    @staticmethod
    def _refusing_then_answering(key: str, calls: list):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            calls.append(body)
            if key in body:
                return httpx.Response(
                    400, json={'error': {'message': f'Unknown parameter: {key}'}}
                )
            return httpx.Response(200, json=_ok_payload('pong'))

        return handler

    @pytest.mark.asyncio
    async def test_a_refused_thinking_switch_is_not_paid_for_again(
        self, stub_dns
    ) -> None:
        from app.core.llm._optional_payload import remembered_rejections

        calls: list[dict] = []
        conn = _conn()

        def build() -> AnthropicClient:
            return AnthropicClient(
                conn,
                _transport=httpx.MockTransport(
                    self._refusing_then_answering('thinking', calls)
                ),
            )

        with patch(
            'app.core.llm.secrets.decrypt_connection_secret',
            return_value='sk-ant-test',
        ):
            await build().complete(LlmRequest(prompt='ping', disable_reasoning=True))
            assert len(calls) == 2  # refused once, retried without the key
            assert remembered_rejections(conn) == frozenset({'thinking'})

            calls.clear()
            response = await build().complete(
                LlmRequest(prompt='ping', disable_reasoning=True)
            )

        assert response.content == 'pong'
        assert len(calls) == 1
        assert 'thinking' not in calls[0]
