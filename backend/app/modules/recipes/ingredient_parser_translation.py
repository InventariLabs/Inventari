"""Recipe metadata translation (title + instructions) via LLM."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx

from app.core.logging import get_logger
from app.core.public_api.llm import extract_json_object

from .ingredient_parser_llm import _LANG_NAMES

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

_METADATA_TRANSLATION_PROMPT = """\
Translate the following recipe metadata into {target_language}.
If the text is already in {target_language}, return it unchanged.

Return a JSON object with EXACTLY these fields:
- "title": translated recipe title (string)
- "instructions": translated cooking instructions, formatted in Markdown (string or null).
  If the input instructions are null or empty, return null.
  Apply the following formatting rules:
  * If the source is already well-structured Markdown (## headers, numbered lists), preserve
    and translate it as-is.
  * If the source is a single block of text or unstructured sentences, reformat it:
    - Split into logical sections and add `##` headers (e.g. `## Preparation`, `## Cooking`).
    - Convert each step into a numbered list item (`1.`, `2.`, ...).
    - Keep steps short and clear — one action per step.
  * Never produce a wall of text. Always use numbered steps.

title: {title}

instructions:
{instructions}

Return ONLY valid JSON. No explanation."""

# Output shape for structured output, matching the two fields the prompt
# describes and the caller reads back.
_METADATA_TRANSLATION_SCHEMA: dict[str, Any] = {
    'type': 'object',
    'properties': {
        'title': {'type': 'string'},
        'instructions': {'type': ['string', 'null']},
    },
    'required': ['title', 'instructions'],
}


async def translate_recipe_metadata_async(
    db: AsyncSession,
    org_id: UUID,
    title: str,
    instructions: str | None,
    usage_ctx: dict[str, Any] | None = None,
) -> tuple[str, str | None]:
    """Async, registry-backed translation of recipe title + instructions.

    routes through :func:`app.core.llm.registry.get_client_for_purpose`
    with the ``recipes.text_parse`` purpose. Falls back to the original
    title/instructions on any LLM error.
    """

    from app.i18n.service import get_current_lang

    from ._llm_client import call_llm_async

    db_session: AsyncSession = db

    lang_code = str(get_current_lang())
    target_language = _LANG_NAMES.get(lang_code, 'English')
    log.info('Translating recipe metadata → target_language=%s', target_language)

    prompt = _METADATA_TRANSLATION_PROMPT.format(
        target_language=target_language,
        title=title,
        instructions=instructions or '',
    )
    try:
        raw = await call_llm_async(
            db_session,
            org_id,
            prompt,
            usage_ctx=usage_ctx,
            action_type='recipe_import',
            json_schema=_METADATA_TRANSLATION_SCHEMA,
        )
        data = extract_json_object(raw)
        translated_title = str(data.get('title') or title).strip() or title
        raw_inst = data.get('instructions')
        translated_instructions = str(raw_inst).strip() if raw_inst else None
        return translated_title, translated_instructions
    except (
        httpx.HTTPError,
        json.JSONDecodeError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
    ) as exc:
        log.warning(
            'translate_recipe_metadata_async failed, keeping originals: %s', exc
        )
        return title, instructions
