"""Unit tests for app.core.llm.google_client.

The client speaks the ``google.genai`` SDK; the ``google.generativeai``
package it replaced was end-of-lifed by Google and its
``GenerationConfig`` never grew a ``thinking_config``, which made
``disable_reasoning`` a silent no-op on this one provider. The client must:

- Generic on the input/output surface (takes ``LlmRequest``,
  returns ``LlmResponse``).
- Build a ``genai.Client`` per call from the decrypted key, so key
  rotation through replacing an ``AiConnection`` row behaves.
- Strip the ``google/`` model-name prefix (OpenRouter routing uses
  names like ``google/gemini-2.0-flash``, but the native SDK expects
  ``gemini-2.0-flash``).
- Multimodal via inline ``PIL.Image`` (the SDK's native type), not
  base64 strings — different shape from the OpenAI client.
- Map ``disable_reasoning`` to a zero ``thinking_budget`` — the switch
  that keeps a reasoning model from answering with an empty string
  under a fixed token budget.

These tests mock ``google.genai`` at the ``sys.modules`` level so we
don't need a live API key or hit the network.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_connection(
    model_name='gemini-2.0-flash',
    api_key='google-test-key',
    provider='google',
):
    """Build an AiConnection in-memory without DB I/O."""
    import uuid as _uuid

    from app.models.ai_connection import AiConnection

    return AiConnection(
        organization_id=_uuid.UUID('00000000-0000-0000-0000-000000000001'),
        name='test',
        provider=provider,
        api_key_enc=api_key,
        api_base_url='',
        model_name=model_name,
        capabilities=['vision', 'text'],
    )


def _install_genai_mock(monkeypatch, response_text: str) -> dict:
    """Install a fake ``google.genai`` module tree on ``sys.modules``.

    Returns a dict with refs the tests can introspect. All three names
    (``google``, ``google.genai``, ``google.genai.types``) are replaced,
    because the real ``google-genai`` package may be installed and would
    otherwise win the resolution.

    NOTE: this project does not have ``pytest-mock``, so we use
    ``monkeypatch.setitem`` on ``sys.modules`` instead.
    """
    usage = MagicMock()
    usage.prompt_token_count = 7
    usage.candidates_token_count = 4
    usage.total_token_count = 11

    response_obj = MagicMock()
    response_obj.text = response_text
    response_obj.usage_metadata = usage

    async def _async_response(*args, **kwargs):
        return response_obj

    async_models = MagicMock()
    async_models.generate_content = AsyncMock(side_effect=_async_response)
    client_instance = MagicMock()
    client_instance.aio.models = async_models
    # list_models() walks client.models.list() in a worker thread.
    client_instance.models.list.return_value = iter([])

    def _client_factory(*, api_key, http_options=None):
        return client_instance

    client_cls = MagicMock(side_effect=_client_factory)

    thinking_config = MagicMock()

    fake_types = types.ModuleType('google.genai.types')
    fake_types.ThinkingConfig = thinking_config

    fake_genai = types.ModuleType('google.genai')
    fake_genai.Client = client_cls
    fake_genai.types = fake_types

    fake_google = types.ModuleType('google')
    fake_google.genai = fake_genai

    monkeypatch.setitem(sys.modules, 'google', fake_google)
    monkeypatch.setitem(sys.modules, 'google.genai', fake_genai)
    monkeypatch.setitem(sys.modules, 'google.genai.types', fake_types)

    return {
        'client_cls': client_cls,
        'client_instance': client_instance,
        'generate_content': async_models.generate_content,
        'thinking_config': thinking_config,
        'response_obj': response_obj,
    }


def _generate_config(fakes: dict) -> dict:
    """The ``config`` kwarg of the single generate_content call."""
    return fakes['generate_content'].call_args.kwargs['config']


class TestGoogleClientText:
    async def test_text_only_calls_generate_content(self, monkeypatch):
        from app.core.llm.base import LlmRequest
        from app.core.llm.google_client import GoogleClient

        fakes = _install_genai_mock(monkeypatch, response_text='hello back')

        response = await GoogleClient(
            _make_connection(model_name='gemini-2.0-flash')
        ).complete(LlmRequest(prompt='hi'))

        # SDK client was built with the decrypted API key.
        fakes['client_cls'].assert_called_once()
        assert fakes['client_cls'].call_args.kwargs['api_key'] == 'google-test-key'

        # generate_content was invoked exactly once, for this model.
        fakes['generate_content'].assert_awaited_once()
        kwargs = fakes['generate_content'].call_args.kwargs
        assert kwargs['model'] == 'gemini-2.0-flash'
        # Text-only mode passes ``[prompt]`` (a list of one string).
        assert kwargs['contents'] == ['hi']

        # Response is adapted to LlmResponse.
        assert response.content == 'hello back'
        assert response.usage == {
            'prompt_tokens': 7,
            'completion_tokens': 4,
            'total_tokens': 11,
        }

    async def test_google_prefix_stripped_from_model_name(self, monkeypatch):
        """OpenRouter-style ``google/<model>`` names are stored on the
        connection row when the user picks Google via OpenRouter. The
        native SDK rejects ``google/google/<model>``, so we strip it
        once before calling the SDK."""
        from app.core.llm.base import LlmRequest
        from app.core.llm.google_client import GoogleClient

        fakes = _install_genai_mock(monkeypatch, response_text='ok')

        conn = _make_connection(model_name='google/gemini-2.0-flash')
        await GoogleClient(conn).complete(LlmRequest(prompt='hi'))

        kwargs = fakes['generate_content'].call_args.kwargs
        assert kwargs['model'] == 'gemini-2.0-flash'

    async def test_text_with_system_prompt_becomes_first_part(self, monkeypatch):
        from app.core.llm.base import LlmRequest
        from app.core.llm.google_client import GoogleClient

        fakes = _install_genai_mock(monkeypatch, response_text='ok')

        await GoogleClient(_make_connection()).complete(
            LlmRequest(prompt='hi', system_prompt='be brief')
        )

        parts = fakes['generate_content'].call_args.kwargs['contents']
        assert parts == ['be brief', 'hi']

    async def test_image_bytes_become_pil_image_parts(self, monkeypatch):
        """``LlmRequest.images: list[bytes]`` becomes ``PIL.Image.Image``
        instances in the parts list. Bytes are wrapped in ``BytesIO``
        before being handed to ``Image.open()`` — no temp files."""
        from app.core.llm.base import LlmRequest
        from app.core.llm.google_client import GoogleClient

        fakes = _install_genai_mock(monkeypatch, response_text='seen')
        from PIL import Image as PILImage

        class _FakeImage:
            def __init__(self, _b: bytes):
                self.format = 'PNG'

            def close(self):
                pass

        def fake_open(buf, *a, **kw):
            # Don't actually parse bytes — just verify the buf type
            # (BytesIO).
            assert hasattr(buf, 'read')
            return _FakeImage(buf)

        monkeypatch.setattr(PILImage, 'open', fake_open)

        png_bytes = b'\x89PNG\r\n\x1a\n' + b'any'
        await GoogleClient(_make_connection()).complete(
            LlmRequest(prompt='describe', images=[png_bytes])
        )

        parts = fakes['generate_content'].call_args.kwargs['contents']
        # First part is the text prompt, subsequent parts are PIL images.
        assert parts[0] == 'describe'
        assert isinstance(parts[1], _FakeImage)


class TestGoogleClientDisableReasoning:
    async def test_disable_reasoning_sets_a_zero_thinking_budget(self, monkeypatch):
        """The switch exists for this: a reasoning model under a fixed
        token budget spent it all on thought tokens and answered with an
        empty string. A zero budget turns the thinking off, so the budget
        lands in content."""
        from app.core.llm.base import LlmRequest
        from app.core.llm.google_client import GoogleClient

        fakes = _install_genai_mock(monkeypatch, response_text='the answer')

        await GoogleClient(_make_connection()).complete(
            LlmRequest(prompt='read the label', disable_reasoning=True)
        )

        gen_config = _generate_config(fakes)
        fakes['thinking_config'].assert_called_once_with(thinking_budget=0)
        assert gen_config['thinking_config'] is fakes['thinking_config'].return_value

    async def test_reasoning_left_alone_by_default(self, monkeypatch):
        """A caller who did not ask for the switch gets no thinking
        config at all — the model keeps its provider-default behaviour."""
        from app.core.llm.base import LlmRequest
        from app.core.llm.google_client import GoogleClient

        fakes = _install_genai_mock(monkeypatch, response_text='ok')

        await GoogleClient(_make_connection()).complete(LlmRequest(prompt='hi'))

        assert 'thinking_config' not in _generate_config(fakes)


class TestGoogleClientGenerationConfig:
    async def test_params_forwarded_to_generation_config(self, monkeypatch):
        from app.core.llm.base import LlmRequest
        from app.core.llm.google_client import GoogleClient

        fakes = _install_genai_mock(monkeypatch, response_text='ok')

        conn = _make_connection()
        conn.temperature = 0.3
        conn.max_tokens = 512
        conn.top_p = 0.9
        await GoogleClient(conn).complete(LlmRequest(prompt='hi'))

        gen_config = _generate_config(fakes)
        assert gen_config['temperature'] == 0.3
        assert gen_config['max_output_tokens'] == 512
        assert gen_config['top_p'] == 0.9

    async def test_per_call_overrides_win_over_the_connection_row(self, monkeypatch):
        from app.core.llm.base import LlmRequest
        from app.core.llm.google_client import GoogleClient

        fakes = _install_genai_mock(monkeypatch, response_text='ok')

        conn = _make_connection()
        conn.temperature = 0.3
        await GoogleClient(conn).complete(
            LlmRequest(prompt='hi', temperature=0.7, max_tokens=64)
        )

        gen_config = _generate_config(fakes)
        assert gen_config['temperature'] == 0.7
        assert gen_config['max_output_tokens'] == 64

    async def test_json_schema_sets_response_schema_alongside_mime_type(
        self, monkeypatch
    ):
        from app.core.llm.base import LlmRequest
        from app.core.llm.google_client import GoogleClient

        fakes = _install_genai_mock(monkeypatch, response_text='{}')

        schema = {'type': 'object', 'properties': {'x': {'type': 'number'}}}
        await GoogleClient(_make_connection()).complete(
            LlmRequest(prompt='extract', json_schema=schema)
        )

        gen_config = _generate_config(fakes)
        assert gen_config['response_mime_type'] == 'application/json'
        assert gen_config['response_schema'] == schema

    async def test_no_json_schema_omits_response_mime_type(self, monkeypatch):
        from app.core.llm.base import LlmRequest
        from app.core.llm.google_client import GoogleClient

        fakes = _install_genai_mock(monkeypatch, response_text='ok')

        await GoogleClient(_make_connection()).complete(LlmRequest(prompt='hi'))

        assert 'response_mime_type' not in _generate_config(fakes)

    async def test_json_schema_degrades_to_mime_type_on_sdk_error(self, monkeypatch):
        from app.core.llm.base import LlmRequest
        from app.core.llm.google_client import GoogleClient

        fakes = _install_genai_mock(monkeypatch, response_text='{}')
        calls = {'n': 0}

        async def _flaky(*args, **kwargs):
            calls['n'] += 1
            if calls['n'] == 1:
                raise TypeError('response_schema: unsupported anyOf')
            return fakes['response_obj']

        fakes['generate_content'].side_effect = _flaky

        response = await GoogleClient(_make_connection()).complete(
            LlmRequest(prompt='extract', json_schema={'type': 'object'})
        )

        assert response.content == '{}'
        assert calls['n'] == 2
        second_config = fakes['generate_content'].call_args_list[1].kwargs['config']
        assert 'response_schema' not in second_config
        assert second_config['response_mime_type'] == 'application/json'


class TestGoogleClientLimits:
    """The SDK waits without end unless told; the client tells it."""

    async def test_a_completion_waits_the_configured_time(self, monkeypatch):
        from app.config import settings
        from app.core.llm.base import LlmRequest
        from app.core.llm.google_client import GoogleClient

        fakes = _install_genai_mock(monkeypatch, response_text='ok')
        monkeypatch.setattr(settings, 'LLM_REQUEST_TIMEOUT_SECONDS', 42)

        await GoogleClient(_make_connection()).complete(LlmRequest(prompt='hi'))

        # The SDK counts in milliseconds.
        options = fakes['client_cls'].call_args.kwargs['http_options']
        assert options['timeout'] == 42_000

    async def test_a_model_listing_waits_thirty_seconds(self, monkeypatch):
        from app.core.llm.google_client import GoogleClient

        fakes = _install_genai_mock(monkeypatch, response_text='ok')

        await GoogleClient(_make_connection()).list_models()

        options = fakes['client_cls'].call_args.kwargs['http_options']
        assert options['timeout'] == 30_000

    async def test_the_sdk_is_kept_on_httpx(self, monkeypatch):
        """Left to choose, the SDK takes aiohttp wherever something installed it.

        Its async calls then raise aiohttp's errors — ``OSError``s the vision
        route reads as an unreadable photograph — and nothing here names
        them. A transport of our own keeps them on httpx, whose failures the
        shared classifier reads for every provider.
        """
        import httpx

        from app.core.llm.base import LlmRequest
        from app.core.llm.google_client import GoogleClient

        fakes = _install_genai_mock(monkeypatch, response_text='ok')

        await GoogleClient(_make_connection()).complete(LlmRequest(prompt='hi'))

        options = fakes['client_cls'].call_args.kwargs['http_options']
        transport = options['async_client_args']['transport']
        assert isinstance(transport, httpx.AsyncHTTPTransport)


class TestGoogleClientOutages:
    """An outage is the transport failure every other client raises."""

    async def _complete_raising(self, monkeypatch, exc):
        from app.core.llm.base import LlmRequest
        from app.core.llm.google_client import GoogleClient

        fakes = _install_genai_mock(monkeypatch, response_text='ok')
        fakes['generate_content'].side_effect = exc
        await GoogleClient(_make_connection()).complete(LlmRequest(prompt='hi'))

    async def test_a_refused_connection_cannot_reach_the_provider(self, monkeypatch):
        import httpx

        from app.core.llm.errors import LlmTimeoutError, LlmTransportError

        with pytest.raises(LlmTransportError) as caught:
            await self._complete_raising(
                monkeypatch, httpx.ConnectError('connection refused')
            )
        assert not isinstance(caught.value, LlmTimeoutError)
        assert caught.value.connection_name == 'test'

    async def test_an_answer_that_never_came_is_a_timeout(self, monkeypatch):
        import httpx

        from app.core.llm.errors import LlmTimeoutError

        with pytest.raises(LlmTimeoutError):
            await self._complete_raising(monkeypatch, httpx.ReadTimeout('slow'))

    async def test_a_timeout_while_connecting_cannot_reach_the_provider(
        self, monkeypatch
    ):
        import httpx

        from app.core.llm.errors import LlmTimeoutError, LlmTransportError

        with pytest.raises(LlmTransportError) as caught:
            await self._complete_raising(monkeypatch, httpx.ConnectTimeout('connect'))
        assert not isinstance(caught.value, LlmTimeoutError)

    async def test_a_listing_that_cannot_reach_the_provider(self, monkeypatch):
        import httpx

        from app.core.llm.errors import LlmTransportError
        from app.core.llm.google_client import GoogleClient

        fakes = _install_genai_mock(monkeypatch, response_text='ok')
        fakes['client_instance'].models.list.side_effect = httpx.ConnectError('dns')

        with pytest.raises(LlmTransportError):
            await GoogleClient(_make_connection()).list_models()

    async def test_an_unrelated_fault_is_left_alone(self, monkeypatch):
        from app.core.llm.errors import LlmTransportError

        with pytest.raises(KeyError) as caught:
            await self._complete_raising(monkeypatch, KeyError('candidates'))
        assert not isinstance(caught.value, LlmTransportError)


class TestGoogleClientModuleShape:
    def test_module_import_does_not_require_sdk(self):
        """Just importing the module must not trigger the google.genai
        import — verify by removing it from sys.modules first."""
        saved = [
            (name, sys.modules.pop(name))
            for name in ('google', 'google.genai', 'google.genai.types')
            if name in sys.modules
        ]
        try:
            import importlib

            mod = importlib.import_module('app.core.llm.google_client')
            assert mod.GoogleClient is not None
            assert 'google.genai' not in sys.modules
        finally:
            for name, mod_obj in saved:
                sys.modules[name] = mod_obj
