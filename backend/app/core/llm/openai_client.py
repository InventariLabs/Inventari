"""OpenAI-compatible LLM client — the workhorse adapter for ``openrouter``
and ``custom`` (LM Studio / Ollama / vLLM / OpenAI itself).

The OpenAI chat/completions protocol is the common denominator across all
\"OpenAI-compatible\" providers. The
single behavioural divergence is the ``response_format={type:json_schema}``
toggle: OpenRouter accepts it for structured output, but local endpoints
(Ollama / LM Studio) reject it as unknown. The factory routes by provider
string, but this client decides on its own whether to send
``response_format`` — keyed on the provider id (openrouter = send full
``json_schema``, every other OpenAI-compatible provider = don't send).

Adapts ``LlmRequest`` ↔ provider JSON; raises ``RuntimeError`` on
provider HTTP errors. Never silently falls back to a different model
or empty content — the legacy ``vision/_openai_client.py`` ``default_models``
list pattern that masked upstream errors is gone.
"""

from __future__ import annotations

import base64
import re
from typing import Any, cast

import httpx

from app.core.db_retry import mark_external_effect
from app.core.llm._optional_payload import (
    rejected_optional_key,
    remember_rejected_key,
    remembered_rejections,
)
from app.core.llm._outbound import pin_llm_url, route_base_url
from app.core.llm.base import LlmRequest, LlmResponse
from app.core.llm.diagnostics import log_answer
from app.core.llm.enums import LlmProvider
from app.core.llm.errors import provider_refusal, transport_failure
from app.core.llm.timeouts import request_timeout
from app.core.logging import get_logger

logger = get_logger(__name__)

# Endpoints that ignore ``response_format``. Anything in the OpenAI-compatible
# tier other than ``openrouter`` (LM Studio, Ollama, vLLM, OpenAI itself)
# treats ``response_format`` as an unknown key and returns 400.
_REQUIRES_JSON_FORMAT = {LlmProvider.OPENROUTER.value}

# Reasoning models (MiniMax-M3, DeepSeek-R1, QwQ, …) emit chain-of-thought
# wrapped in <think>…</think> *inside* ``content``; the usable answer follows
# the closing tag. Strip it so downstream JSON parsers see only the answer.
# (Anthropic / OpenAI o-series keep CoT in a separate field, so ``content`` is
# already clean — this is a no-op for them.)
_THINK_BLOCK = re.compile(r'<think>.*?</think>', re.DOTALL)
_UNCLOSED_THINK = re.compile(r'<think>.*$', re.DOTALL)


def _strip_reasoning(content: Any) -> str:
    """Remove ``<think>…</think>`` reasoning wrappers from model ``content``.

    Returns ``''`` for non-string content (some providers send ``null``).
    A trailing unclosed ``<think>`` (model cut off mid-thought, no answer
    produced) is dropped so callers see an empty result rather than raw CoT.
    """
    if not isinstance(content, str):
        return ''
    cleaned = _THINK_BLOCK.sub('', content)
    cleaned = _UNCLOSED_THINK.sub('', cleaned)
    return cleaned.strip()


