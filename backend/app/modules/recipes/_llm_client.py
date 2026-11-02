"""Async LLM client helper for the recipes module.

Single entry point for all recipes-module LLM calls. Checks the
organization's monthly AI budget, resolves the client through
:func:`app.core.llm.registry.get_client_for_purpose`
(``recipes.text_parse`` purpose), dispatches the prompt, and logs
AI usage — the budget gate and the logging both best-effort.

Legacy code (the old ``ingredient_parser_llm._call_llm_sync`` and
``scrapers.jina_llm._call_google_direct_sync``) used a ``llm_cfg``
dict passed down from ``_import_url_pipeline``. Since the move to the registry the
``llm_cfg`` parameter is gone from the call sites — the bound
``AiConnection`` is the source of truth.

Why a recipes-local helper instead of calling the registry directly
from each consumer? Three reasons:

1. **Logging is centralised.** AI usage + cost estimation is done
   here, so each call site only writes the prompt and parses the
   response.
2. **Prompt-vs-payload split is enforced.** The helper takes a plain
   ``str`` prompt; image-bearing recipes (none today, but possible
   in the future) would extend it to ``LlmRequest`` directly.
3. **The legacy ``llm_cfg`` path stays testable.** Unit tests for
   :func:`app.modules.recipes.ingredient_parser.parse_ingredients_llm`
   still inject a synthetic ``llm_cfg`` to exercise the JSON-parsing
   branches without spinning up the registry.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.public_api import core_api
from app.core.public_api.llm import (
    TRUNCATED_REASONS,
    LlmPurposeUnboundError,
    LlmRequest,
)

logger = get_logger(__name__)


_RECIPES_PURPOSE = 'recipes.text_parse'


def build_text_request(
    prompt: str, *, json_schema: dict[str, Any] | None = None
) -> LlmRequest:
    """The request every recipes text call sends, prompt aside.

    The connection test's probe (:mod:`._probe`) builds its request here
    too, so it tests the call the import makes and not a lookalike.
    """
    # Per-call sampling params — hardcoded for recipe text parsing
    # (structured JSON output from a recipe page). Slightly higher
    # temperature than vision because recipe text is ambiguous ("szklanka"
    # = 200 or 250 ml, brand names get misspelled), but still well below
    # the provider default of 1.0 which would let the model "creatively"
    # alter ingredient names and quantities. max_tokens sized for a long
    # recipe (30+ ingredients ≈ 3–4k JSON tokens) with headroom.
    # ``disable_reasoning`` keeps reasoning models (MiniMax-M3, …) from
    # burning the whole budget on chain-of-thought and returning empty
    # content — reasoning tokens count towards completion_tokens.
    # These override any connection-level defaults because the form no
    # longer surfaces those fields — leaving them to the provider default
    # would mean temperature=1.0, which is too hot for precise parsing.
    return LlmRequest(
        prompt=prompt,
        temperature=0.4,
        max_tokens=8000,
        disable_reasoning=True,
        json_schema=json_schema,
    )


async def call_llm_async(
    db: AsyncSession,
    org_id: UUID,
    prompt: str,
    usage_ctx: dict[str, Any] | None = None,
    *,
    action_type: str = 'recipe_import',
    json_schema: dict[str, Any] | None = None,
) -> str:
    """Resolve the bound ``recipes.text_parse`` client and return the
    provider's text response.

    Args:
        db: Async SQLAlchemy session (must belong to ``org_id``).
        org_id: Organization id used to look up the bound connection.
        prompt: Full user prompt to send to the model.
        usage_ctx: Optional dict with ``user_id`` and ``organization_id``
            keys for AI usage logging. Must match ``org_id`` if provided.
        action_type: Value to record in the AI-usage log row.
        json_schema: Optional output shape to request from the provider via
            structured output. ``None`` keeps the existing prompt-only
            behaviour; providers that cannot honour it degrade gracefully.

    Returns:
        The raw ``content`` string from the LLM. JSON / markdown-fence
        cleanup is the caller's responsibility.

    Raises:
        HTTPException: 429 when the organization has spent its monthly AI
            budget. The refusal is the counter's, with its numbers and
            period; a counter outage is swallowed by the same best-effort
            gate and does not block the call.
        LlmPurposeUnboundError: if no client is bound for
            ``recipes.text_parse`` in this organization — a configuration
            gap, named so routers can answer "set it up in Settings"
            instead of reporting an internal error.
        RuntimeError: if the provider returned an error.
    """
    # Every recipes provider call is billed against the organization's
    # monthly ceiling (the ledger row below is that spend), so the ceiling
    # gates the call first. The gate is the core one — best-effort: a real
    # overage refuses with what the counter measured, an outage of the
    # counter itself does not take importing down with it.
    await core_api.ai_usage.enforce_limit_async(db, org_id, action_type)

    client = await core_api.llm.get_client_for_purpose_async(
        db, org_id, _RECIPES_PURPOSE
    )
    if client is None:
        # Typed, with the purpose key as data: the router maps this to a
        # "configure it" answer instead of a wrapped internal sentence that
        # echoes the raw key back at the reader.
        raise LlmPurposeUnboundError(_RECIPES_PURPOSE)

    request = build_text_request(prompt, json_schema=json_schema)
    response = await client.complete(request)

    # What went wrong with the answer is logged by the client, for every
    # caller and in one place (``app.core.llm.diagnostics``). What is left to
    # say here is the part only this module knows: what happens next.
    if not response.content.strip() or response.finish_reason in TRUNCATED_REASONS:
        logger.warning(
            'Recipe parsing falls back to the basic parser: the model answered with %s',
            'nothing' if not response.content.strip() else 'a truncated answer',
        )

    await core_api.ai_usage.log_llm_usage_async(
        db=db,
        user_id=usage_ctx.get('user_id') if usage_ctx else None,
        organization_id=org_id,
        response=response,
        action_type=action_type,
        client=client,
    )
    return response.content
