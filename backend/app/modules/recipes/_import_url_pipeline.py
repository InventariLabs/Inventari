"""URL scraping pipeline for recipe import (tiered scraper → LLM → template match).

Extracted from ``import_export_service`` to keep file sizes manageable.
Both ``_parse_import_url`` (persist) and ``_preview_import_url`` (dry-run)
share the same scraping/translation/parsing stages.
"""

import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.core.public_api.llm import LlmProviderRefusalError, LlmPurposeUnboundError

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers (used by both parse and preview URL paths)
# ---------------------------------------------------------------------------


async def _find_uom(db: AsyncSession, org_id: UUID, symbol: str | None) -> Any:
    """Return the UOM DTO matching *symbol* exactly, or None."""
    if not symbol:
        return None
    return await core_api.uoms.get_by_symbol_async(db, symbol, org_id)


async def _check_ai_limit(db: AsyncSession, org_id: UUID) -> None:
    """Refuse the import when the organization has spent its monthly AI budget.

    The gate is the core counter's — the same 429-with-numbers the connection
    test and vision answer with — and so is its best-effort shape: an outage
    of the counter itself must not block the import, but a real overage must.
    The recipes-local variant this replaces got both halves wrong: it counted
    one action bucket against a hardcoded 50 instead of the organization's
    ``ai_requests_monthly``, and the "safe" wrapper around it caught the very
    refusal it raised (an ``HTTPException`` is an ``Exception``), logging the
    overage as "non-blocking" and importing anyway.
    """
    await core_api.ai_usage.enforce_limit_async(db, org_id, 'recipe_import')


# ---------------------------------------------------------------------------
# URL import (persist)
# ---------------------------------------------------------------------------


async def _scrape_recipe(
    url: str,
    db: AsyncSession,
    org_id: UUID,
    jina_api_key: str | None,
    usage_ctx: dict[str, Any] | None,
) -> Any:
    """Fetch and structure a recipe from *url* through the tiered scraper.

    A failure of the scraping machinery itself is reported as an invalid
    input. A finished refusal is different: the quota gate's 429 carries its
    numbers, and an unbound AI purpose carries "set it up in Settings" —
    wrapping either in a scrape-failure prefix would glue a second sentence
    onto one that is finished, so they travel on under their own name.
    """
    from .scrapers.base import ScrapedRecipe
    from .scrapers.jina_llm import scrape_with_jina_llm_async

    try:
        scraped: ScrapedRecipe = await scrape_with_jina_llm_async(
            db,
            org_id,
            url,
            jina_api_key=jina_api_key,
            usage_ctx=usage_ctx,
        )
    except (HTTPException, LlmPurposeUnboundError, LlmProviderRefusalError):
        # An answer that is finished: the quota refusal carries its numbers,
        # the unbound purpose its "set it up in Settings". Only a broken
        # scrape becomes a scrape failure — gluing a prefix onto a finished
        # sentence was how a 429 used to leave here as a 400.
        raise
    except Exception as exc:  # any scraper failure is a scrape failure
        # The exception's text is English and for operators (a provider's
        # answer, an HTTP library's message): it goes to the log, not into
        # the reader's sentence.
        log.warning('Recipe scrape failed: %s', exc)
        raise ServiceRejectionError('recipe_scrape_failed') from exc
    return scraped


async def _parse_import_url(
    url: str,
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    organization_settings: dict[str, Any] | None = None,
) -> Any:
    """Scrape a recipe from *url* using the tiered scraper pipeline.

    Raises ``ValueError`` on scraping failure or invalid URL.
    Returns a ``RecipeCreate`` schema.

    The LLM is resolved from the ``recipes.text_parse`` purpose binding.
    """
    from .schemas import RecipeIngredientCreate

    if not re.match(r'^https?://', url):
        raise ServiceRejectionError('invalid_url_scheme')

    from app.core.module_settings import resolve_jina_api_key_async

    # Refuse before the external fetch: an organization out of budget must
    # not spend a Jina request on the way to its answer. The gate is
    # attempted unconditionally — the counter is the authority, not the
    # presence of a binding (``call_llm_async`` re-checks it per call).
    await _check_ai_limit(db, org_id)

    jina_api_key = await resolve_jina_api_key_async(db, org_id)

    usage_ctx: dict[str, Any] | None = {
        'db': db,
        'user_id': user_id,
        'organization_id': org_id,
    }

    scraped = await _scrape_recipe(url, db, org_id, jina_api_key, usage_ctx)

    from .ingredient_parser_llm import parse_ingredients_llm_async
    from .ingredient_parser_translation import translate_recipe_metadata_async
    from .template_matcher import match_templates

    scraped_title = scraped.title
    scraped_instructions = scraped.instructions
    if not scraped.translated:
        from app.i18n.service import get_current_lang

        ui_lang = str(get_current_lang())
        source_lang = scraped.source_language
        needs_translation = source_lang is None or source_lang != ui_lang
        if needs_translation:
            log.info(
                'Translating recipe metadata: source_lang=%r ui_lang=%r',
                source_lang,
                ui_lang,
            )
            scraped_title, scraped_instructions = await translate_recipe_metadata_async(
                db,
                org_id,
                scraped.title,
                scraped.instructions,
                usage_ctx=usage_ctx,
            )
        else:
            log.info(
                'Skipping translation: source_lang=%r matches ui_lang=%r',
                source_lang,
                ui_lang,
            )

    from app.i18n.service import get_current_lang

    from .unit_conversion_service import list_conversions, render_conversion_table

    ui_lang = str(get_current_lang())
    conversions = await list_conversions(db, org_id, lang=ui_lang)
    conversion_table = render_conversion_table(conversions)

    parsed_list = await parse_ingredients_llm_async(
        db,
        org_id,
        scraped.ingredients,
        usage_ctx=usage_ctx,
        conversion_table=conversion_table,
    )

    template_matches: dict[int, UUID | None] = {}
    if parsed_list:
        group_names = [p.group_name or p.name for p in parsed_list]
        match_results = await match_templates(
            db, org_id, group_names, usage_ctx=usage_ctx
        )
        template_matches = {r.ingredient_index: r.template_id for r in match_results}

    ingredients = [
        RecipeIngredientCreate(
            name=parsed.name,
            ingredient_group_name=parsed.group_name or parsed.name,
            template_id=template_matches.get(idx),
            quantity=parsed.quantity,
            uom_id=(await _find_uom(db, org_id, parsed.unit_symbol)).id
            if (await _find_uom(db, org_id, parsed.unit_symbol))
            else None,
            is_optional=False,
            sort_order=idx,
        )
        for idx, parsed in enumerate(parsed_list)
    ]

    from .schemas import RecipeCreate

    return RecipeCreate(
        name=scraped_title,
        instructions=scraped_instructions,
        servings=scraped.servings,
        image_source_url=scraped.image_url,
        source_url=url,
        prep_time_minutes=scraped.prep_time_minutes,
        ingredients=ingredients,
    )


