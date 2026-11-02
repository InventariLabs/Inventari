"""Jina Reader + LLM fallback scraper.

Fetches any URL via the Jina Reader proxy (``https://r.jina.ai/``) which
converts web pages to clean markdown, then sends the markdown to an LLM to
extract the recipe structure.  This tier works for any page in any language
and is used as a last resort when the other tiers fail.

Two entry points:

* :func:`scrape_with_jina_llm_async` — preferred. Resolves the LLM
  through the Core AI registry (``recipes.text_parse`` purpose).
* :func:`scrape_with_jina_llm` — legacy. Uses the ``llm_cfg`` dict
  shape; new callers MUST use the async variant.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.core.logging import get_logger
from app.core.public_api.llm import (
    LlmContractError,
    LlmProviderRefusalError,
    LlmPurposeUnboundError,
    extract_json,
)

from .._llm_client import call_llm_async
from .base import ScrapedRecipe

log = get_logger(__name__)

_JINA_BASE_URL = 'https://r.jina.ai/'
# Allows long navigation before the recipe while bounding untrusted responses.
_JINA_MAX_BYTES = 1024 * 1024

# A site's menus: six or more lines in a row that are a link and nothing
# else, list marker and indentation allowed, blank lines between them too.
# That is how the reader renders navigation, and on a recipe site it can fill
# the whole prompt bound before the recipe begins — 56,000 characters of it
# on one measured page. A recipe line usually carries more than a link
# ("2 [eggs](…)", "[salt](…) to taste"), and the few that are only one —
# salt, pepper, a herb — come in runs shorter than a menu's.
_BOILERPLATE_RE = re.compile(
    r'(?:^[ \t]*(?:[*+-][ \t]+)?\[[^\]\n]*\]\([^)\n]*\)[ \t]*(?:\n|\Z)(?:[ \t]*\n)*){6,}',
    re.MULTILINE,
)

_RECIPE_EXTRACTION_PROMPT = """\
You are a structured data extractor. Extract the recipe from the following webpage content.

Return a JSON object with exactly these fields:
- "title": recipe name (string) — translate to {target_language} if needed
- "servings": number of servings as a plain integer (e.g. 4), NOT a weight or volume (integer, default 1)
- "prep_time_minutes": total time (prep + cook) in minutes (integer or null)
- "ingredients": array of raw ingredient strings exactly as written on the page (array of strings, keep original language)
- "instructions": cooking instructions formatted in Markdown (string or null) — translate to {target_language} if needed.
  Structure the instructions with:
  * `##` headers for logical sections (e.g. `## Preparation`, `## Cooking`, `## Tips`) where appropriate
  * Numbered lists (`1.`, `2.`, ...) for sequential steps
  * Short paragraphs — never one wall of text
  If the original is already a numbered list, preserve the numbers and add section headers.
- "image_url": absolute URL of the main recipe image if present in the text (string or null)

Webpage content:
{content}

