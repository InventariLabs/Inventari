"""Unit tests for app.core.llm.openai_client.

We mock the HTTP layer with :mod:`httpx.MockTransport` — no live API
calls. The contract we pin is the request body shape (especially for
the ``response_format={type:'json_object'}`` toggle that OpenRouter
requires for structured output, and the base64 data-URI for image
parts) plus the response adaptation (provider → ``LlmResponse``).

Critical regression: the legacy ``vision/_openai_client.py`` had
fallback chains (``default_models`` list) that masked real provider
errors. The Core client must NOT silently fall back — it raises and
the caller decides what to do.
"""

import json

import httpx
import pytest

from app.core.llm.base import LlmRequest


@pytest.fixture(autouse=True)
def _no_real_dns(stub_dns):
    """These tests are about the request payload; the SSRF guard resolves
    the host first, and that must never reach the network. The guard's own
    answers to a name that does not resolve are pinned with ``stub_dns.fails``
    in ``test_llm_outbound_pinning.py``."""


def _make_connection(provider='openrouter', api_key='sk-or-test', base_url=''):
    """Build an AiConnection in-memory without DB I/O."""
    import uuid as _uuid

    from app.models.ai_connection import AiConnection

    if not base_url:
        base_url = (
            'https://openrouter.ai/api/v1'
            if provider == 'openrouter'
            else 'http://example.com/v1'
        )
    return AiConnection(
        organization_id=_uuid.UUID('00000000-0000-0000-0000-000000000001'),
        name='test',
        provider=provider,
        api_key_enc=api_key,
        api_base_url=base_url,
        model_name='gemini-2.0-flash',
        capabilities=['vision', 'text'],
    )