# ---------------------------------------------------------------------------
# URL import preview (dry-run, no persist)
# ---------------------------------------------------------------------------


async def _preview_import_url(
    url: str,
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    organization_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Scrape + parse URL and return preview data without persisting."""
    if not re.match(r'^https?://', url):
        raise ServiceRejectionError('invalid_url_scheme')

    from app.core.module_settings import resolve_jina_api_key_async

    from .schemas import PreviewIngredient

    await _check_ai_limit(db, org_id)

    jina_api_key = await resolve_jina_api_key_async(db, org_id)

    usage_ctx: dict[str, Any] | None = {
        'db': db,
        'user_id': user_id,
        'organization_id': org_id,
    }

    scraped = await _scrape_recipe(url, db, org_id, jina_api_key, usage_ctx)

    from .ingredient_parser_llm import parse_ingredients_llm_with_status_async
    from .ingredient_parser_translation import translate_recipe_metadata_async
    from .template_matcher import match_templates

    scraped_title = scraped.title
    scraped_instructions = scraped.instructions
    if not scraped.translated:
        from app.i18n.service import get_current_lang

        ui_lang = str(get_current_lang())
        source_lang = scraped.source_language
        needs_translation = source_lang is None or source_lang != ui_lang
        if needs_translation:
            log.info(
                'Translating recipe metadata: source_lang=%r ui_lang=%r',
                source_lang,
                ui_lang,
            )
            scraped_title, scraped_instructions = await translate_recipe_metadata_async(
                db,
                org_id,
                scraped.title,
                scraped.instructions,
                usage_ctx=usage_ctx,
            )
        else:
            log.info(
                'Skipping translation: source_lang=%r matches ui_lang=%r',
                source_lang,
                ui_lang,
            )

    from app.i18n.service import get_current_lang

    from .unit_conversion_service import list_conversions, render_conversion_table

    ui_lang = str(get_current_lang())
    conversions = await list_conversions(db, org_id, lang=ui_lang)
    conversion_table = render_conversion_table(conversions)

    parse_outcome = await parse_ingredients_llm_with_status_async(
        db,
        org_id,
        scraped.ingredients,
        usage_ctx=usage_ctx,
        conversion_table=conversion_table,
    )
    parsed_list = parse_outcome.items

    template_matches: dict[int, UUID | None] = {}
    template_names: dict[int, str | None] = {}
    if parsed_list:
        from app.core.public_api import core_api

        group_names = [p.group_name or p.name for p in parsed_list]
        match_results = await match_templates(
            db, org_id, group_names, usage_ctx=usage_ctx
        )
        template_matches = {r.ingredient_index: r.template_id for r in match_results}
        templates = (
            await core_api.product_templates.list_for_org_with_recipe_usage_async(
                db, org_id
            )
        )
        id_to_name: dict[UUID, str] = {t.id: t.name for t in templates}
        template_names = {
            idx: id_to_name.get(tid) if tid else None
            for idx, tid in template_matches.items()
        }

    preview_ingredients: list[dict[str, Any]] = []
    for idx, parsed in enumerate(parsed_list):
        uom = await _find_uom(db, org_id, parsed.unit_symbol)
        preview_ingredients.append(
            PreviewIngredient(
                name=parsed.name,
                quantity=float(parsed.quantity),
                uom_symbol=parsed.unit_symbol,
                uom_id=str(uom.id) if uom else None,
                original_text=parsed.original_text,
                group_name=parsed.group_name,
                template_id=str(template_matches[idx])
                if template_matches.get(idx)
                else None,
                template_name=template_names.get(idx),
                is_optional=False,
                original_quantity=float(parsed.original_quantity)
                if parsed.original_quantity is not None
                else None,
                original_unit_text=parsed.original_unit_text,
                unit_display=parsed.unit_display,
            ).model_dump()
        )

    return {
        'name': scraped_title,
        'description': None,
        'instructions': scraped_instructions,
        'servings': scraped.servings,
        'prep_time_minutes': scraped.prep_time_minutes,
        'image_source_url': scraped.image_url,
        'source_url': url,
        'tags': [],
        'ingredients': preview_ingredients,
        'parse_warning': 'llm_fallback' if parse_outcome.used_fallback else None,
    }
