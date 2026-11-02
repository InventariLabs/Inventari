"""Anthropic Messages API LLM client — native adapter.

Anthropic's API differs from the OpenAI-compatible shape in three ways
that matter for this adapter:

1. Auth: ``x-api-key`` header, not ``Authorization: Bearer``.
2. ``max_tokens`` is REQUIRED (no provider default) — this client falls
   back to 4096 when the connection row has none, rather than letting
   the API reject every call.
3. ``system`` is a top-level param, not a message in the ``messages``
   array. Multimodal images use ``{type:image, source:{type:base64,...}}``
   content blocks rather than OpenAI's ``image_url`` data-URI shape.

The connection row carries ``api_base_url`` defaulting to
``https://api.anthropic.com`` (the frontend descriptor seeds this on
connection creation).
"""

from __future__ import annotations

import base64
import json
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
from app.core.llm.errors import provider_refusal, transport_failure
from app.core.llm.timeouts import request_timeout
from app.core.logging import get_logger

logger = get_logger(__name__)

# Anthropic rejects requests without max_tokens; this fallback keeps
# bare connections working. Callers can override per-call or per-connection.
_DEFAULT_MAX_TOKENS = 4096
_ANTHROPIC_API_VERSION = '2023-06-01'


class AnthropicClient:
    """Anthropic native Messages API adapter."""

    def __init__(
        self,
        connection: Any,  # app.models.ai_connection.AiConnection
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
    def model_name(self) -> str | None:
        return cast(str | None, self._conn.model_name)

    @property
    def connection_provider(self) -> str | None:
        return cast(str | None, getattr(self._conn, 'provider', None))

    async def complete(self, request: LlmRequest) -> LlmResponse:
        # A provider call is billed and answered once; a request whose
        # transaction later deadlocks must not repeat it (db_retry).
        mark_external_effect('llm:complete')
        payload = self._build_payload(request)
        # Same memory as the OpenAI-compatible client: a refusal already
        # voiced by this connection is not paid for again.
        for refused_key in remembered_rejections(self._conn):
            payload.pop(refused_key, None)
        base_url = route_base_url(self._conn)
        url = base_url + '/v1/messages'
        target = pin_llm_url(url)

        from app.core.llm.secrets import decrypt_connection_secret

        api_key = decrypt_connection_secret(self._conn.api_key_enc)

        headers = target.with_host_header(
            {
                'Content-Type': 'application/json',
                'x-api-key': api_key or '',
                'anthropic-version': _ANTHROPIC_API_VERSION,
            }
        )

        transport: httpx.AsyncBaseTransport | None = self._transport
        if transport is None:
            transport = httpx.AsyncHTTPTransport()

        # See `LlmTransportError`: a provider that was never reached is not a
        # provider that answered badly, and `httpx` says so with exception
        # types no router thinks to catch.
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

                # A model with no extended thinking to switch off refuses the
                # switch rather than ignoring it, and the request is worth
                # more than the key: without it the model answers as it always
                # did. Same reasoning as the OpenAI-compatible client, which
                # carries the full note.
                rejected = rejected_optional_key(response, payload)
                if rejected is not None:
                    remember_rejected_key(self._conn, rejected)
                    logger.warning(
                        'Anthropic rejected %r; retrying without it and '
                        'skipping it for the next hour',
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
                what='Anthropic API',
                connection_name=self.connection_name,
                model_name=self.model_name,
            )

        data = response.json()
        content_blocks = data.get('content', [])
        # When the request asked for structured output, the model answers
        # through a forced ``tool_use`` block. Serialise its input back to
        # JSON so ``LlmResponse.content`` looks like the other clients'.
        tool_use_block = next(
            (block for block in content_blocks if block.get('type') == 'tool_use'),
            None,
        )
        if tool_use_block is not None:
            content = json.dumps(tool_use_block.get('input', {}))
        else:
            # Otherwise concatenate text blocks (legacy path).
            content = ''.join(
                block.get('text', '')
                for block in content_blocks
                if block.get('type') == 'text'
            )
        usage_raw = data.get('usage', {}) or {}
        # Normalise to the OpenAI-style keys the rest of the codebase uses.
        usage: dict[str, int] = {}
        if 'input_tokens' in usage_raw:
            usage['prompt_tokens'] = usage_raw['input_tokens']
        if 'output_tokens' in usage_raw:
            usage['completion_tokens'] = usage_raw['output_tokens']
        if 'input_tokens' in usage_raw and 'output_tokens' in usage_raw:
            usage['total_tokens'] = (
                usage_raw['input_tokens'] + usage_raw['output_tokens']
            )
        # Anthropic's word for "the budget ran out" is ``max_tokens``.
        finish_reason = data.get('stop_reason') or None
        log_answer(
            logger,
            content=content,
            raw_content=content,
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

    async def list_models(self) -> list[str]:
        """Lightweight GET /v1/models — backs the Test-connection endpoint."""
        mark_external_effect('llm:list-models')
        base_url = route_base_url(self._conn)
        url = base_url + '/v1/models'
        target = pin_llm_url(url)

        from app.core.llm.secrets import decrypt_connection_secret

        api_key = decrypt_connection_secret(self._conn.api_key_enc)

        headers = target.with_host_header(
            {
                'x-api-key': api_key or '',
                'anthropic-version': _ANTHROPIC_API_VERSION,
            }
        )

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
                what='Anthropic list_models',
                connection_name=self.connection_name,
                model_name=self.model_name,
            )
        data = response.json()
        return [m.get('id', '') for m in data.get('data', []) if m.get('id')]

    def _build_payload(self, request: LlmRequest) -> dict[str, Any]:
        """Compose the Messages API request body.

        - ``system`` is a top-level param (Anthropic convention).
        - ``messages`` is always ``[{role:user, content: str | blocks}]``.
        - ``max_tokens`` falls back to 4096 (API requires it).
        """
        payload: dict[str, Any] = {
            'model': self._conn.model_name,
            'max_tokens': _DEFAULT_MAX_TOKENS,
            'messages': [self._build_user_message(request)],
        }

        if request.system_prompt:
            payload['system'] = request.system_prompt

        # Per-call overrides win over connection defaults.
        if request.max_tokens is not None:
            payload['max_tokens'] = request.max_tokens
        elif self._conn.max_tokens is not None:
            payload['max_tokens'] = self._conn.max_tokens

        if request.temperature is not None:
            payload['temperature'] = request.temperature
        elif self._conn.temperature is not None:
            payload['temperature'] = self._conn.temperature

        if self._conn.top_p is not None:
            payload['top_p'] = self._conn.top_p

        if request.disable_reasoning:
            payload['thinking'] = {'type': 'disabled'}

        if request.json_schema:
            payload['tools'] = [
                {
                    'name': 'structured_response',
                    'description': 'Return the structured answer',
                    'input_schema': request.json_schema,
                }
            ]
            payload['tool_choice'] = {
                'type': 'tool',
                'name': 'structured_response',
            }

        return payload

    def _build_user_message(self, request: LlmRequest) -> dict[str, Any]:
        """Build the user message. Multimodal → list of content blocks."""
        if not request.images:
            return {'role': 'user', 'content': request.prompt}

        blocks: list[dict[str, Any]] = [{'type': 'text', 'text': request.prompt}]
        for image_bytes in request.images:
            b64 = base64.b64encode(image_bytes).decode()
            blocks.append(
                {
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': 'image/png',  # callers pass PNG/JPEG already
                        'data': b64,
                    },
                }
            )
        return {'role': 'user', 'content': blocks}