Return ONLY valid JSON. No explanation."""

# Output shape for structured output, matching the field names
# :func:`_build_scraped_recipe` reads back.
_RECIPE_EXTRACTION_SCHEMA: dict[str, Any] = {
    'type': 'object',
    'properties': {
        'title': {'type': 'string'},
        'servings': {'type': 'integer'},
        'prep_time_minutes': {'type': ['integer', 'null']},
        'ingredients': {'type': 'array', 'items': {'type': 'string'}},
        'instructions': {'type': ['string', 'null']},
        'image_url': {'type': ['string', 'null']},
    },
    'required': [
        'title',
        'servings',
        'prep_time_minutes',
        'ingredients',
        'instructions',
        'image_url',
    ],
}


def _fetch_via_jina(url: str, jina_api_key: str | None = None) -> str:
    """Fetch *url* via Jina Reader and return the clean markdown content.

    Raises ``ValueError`` on network errors or empty response.
    """
    jina_url = f'{_JINA_BASE_URL}{url}'
    headers: dict[str, str] = {
        'Accept': 'text/plain',
        'User-Agent': 'Inventari/1.0',
        'X-Return-Format': 'markdown',
        'Accept-Encoding': 'identity',
    }
    if jina_api_key:
        headers['Authorization'] = f'Bearer {jina_api_key}'
    try:
        with httpx.stream(
            'GET',
            jina_url,
            headers=headers,
            timeout=30,
            follow_redirects=False,
        ) as resp:
            resp.raise_for_status()
            if resp.headers.get('content-encoding', 'identity').lower() != 'identity':
                raise ServiceRejectionError('recipe_scrape_encoding_unsupported')
            data = bytearray()
            for chunk in resp.iter_raw(chunk_size=16384):
                data.extend(chunk[: _JINA_MAX_BYTES - len(data)])
                if len(data) >= _JINA_MAX_BYTES:
                    break
            try:
                content = bytes(data).decode(resp.encoding or 'utf-8', errors='replace')
            except LookupError:
                content = bytes(data).decode('utf-8', errors='replace')
    except httpx.HTTPError as exc:
        raise ServiceRejectionError(
            'recipe_scrape_fetch_failed', url=url, error=exc
        ) from exc

    if not content.strip():
        raise ServiceRejectionError('recipe_scrape_empty', url=url)
    return content


# ---------------------------------------------------------------------------
# Keyword sets for heuristic section detection (multilingual)
# ---------------------------------------------------------------------------


async def scrape_with_jina_llm_async(
    db: AsyncSession,
    org_id: UUID,
    url: str,
    *,
    jina_api_key: str | None = None,
    usage_ctx: dict[str, Any] | None = None,
) -> ScrapedRecipe:
    """Async, registry-backed variant of :func:`scrape_with_jina_llm`.

    Steps:
      1. fetch the page via the Jina Reader proxy on a worker thread —
         the client is synchronous, and awaiting it here would stall
         every request the worker is serving for up to its 30 s timeout
      2. resolve the LLM through :func:`app.core.llm.registry`
         (purpose ``recipes.text_parse``)
      3. parse the LLM's JSON into a :class:`ScrapedRecipe`

    Raises ``ValueError`` on any failure (network, LLM error, or no
    ingredients found in the response).
    """
    markdown_content = await asyncio.to_thread(_fetch_via_jina, url, jina_api_key)

    markdown_clean = _BOILERPLATE_RE.sub('\n', markdown_content)
    content_trimmed = markdown_clean[:24000]

    from app.i18n.service import get_current_lang

    from ..ingredient_parser_llm import _LANG_NAMES

    lang_code = str(get_current_lang())
    target_language = _LANG_NAMES.get(lang_code, 'English')
    prompt = _RECIPE_EXTRACTION_PROMPT.format(
        content=content_trimmed, target_language=target_language
    )
    try:
        raw_content = await call_llm_async(
            db,
            org_id,
            prompt,
            usage_ctx=usage_ctx,
            action_type='recipe_import',
            json_schema=_RECIPE_EXTRACTION_SCHEMA,
        )
        data = extract_json(raw_content)
    except (LlmPurposeUnboundError, LlmProviderRefusalError):
        # A configuration answer, not an unusable one — an unbound purpose
        # or a provider refusing the key/budget/model travels on under its
        # own name instead of an "LLM recipe extraction failed" prefix.
        raise
    except (
        httpx.HTTPError,
        json.JSONDecodeError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
    ) as exc:
        log.warning('LLM recipe extraction failed: %s', exc)
        raise ServiceRejectionError('recipe_extraction_failed') from exc

    if not isinstance(data, dict):
        raise LlmContractError(
            f'LLM returned unexpected type {type(data).__name__}, expected dict'
        )

    return _build_scraped_recipe(data)


def _build_scraped_recipe(data: dict[str, Any]) -> ScrapedRecipe:
    """Convert the LLM's JSON dict into a :class:`ScrapedRecipe`."""
    ingredients = data.get('ingredients') or []
    if not isinstance(ingredients, list):
        ingredients = []

    if not ingredients:
        raise ServiceRejectionError('recipe_scrape_no_ingredients')

    servings = 1
    raw_servings = data.get('servings')
    if raw_servings:
        try:
            parsed = max(1, int(raw_servings))
            # Sanity cap: >200 almost certainly means the LLM picked up a weight
            servings = parsed if parsed <= 200 else 1
        except (ValueError, TypeError):
            pass

    prep_time: int | None = None
    raw_pt = data.get('prep_time_minutes')
    if raw_pt:
        try:
            prep_time = int(raw_pt)
        except (ValueError, TypeError):
            pass

    return ScrapedRecipe(
        title=str(data.get('title') or 'Imported recipe').strip(),
        ingredients=[str(i) for i in ingredients],
        instructions=data.get('instructions') or None,
        servings=servings,
        image_url=data.get('image_url') or None,
        prep_time_minutes=prep_time,
        translated=True,  # LLM already translated title + instructions
    )