class TestOpenAiCompatibleClientText:
    async def test_text_only_request_shape(self):
        """Minimal text request: POST to {base_url}/chat/completions
        with role+content (no image parts), Authorization header,
        response_format absent (toggled by json_schema separately)."""
        from app.core.llm.openai_client import OpenAiCompatibleClient

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured['url'] = str(request.url)
            captured['body'] = json.loads(request.content.decode())
            captured['headers'] = dict(request.headers)
            return httpx.Response(
                200,
                json={
                    'choices': [{'message': {'content': 'pong'}}],
                    'usage': {
                        'prompt_tokens': 5,
                        'completion_tokens': 3,
                        'total_tokens': 8,
                    },
                },
            )

        conn = _make_connection()
        client = OpenAiCompatibleClient(conn, _transport=httpx.MockTransport(handler))
        req = LlmRequest(prompt='ping')
        response = await client.complete(req)

        assert response.content == 'pong'
        assert response.usage == {
            'prompt_tokens': 5,
            'completion_tokens': 3,
            'total_tokens': 8,
        }
        assert captured['url'].endswith('/chat/completions')
        assert captured['body']['model'] == 'gemini-2.0-flash'
        body_messages = captured['body']['messages']
        assert len(body_messages) == 1
        # The single message has role=user + text content only
        assert body_messages[0]['role'] == 'user'
        assert body_messages[0]['content'] == 'ping'
        # No `response_format` on a plain text request
        assert 'response_format' not in captured['body']
        assert captured['headers']['authorization'] == 'Bearer sk-or-test'

    async def test_strips_reasoning_think_block_from_content(self):
        """Reasoning models (MiniMax-M3, DeepSeek-R1, QwQ, ...) wrap their
        chain-of-thought in <think>...</think> inside ``content``; the real
        answer follows the closing tag. The client must surface only the
        answer so JSON parsers downstream don't choke on the leading '<'
        (regression: Vision extraction returned JSONDecodeError char 0)."""
        from app.core.llm.openai_client import OpenAiCompatibleClient

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    'choices': [
                        {
                            'message': {
                                'content': (
                                    '<think>\nThe user wants JSON.\n'
                                    '</think>{"name":"unknown"}'
                                )
                            }
                        }
                    ],
                    'usage': {'prompt_tokens': 10, 'completion_tokens': 5},
                },
            )

        conn = _make_connection()
        client = OpenAiCompatibleClient(conn, _transport=httpx.MockTransport(handler))
        response = await client.complete(LlmRequest(prompt='extract'))

        assert response.content == '{"name":"unknown"}'

    async def test_json_schema_sets_response_format_for_openrouter(self):
        """Per legacy behavior in vision/_openai_client.py:
        ``response_format={type:'json_object'}`` is required by OpenRouter
        for structured output. The key MUST be absent for custom
        endpoints that don't honour it (Ollama rejects it)."""
        from app.core.llm.openai_client import OpenAiCompatibleClient

        # OpenRouter: response_format must be set
        captured_or = {}

        def handler_or(request: httpx.Request) -> httpx.Response:
            captured_or['body'] = json.loads(request.content.decode())
            return httpx.Response(
                200, json={'choices': [{'message': {'content': '{}'}}]}
            )

        conn_or = _make_connection(provider='openrouter')
        client_or = OpenAiCompatibleClient(
            conn_or, _transport=httpx.MockTransport(handler_or)
        )
        await client_or.complete(
            LlmRequest(
                prompt='extract',
                json_schema={
                    'type': 'object',
                    'properties': {'x': {'type': 'number'}},
                },
            )
        )
        assert captured_or['body']['response_format'] == {
            'type': 'json_schema',
            'json_schema': {
                'name': 'extract',
                'strict': True,
                'schema': {
                    'type': 'object',
                    'properties': {'x': {'type': 'number'}},
                },
            },
        }, 'OpenRouter must receive the full json_schema response_format'

    async def test_json_schema_omits_response_format_for_custom(self, monkeypatch):
        """Custom endpoints (LM Studio/Ollama) reject ``response_format``
        as unknown. The key MUST be absent even when json_schema is set."""
        from app.core.llm.openai_client import OpenAiCompatibleClient

        captured_cu = {}

        def handler_cu(request: httpx.Request) -> httpx.Response:
            captured_cu['body'] = json.loads(request.content.decode())
            return httpx.Response(
                200, json={'choices': [{'message': {'content': '{}'}}]}
            )

        # A local Ollama is a private address — the SSRF guard only lets it
        # through when the operator opted in.
        from app.config import settings

        monkeypatch.setattr(settings, 'LLM_ALLOW_PRIVATE_NETWORKS', True)

        conn_cu = _make_connection(
            provider='custom',
            base_url='http://localhost:11434/v1',
        )
        client_cu = OpenAiCompatibleClient(
            conn_cu, _transport=httpx.MockTransport(handler_cu)
        )
        await client_cu.complete(
            LlmRequest(
                prompt='extract',
                json_schema={
                    'type': 'object',
                    'properties': {'x': {'type': 'number'}},
                },
            )
        )
        assert 'response_format' not in captured_cu['body'], (
            'Custom endpoints (LM Studio/Ollama) must NOT receive '
            'response_format — it is an OpenAI-only param'
        )

    async def test_text_with_system_prompt_appends_system_role(self):
        """``system_prompt`` becomes the first message with role=system,
        NOT a prefix on the user message."""
        from app.core.llm.openai_client import OpenAiCompatibleClient

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured['body'] = json.loads(request.content.decode())
            return httpx.Response(
                200, json={'choices': [{'message': {'content': 'ok'}}]}
            )

        conn = _make_connection()
        client = OpenAiCompatibleClient(conn, _transport=httpx.MockTransport(handler))
        await client.complete(
            LlmRequest(
                prompt='hi',
                system_prompt='you are concise',
            )
        )
        msgs = captured['body']['messages']
        assert msgs[0]['role'] == 'system'
        assert msgs[0]['content'] == 'you are concise'
        assert msgs[1]['role'] == 'user'
        assert msgs[1]['content'] == 'hi'


