"""Google Gemini LLM client — full implementation.

Native Gemini SDK adapter (``google.genai``). Replaced the deprecated
``google.generativeai`` package, which Google end-of-lifed: it stopped
receiving fixes and its ``GenerationConfig`` never grew a
``thinking_config`` field, so ``disable_reasoning`` was a silent no-op on
this one provider while every other client honored it — and a reasoning
model under a fixed token budget spent the budget on thought tokens and
answered with an empty string.

Notable differences from the OpenAI-compatible client:

- SDK, not HTTP. A ``genai.Client`` is built per call from the
  connection's decrypted key, so the key rotation that comes with
  replacing an ``AiConnection`` row behaves as expected.
- Model name: OpenRouter exposes Google models as ``google/<model>``.
  The native SDK rejects the prefix, so we strip it once.
- Multimodal: in-process ``PIL.Image.Image`` objects, NOT base64 data
  URIs. Slightly different shape than ``OpenAiCompatibleClient``.
- Generation config maps one-to-one onto ``GenerateContentConfig``;
  structured output is ``response_mime_type='application/json'`` — the
  SDK's analog of OpenAI's ``response_format``.
- ``disable_reasoning`` becomes ``thinking_config`` with a zero budget.
  The flash family honors it; Gemini Pro ignores a zero budget (its
  floor is 128) and keeps thinking — callers sizing ``max_tokens``
  still owe it reasoning headroom there.

Lazy import: the SDK is imported inside ``complete()`` so that
loading this module does not require ``google-genai`` to be
installed. OpenRouter-only deployments don't need it; the import
would cost cold-start time for no benefit.
"""

from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING, Any

from app.core.db_retry import mark_external_effect
from app.core.llm.base import LlmClient, LlmRequest, LlmResponse
from app.core.llm.diagnostics import log_answer
from app.core.llm.errors import classify_provider_refusal, provider_refusal
from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.models.ai_connection import AiConnection

logger = get_logger(__name__)


def _finish_reason_of(response: Any) -> str | None:
    """The SDK's reason for stopping, as its own word.

    Buried on the first candidate and typed as an enum, so it is read
    defensively: a response without candidates is exactly the case this is
    meant to explain, and must not turn into an ``IndexError`` on the way to
    saying so.
    """
    candidates = getattr(response, 'candidates', None) or []
    if not candidates:
        return None
    reason = getattr(candidates[0], 'finish_reason', None)
    if reason is None:
        return None
    return str(getattr(reason, 'name', reason))