class OpenAiCompatibleClient:
    """A pooled OpenAI-compatible LLM client.

    The constructor takes an :class:`AiConnection` (whose ``api_key_enc``
    is Fernet ciphertext, decrypted on first call) plus an optional
    transport override used in tests to inject :class:`httpx.MockTransport`.
    """

    def __init__(
        self,
        connection: Any,  # app.models.ai_connection.AiConnection — avoid hard import
        *,
        _transport: httpx.MockTransport | None = None,
    ) -> None:
        self._conn = connection
        self._transport = _transport

    @property
    def connection_name(self) -> str | None:
        # ``getattr``: the diagnostics on the answer path read this, and a
        # log line must not be able to take down the request that produced
        # it. A transient connection built from environment variables has
        # never been named.
        return cast(str | None, getattr(self._conn, 'name', None))

    @property
    def connection_provider(self) -> str | None:
        # ``getattr`` for the same reason as connection_name: the usage
        # ledger reads this after every call, and bookkeeping must not be
        # able to take down the request it bills.
        return cast(str | None, getattr(self._conn, 'provider', None))

    @property
    def model_name(self) -> str | None:
        return cast(str | None, self._conn.model_name)

    async def complete(self, request: LlmRequest) -> LlmResponse:
        # A provider call is billed and answered once; a request whose
        # transaction later deadlocks must not repeat it (db_retry).
        mark_external_effect('llm:complete')
        payload = self._build_payload(request)
        # A refusal this connection's route already voiced is not paid for
        # again: the key comes off the payload before the first attempt.
        for refused_key in remembered_rejections(self._conn):
            payload.pop(refused_key, None)
        url = route_base_url(self._conn) + '/chat/completions'
        target = pin_llm_url(url)

        # Decrypt at request time. Plaintext values (legacy migracji)
        # pass through unchanged via the crypto_service pass-through.
        from app.core.llm.secrets import decrypt_connection_secret

        api_key = decrypt_connection_secret(self._conn.api_key_enc)
        headers = target.with_host_header(
            {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}' if api_key else '',
            }
        )

        transport: httpx.AsyncBaseTransport | None = self._transport
        if transport is None:
            transport = httpx.AsyncHTTPTransport()

        # A provider that was never reached is not a provider that answered
        # badly: `httpx` transport failures inherit from none of the types a
        # router catches, so an unreachable endpoint used to leave image
        # recognition as a bare HTTP 500 (see `LlmTransportError`).
        try:
            async with httpx.AsyncClient(
                transport=transport,
                timeout=request_timeout(self.connection_provider),
            ) as client:
                response = await client.post(
                    target.url,
                    json=payload,
                    headers=headers,
                    extensions=target.extensions,
                )

                # Graceful degrade: a provider that does not know one of the
                # optional keys answers 400 rather than ignoring it. Drop the
                # key it named and ask again — the whole request is worth more
                # than the key.
                rejected = rejected_optional_key(response, payload)
                if rejected is not None:
                    remember_rejected_key(self._conn, rejected)
                    logger.warning(
                        'Provider %s rejected %r; retrying without it and '
                        'skipping it for the next hour',
                        self._conn.provider,
                        rejected,
                    )
                    payload = {
                        key: value for key, value in payload.items() if key != rejected
                    }
                    response = await client.post(
                        target.url,
                        json=payload,
                        headers=headers,
                        extensions=target.extensions,
                    )
        except httpx.HTTPError as exc:
            raise transport_failure(
                exc,
                connection_name=self.connection_name,
                model_name=self.model_name,
            ) from exc

        if response.status_code >= 400:
            raise provider_refusal(
                response.status_code,
                response.text,
                what='OpenAI-compatible provider',
                connection_name=self.connection_name,
                model_name=self.model_name,
            )

        data = response.json()
        choice = (data.get('choices') or [{}])[0]
        raw_content = choice.get('message', {}).get('content', '')
        content = _strip_reasoning(raw_content)
        usage = data.get('usage', {}) or {}
        finish_reason = choice.get('finish_reason') or None
        log_answer(
            logger,
            content=content,
            raw_content=raw_content,
            finish_reason=finish_reason,
            usage=usage,
            connection_name=self.connection_name,
            model_name=self.model_name,
        )
        return LlmResponse(
            content=content,
            usage=usage,
            raw=data,
            finish_reason=finish_reason,
        )

    def _build_payload(self, request: LlmRequest) -> dict[str, Any]:
        """Compose the chat/completions request body.

        Conventions:
        - ``model`` always comes from the connection row, never from
          the request — the model is part of the pool entry, not a
          per-call choice.
        - ``messages`` is always ``[system?, user(text or parts)]``.
        - ``temperature``/``max_tokens``: per-call overrides win over
          connection defaults (caller's right to opt into model-
          specific sampling without defining a new connection row).
        - ``top_p`` is forwarded for completeness — provider-specific
          meaning (some treat it as exclusive of temperature, others
          as a default), so the connection row controls it.
        - ``response_format`` is added only for providers that honour
          it (see module docstring).
        """
        messages: list[dict[str, Any]] = []
        if request.system_prompt:
            messages.append({'role': 'system', 'content': request.system_prompt})

        if request.images:
            # Multimodal: content is a list of parts.
            parts: list[dict[str, Any]] = [{'type': 'text', 'text': request.prompt}]
            for image_bytes in request.images:
                b64 = base64.b64encode(image_bytes).decode()
                # Default to PNG; the byte-prefix sniffing that
                # legacy vision used is dropped here — callers pass
                # PNG/JPEG already. Generic MIME unknown -> octet-stream.
                mime = 'image/png'
                parts.append(
                    {
                        'type': 'image_url',
                        'image_url': {
                            'url': f'data:{mime};base64,{b64}',
                        },
                    }
                )
            messages.append({'role': 'user', 'content': parts})
        else:
            # Text-only: content is the plain string.
            messages.append({'role': 'user', 'content': request.prompt})

        payload: dict[str, Any] = {
            'model': self._conn.model_name,
            'messages': messages,
        }

        # Per-call overrides win over connection defaults.
        if request.temperature is not None:
            payload['temperature'] = request.temperature
        elif self._conn.temperature is not None:
            payload['temperature'] = self._conn.temperature

        if request.max_tokens is not None:
            payload['max_tokens'] = request.max_tokens
        elif self._conn.max_tokens is not None:
            payload['max_tokens'] = self._conn.max_tokens

        if self._conn.top_p is not None:
            payload['top_p'] = self._conn.top_p

        if request.json_schema and self._conn.provider in _REQUIRES_JSON_FORMAT:
            payload['response_format'] = {
                'type': 'json_schema',
                'json_schema': {
                    'name': 'extract',
                    'strict': True,
                    'schema': request.json_schema,
                },
            }

        if request.disable_reasoning:
            # No universal off-switch exists: OpenRouter honors ``reasoning``,
            # MiniMax/Anthropic-style endpoints honor ``thinking``. Providers
            # without a documented toggle (OpenAI strict, local servers)
            # either ignore the extra key or were never reasoning models.
            if self._conn.provider == LlmProvider.OPENROUTER.value:
                payload['reasoning'] = {'enabled': False}
            else:
                payload['thinking'] = {'type': 'disabled'}

        return payload

    async def list_models(self) -> list[str]:
        """Lightweight GET /models — backs the Test-connection endpoint.

        OpenAI shape: ``{data: [{id: ...}]}``. Some local servers (LM
        Studio, llama.cpp) return ``{models: [{id|name: ...}]}`` — be
        permissive so the same code path serves both.
        """
        mark_external_effect('llm:list-models')
        url = route_base_url(self._conn) + '/models'
        target = pin_llm_url(url)

        from app.core.llm.secrets import decrypt_connection_secret

        api_key = decrypt_connection_secret(self._conn.api_key_enc)
        headers: dict[str, str] = {}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        headers = target.with_host_header(headers)

        transport: httpx.AsyncBaseTransport | None = self._transport
        if transport is None:
            transport = httpx.AsyncHTTPTransport()

        try:
            async with httpx.AsyncClient(transport=transport, timeout=30.0) as client:
                response = await client.get(
                    target.url, headers=headers, extensions=target.extensions
                )
        except httpx.HTTPError as exc:
            raise transport_failure(
                exc,
                connection_name=self.connection_name,
                model_name=self.model_name,
            ) from exc

        if response.status_code >= 400:
            raise provider_refusal(
                response.status_code,
                response.text,
                what='OpenAI-compatible list_models',
                connection_name=self.connection_name,
                model_name=self.model_name,
            )
        data = response.json()
        items = data.get('data') or data.get('models') or []
        return [
            m.get('id') or m.get('name') or ''
            for m in items
            if m.get('id') or m.get('name')
        ]