class TestOpenAiCompatibleClientMultimodal:
    async def test_image_bytes_become_base64_data_uri(self):
        """``LlmRequest.images: list[bytes]`` becomes a list of
        ``image_url`` content parts with base64 data URIs. PNG bytes
        are encoded as ``data:image/png;base64,...``."""
        from app.core.llm.openai_client import OpenAiCompatibleClient

        png_bytes = b'\x89PNG\r\n\x1a\n' + b'fake-image-bytes'
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured['body'] = json.loads(request.content.decode())
            return httpx.Response(
                200, json={'choices': [{'message': {'content': 'seen'}}]}
            )

        conn = _make_connection()
        client = OpenAiCompatibleClient(conn, _transport=httpx.MockTransport(handler))
        await client.complete(LlmRequest(prompt='describe', images=[png_bytes]))
        content = captured['body']['messages'][0]['content']
        assert isinstance(content, list)
        # First part = text prompt, subsequent parts = images.
        assert content[0]['type'] == 'text'
        assert content[0]['text'] == 'describe'
        assert content[1]['type'] == 'image_url'
        url = content[1]['image_url']['url']
        assert url.startswith('data:image/png;base64,')

    async def test_empty_images_list_treated_as_text_only(self):
        """``images=[]`` (empty list) must collapse to text-only mode —
        otherwise we send an empty image parts array which some
        providers reject."""
        from app.core.llm.openai_client import OpenAiCompatibleClient

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured['body'] = json.loads(request.content.decode())
            return httpx.Response(
                200, json={'choices': [{'message': {'content': 'ok'}}]}
            )

        conn = _make_connection()
        client = OpenAiCompatibleClient(conn, _transport=httpx.MockTransport(handler))
        await client.complete(LlmRequest(prompt='hi', images=[]))
        # content should be the string prompt (text mode), not a list
        assert captured['body']['messages'][0]['content'] == 'hi'


class TestOpenAiCompatibleClientErrors:
    async def test_http_error_raises_runtime_error(self):
        """Provider errors (4xx/5xx) must surface as RuntimeError with
        the upstream status. Callers handle it; we don't fake success
        by silently mapping to empty content (the legacy fallback
        pattern that hid real bugs)."""
        from app.core.llm.openai_client import OpenAiCompatibleClient

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={'error': 'invalid api key'})

        conn = _make_connection()
        client = OpenAiCompatibleClient(conn, _transport=httpx.MockTransport(handler))
        with pytest.raises(RuntimeError) as exc_info:
            await client.complete(LlmRequest(prompt='hi'))
        assert '401' in str(exc_info.value) or '401' in repr(exc_info.value)


class TestParametersForwarding:
    async def test_temperature_max_tokens_top_p_forwarded(self):
        """Connection defaults AND per-call overrides both reach the
        payload. Per-call overrides win, matching the documented
        semantics on LlmRequest."""
        from app.core.llm.openai_client import OpenAiCompatibleClient

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured['body'] = json.loads(request.content.decode())
            return httpx.Response(
                200, json={'choices': [{'message': {'content': 'ok'}}]}
            )

        conn = _make_connection()
        conn.temperature = 0.5
        conn.max_tokens = 1024
        client = OpenAiCompatibleClient(conn, _transport=httpx.MockTransport(handler))

        # No per-call override — connection defaults sent.
        await client.complete(LlmRequest(prompt='a'))
        assert captured['body']['temperature'] == 0.5
        assert captured['body']['max_tokens'] == 1024

        # Per-call override wins.
        captured.clear()
        await client.complete(LlmRequest(prompt='b', temperature=0.1, max_tokens=64))
        assert captured['body']['temperature'] == 0.1
        assert captured['body']['max_tokens'] == 64