class GoogleClient(LlmClient):
    """Google Gemini LLM client backed by the native SDK."""

    def __init__(self, connection: AiConnection) -> None:
        self._conn = connection

    @property
    def connection_name(self) -> str | None:
        return self._conn.name

    @property
    def model_name(self) -> str | None:
        return self._conn.model_name

    @property
    def connection_provider(self) -> str | None:
        return getattr(self._conn, 'provider', None)

    async def complete(self, request: LlmRequest) -> LlmResponse:
        # A provider call is billed and answered once; a request whose
        # transaction later deadlocks must not repeat it (db_retry).
        mark_external_effect('llm:complete')
        # Lazy import — see module docstring.
        from google import genai
        from google.genai import types
        from PIL import Image as PILImage

        from app.core.llm.secrets import decrypt_connection_secret

        api_key = decrypt_connection_secret(self._conn.api_key_enc)
        if not api_key:
            raise RuntimeError(
                'Google connection has no api_key_enc set; cannot call SDK'
            )

        # A client per call: the key rotation that comes with replacing an
        # AiConnection row behaves as expected.
        client = genai.Client(api_key=api_key)

        # Strip the 'google/' prefix that OpenRouter-style model names carry.
        # The native SDK rejects 'google/google/gemini-...'.
        clean_model = self._conn.model_name.replace('google/', '', 1)

        # Compose content parts. The SDK accepts a list of mixed
        # ``str | PIL.Image.Image | ...`` and infers roles from order.
        parts: list[Any] = []
        if request.system_prompt:
            parts.append(request.system_prompt)
        parts.append(request.prompt)
        if request.images:
            for image_bytes in request.images:
                img = PILImage.open(io.BytesIO(image_bytes))
                # PIL keeps an open file handle on the image; close
                # explicitly so we don't leak fds across many calls.
                parts.append(img)
                img.close()

        gen_config = self._build_gen_config(request, types)

        response = await self._generate_content(client, clean_model, parts, gen_config)

        # Adapt the SDK response to LlmResponse.
        usage_metadata = getattr(response, 'usage_metadata', None)
        usage: dict[str, int] = {}
        if usage_metadata is not None:
            pt = getattr(usage_metadata, 'prompt_token_count', None)
            ct = getattr(usage_metadata, 'candidates_token_count', None)
            tt = getattr(usage_metadata, 'total_token_count', None)
            if pt is not None:
                usage['prompt_tokens'] = pt
            if ct is not None:
                usage['completion_tokens'] = ct
            if tt is not None:
                usage['total_tokens'] = tt

        # The SDK keeps it on the candidate, as an enum whose name is the
        # provider's word (``MAX_TOKENS``, ``STOP``, ``SAFETY``).
        finish_reason = _finish_reason_of(response)
        content = getattr(response, 'text', '') or ''
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
            raw=response,
            finish_reason=finish_reason,
        )

    def _build_gen_config(self, request: LlmRequest, types: Any) -> dict[str, Any]:
        """Generation config: per-call override wins, fall back to the
        connection row. response_mime_type only when json_schema is set."""
        gen_config: dict[str, Any] = {}
        if request.temperature is not None:
            gen_config['temperature'] = request.temperature
        elif self._conn.temperature is not None:
            gen_config['temperature'] = self._conn.temperature

        if request.max_tokens is not None:
            gen_config['max_output_tokens'] = request.max_tokens
        elif self._conn.max_tokens is not None:
            gen_config['max_output_tokens'] = self._conn.max_tokens

        if self._conn.top_p is not None:
            gen_config['top_p'] = self._conn.top_p

        if request.json_schema:
            gen_config['response_mime_type'] = 'application/json'
            gen_config['response_schema'] = request.json_schema

        if request.disable_reasoning:
            # The flash family honors a zero thinking budget: the chain of
            # thought is off and the token budget lands in content instead
            # of thoughts.
            gen_config['thinking_config'] = types.ThinkingConfig(thinking_budget=0)

        return gen_config

    async def _generate_content(
        self,
        client: Any,
        model_name: str,
        parts: list[Any],
        gen_config: dict[str, Any],
    ) -> Any:
        """Call the SDK once, degrading ``response_schema`` on schema rejection.

        Gemini accepts only an OpenAPI subset of JSON Schema. When the SDK
        rejects our schema, the retry keeps ``response_mime_type`` only, and
        the caller's parser + retry (Slices 1/3) remains the safety net.
        """
        try:
            return await client.aio.models.generate_content(
                model=model_name,
                contents=parts,
                config=gen_config,
            )
        except (TypeError, ValueError) as exc:
            if 'response_schema' not in gen_config:
                raise
            logger.warning(
                'Gemini rejected response_schema (%s); retrying with '
                'response_mime_type only',
                exc,
            )
            gen_config.pop('response_schema', None)
            try:
                return await client.aio.models.generate_content(
                    model=model_name,
                    contents=parts,
                    config=gen_config,
                )
            except Exception as retry_exc:  # a refusal is translated, else re-raised
                refused = self._refusal(retry_exc, 'Gemini API')
                if refused is not None:
                    raise refused from retry_exc
                raise
        except Exception as exc:  # a refusal is translated, else re-raised
            refused = self._refusal(exc, 'Gemini API')
            if refused is not None:
                raise refused from exc
            raise

    def _refusal(self, exc: Exception, what: str) -> RuntimeError | None:
        """Translate a classified SDK refusal into the named failure.

        The SDK raises its own types; the classification only needs their
        HTTP code, read defensively. Anything without a classified code
        returns ``None`` so the caller re-raises the original exception
        untouched.
        """
        code = getattr(exc, 'code', None)
        if isinstance(code, int) and classify_provider_refusal(code) is not None:
            return provider_refusal(
                code,
                str(exc),
                what=what,
                connection_name=self.connection_name,
                model_name=self.model_name,
            )
        return None

    async def list_models(self) -> list[str]:
        """List available Gemini models via the native SDK.

        Strips the ``models/`` prefix the SDK prepends, returning bare
        model names like ``gemini-2.0-flash``.
        """
        mark_external_effect('llm:list-models')
        from google import genai

        from app.core.llm.secrets import decrypt_connection_secret

        api_key = decrypt_connection_secret(self._conn.api_key_enc)
        if not api_key:
            raise RuntimeError('Google connection has no api_key_enc set')

        client = genai.Client(api_key=api_key)

        models: list[str] = []
        # client.models.list() returns a synchronous Iterable; wrap in
        # to_thread so the async contract holds without blocking the loop.
        try:
            listed = await asyncio.to_thread(lambda: list(client.models.list()))
        except Exception as exc:  # a refusal is translated, else re-raised
            refused = self._refusal(exc, 'Gemini list_models')
            if refused is not None:
                raise refused from exc
            raise
        for m in listed:
            name = getattr(m, 'name', '') or ''
            # SDK returns 'models/gemini-1.5-flash' — strip the prefix.
            if name.startswith('models/'):
                name = name[len('models/') :]
            if name:
                models.append(name)
        return models
