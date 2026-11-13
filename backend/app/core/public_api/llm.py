"""Module-safe access to the LLM client registry.

Modules must NOT import ``app.core.llm.*`` directly — they go through this
facade. ``LlmRequest`` / ``LlmResponse`` / ``LlmCapability`` are re-exported
here so module code can build requests without touching Core internals.
The same goes for the JSON parsing helpers: every call site that reads a
model's answer uses ``extract_json`` from here rather than its own
``json.loads`` — that is how a fenced or truncated response stops being a
per-module surprise.

Resolution: ``get_client_for_purpose_async`` binds a purpose key (e.g.
``recipes.text_parse``) to the org's configured AI connection
(core-owned default or module-owned slot), with tenant guard and
capability check. Returns ``None`` when no connection is bound.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm.base import LlmClient, LlmRequest, LlmResponse
from app.core.llm.diagnostics import TRUNCATED_REASONS
from app.core.llm.enums import LlmCapability
from app.core.llm.errors import (
    LlmContractError,
    LlmEmptyAnswerError,
    LlmProviderRefusalError,
    LlmPurposeUnboundError,
    LlmTimeoutError,
    LlmTransportError,
    classify_provider_refusal,
)
from app.core.llm.json_parsing import (
    extract_json,
    extract_json_object,
    repair_json_strings,
    strip_markdown_fence,
)
from app.core.llm.json_retry import complete_json, default_retry_prompt
from app.core.llm.purpose_registry import AiContractProbe
from app.core.llm.structured_extraction import (
    build_shape_prompt,
    describe_validation_error,
    parse_into,
    read_json,
    unwrap_object,
)
from app.core.public_api._access import reads, writes

__all__ = [
    'TRUNCATED_REASONS',
    'AiContractProbe',
    'CoreLlmAPI',
    'LlmCapability',
    'LlmContractError',
    'LlmClient',
    'LlmEmptyAnswerError',
    'LlmProviderRefusalError',
    'LlmPurposeUnboundError',
    'LlmTimeoutError',
    'LlmTransportError',
    'classify_provider_refusal',
    'LlmRequest',
    'LlmResponse',
    'build_shape_prompt',
    'complete_json',
    'default_retry_prompt',
    'describe_validation_error',
    'extract_json',
    'extract_json_object',
    'parse_into',
    'read_json',
    'repair_json_strings',
    'strip_markdown_fence',
    'unwrap_object',
]


class CoreLlmAPI:
    """Public Core API for LLM purposes and client resolution."""

    @reads
    def register_purpose(
        self,
        key: str,
        capability: LlmCapability,
        label_key: str,
        description_key: str,
        owner_module: str,
        probe: AiContractProbe | None = None,
    ) -> None:
        """Register an AI purpose (idempotent; conflict raises ValueError).

        Convention: ``key`` is ``<module>.<purpose>`` (e.g.
        ``recipes.text_parse``); bindings live per purpose key under
        ``settings.ai.defaults[<key>]``, and ``owner_module`` is the
        attribution for the settings screen — the module a purpose belongs
        to, and whose legacy binding slot
        (``settings.modules.<owner_module>.ai_default_connection_id``)
        still reads as a fallback for choices made before per-purpose
        slots.

        Pass a ``probe`` to let the connection test check that a model can
        actually serve this purpose. Without one the test can only report
        that the credentials work.
        """
        from app.core.llm.purpose_registry import AiPurposeSpec, register_ai_purpose

        register_ai_purpose(
            AiPurposeSpec(
                key=key,
                capability=capability,
                label_key=label_key,
                description_key=description_key,
                owner_module=owner_module,
                probe=probe,
            )
        )

    @reads
    async def get_client_for_purpose_async(
        self, db: AsyncSession, organization_id: UUID, purpose_key: str
    ) -> LlmClient | None:
        """Resolve the LLM client bound to *purpose_key* for the organization.

        Returns ``None`` when no connection is bound (caller decides the
        fallback — graceful degradation is the module's responsibility).
        """
        from app.core.llm.registry import get_client_for_purpose

        return await get_client_for_purpose(db, organization_id, purpose_key)

    @reads
    async def connection_for_purpose_async(
        self, db: AsyncSession, organization_id: UUID, purpose_key: str
    ) -> Any | None:
        """Resolve the bound connection **row** for *purpose_key*.

        For a purpose whose consumer reads a credential instead of
        completing a request — the recipes page reader: the row carries the
        encrypted key and the verdict-checked identity. ``None`` when
        nothing serves, and the caller decides what that means (the
        reader's free tier); graceful degradation stays the module's
        responsibility, same as the client door above.
        """
        from app.core.llm.registry import get_connection_for_purpose

        return await get_connection_for_purpose(db, organization_id, purpose_key)

    @writes
    async def extract_from_images_async[T: BaseModel](
        self,
        db: AsyncSession,
        organization_id: UUID,
        *,
        purpose_key: str,
        schema: type[T],
        instructions: str,
        images: Sequence[bytes],
        action_type: str,
        user_id: UUID | str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 8000,
        disable_reasoning: bool = True,
    ) -> T:
        """Read *schema* out of *images*, and account for what it cost.

        The Core half of image recognition: quota, connection, prompt shape,
        one retry when the answer does not fit, one usage row per attempt.
        The domain half — what is worth looking for on this picture — is the
        caller\'s, and arrives entirely as *instructions* and *schema*.

        Three verticals, one code path. A food module asks for a model with
        ``expiry_date`` and describes where a best-before date hides on a
        carton; an equipment module asks for ``serial_number`` and describes a
        rating plate; a library module asks for ``isbn`` and describes a
        copyright page. None of those words occur below this docstring, and
        adding a fourth vertical changes nothing in Core.

        Args:
            purpose_key: The registered AI purpose whose bound connection
                serves this call (e.g. ``vision.extract``).
            schema: The shape asked for. Field descriptions travel into the
                prompt, so that is where the domain vocabulary belongs.
            instructions: What the picture is and what matters on it.
            action_type: The quota bucket this call is billed to.
            disable_reasoning: Ask the provider to skip the chain of thought.
                True is the default because the budget was once spent on
                thinking and the answer never arrived — see the comment on
                *max_tokens* below. It is a parameter rather than a constant
                because that value was chosen from a single observation on a
                single model, and reading a label is not purely transcription:
                deciding whether "21,5 g" on a wrapper is a net weight or a
                per-serving figure is a judgement, and judgement is what a
                chain of thought is for. Making it settable is what allows
                the default to be measured rather than assumed.

        Raises:
            LlmPurposeUnboundError: nothing is bound to *purpose_key*.
            LlmEmptyAnswerError: the model answered with nothing, once.
            LlmContractError: the model answered, unusably, twice.
            LlmTransportError: the provider was never reached, or —
                as ``LlmTimeoutError`` — was reached and did not answer in
                the time its provider is allowed.
        """
        from app.core.public_api import core_api

        await _check_ai_quota(db, organization_id, action_type)

        client = await self.get_client_for_purpose_async(
            db, organization_id, purpose_key
        )
        if client is None:
            raise LlmPurposeUnboundError(purpose_key)

        request = LlmRequest(
            prompt=f'{instructions}\n\n{build_shape_prompt(schema)}',
            images=list(images),
            json_schema=schema.model_json_schema(),
            # Low temperature for faithful reading rather than "creative"
            # rewriting of what is printed.
            temperature=temperature,
            # Two photographs, a schema several modules contributed to, and
            # instructions assembled from all of them. The old 2000 was a
            # text-sized budget on an image-sized task, and on a reasoning
            # model it was spent before the answer began: chain-of-thought is
            # billed as completion, the unclosed block is stripped, and what
            # arrives is the empty string.
            max_tokens=max_tokens,
            disable_reasoning=disable_reasoning,
        )

        async def log(response: LlmResponse) -> None:
            await core_api.ai_usage.log_llm_usage_async(
                db=db,
                user_id=user_id,
                organization_id=organization_id,
                response=response,
                action_type=action_type,
                client=client,
            )

        try:
            result, _ = await complete_json(
                client,
                request,
                validate=lambda content: parse_into(schema, content),
                on_response=log,
            )
        except LlmContractError as exc:
            # Name the connection and model that answered, so a router can tell
            # the photographer *which* AI connection to go look at in Settings —
            # not just that the answer was unusable. Leave the attributes alone
            # when the client does not carry them (structural test doubles, the
            # legacy env-var fallback).
            if exc.connection_name is None and client.connection_name:
                exc.connection_name = client.connection_name
            if exc.model_name is None and client.model_name:
                exc.model_name = client.model_name
            raise
        return result


async def _check_ai_quota(
    db: AsyncSession, organization_id: UUID, action_type: str
) -> None:
    """Best-effort quota gate: over limit blocks, an outage does not.

    The refusal itself belongs to the counter — it measured the numbers, so it
    answers with them (``core_api.ai_usage.enforce_limit_async``), including an
    outage of the counter never taking the feature down with it.
    """
    from app.core.public_api import core_api

    await core_api.ai_usage.enforce_limit_async(db, organization_id, action_type)