class TestDisableReasoning:
    async def test_not_sent_by_default(self):
        from app.core.llm.openai_client import OpenAiCompatibleClient

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured['body'] = json.loads(request.content.decode())
            return httpx.Response(
                200, json={'choices': [{'message': {'content': 'ok'}}]}
            )

        conn = _make_connection()
        client = OpenAiCompatibleClient(conn, _transport=httpx.MockTransport(handler))
        await client.complete(LlmRequest(prompt='a'))
        assert 'reasoning' not in captured['body']
        assert 'thinking' not in captured['body']

    async def test_openrouter_gets_reasoning_enabled_false(self):
        from app.core.llm.openai_client import OpenAiCompatibleClient

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured['body'] = json.loads(request.content.decode())
            return httpx.Response(
                200, json={'choices': [{'message': {'content': 'ok'}}]}
            )

        conn = _make_connection(provider='openrouter')
        client = OpenAiCompatibleClient(conn, _transport=httpx.MockTransport(handler))
        await client.complete(LlmRequest(prompt='a', disable_reasoning=True))
        assert captured['body']['reasoning'] == {'enabled': False}
        assert 'thinking' not in captured['body']

    async def test_custom_provider_gets_thinking_disabled(self):
        """MiniMax/Anthropic-style endpoints honor ``thinking: disabled``;
        verified against api.minimax.io (reasoning_tokens drop to zero)."""
        from app.core.llm.openai_client import OpenAiCompatibleClient

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured['body'] = json.loads(request.content.decode())
            return httpx.Response(
                200, json={'choices': [{'message': {'content': 'ok'}}]}
            )

        conn = _make_connection(provider='custom')
        client = OpenAiCompatibleClient(conn, _transport=httpx.MockTransport(handler))
        await client.complete(LlmRequest(prompt='a', disable_reasoning=True))
        assert captured['body']['thinking'] == {'type': 'disabled'}
        assert 'reasoning' not in captured['body']


class TestStructuredOutputDegrade:
    async def test_payload_without_json_schema_snapshot(self):
        """Regression: a request without ``json_schema`` must produce a
        payload with exactly the pre-change keys — no ``response_format``,
        no ``reasoning``/``thinking``, no sampling leakage."""
        from app.core.llm.openai_client import OpenAiCompatibleClient

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured['body'] = json.loads(request.content.decode())
            return httpx.Response(
                200, json={'choices': [{'message': {'content': 'ok'}}]}
            )

        conn = _make_connection()
        client = OpenAiCompatibleClient(conn, _transport=httpx.MockTransport(handler))
        await client.complete(LlmRequest(prompt='hi'))

        assert set(captured['body'].keys()) == {'model', 'messages'}

    async def test_retries_without_response_format_on_400_mentioning_it(self):
        """Some OpenRouter models do not support ``response_format=json_schema``
        and answer 400. The client degrades to prompt-only exactly once."""
        from app.core.llm.openai_client import OpenAiCompatibleClient

        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode())
            calls.append(body)
            if 'response_format' in body:
                return httpx.Response(
                    400,
                    json={
                        'error': {
                            'message': (
                                'response_format json_schema is not supported '
                                'for this model'
                            )
                        }
                    },
                )
            return httpx.Response(
                200, json={'choices': [{'message': {'content': '{}'}}]}
            )

        conn = _make_connection(provider='openrouter')
        client = OpenAiCompatibleClient(conn, _transport=httpx.MockTransport(handler))
        response = await client.complete(
            LlmRequest(
                prompt='extract',
                json_schema={
                    'type': 'object',
                    'properties': {'x': {'type': 'number'}},
                },
            )
        )

        assert response.content == '{}'
        assert len(calls) == 2
        assert 'response_format' in calls[0]
        assert 'response_format' not in calls[1]

    async def test_400_without_response_format_mention_does_not_retry(self):
        """A 400 that is unrelated to structured output must surface as-is —
        retrying on every 400 would mask genuine request errors."""
        from app.core.llm.openai_client import OpenAiCompatibleClient

        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(400, json={'error': {'message': 'bad request'}})

        conn = _make_connection(provider='openrouter')
        client = OpenAiCompatibleClient(conn, _transport=httpx.MockTransport(handler))
        with pytest.raises(RuntimeError, match='400'):
            await client.complete(
                LlmRequest(
                    prompt='extract',
                    json_schema={'type': 'object'},
                )
            )
        assert len(calls) == 1
