"""Global (all-recipes) linking of ingredients to product templates.

The recipe detail page links one ingredient at a time. This service backs the
screen that does it in bulk: it lists every ingredient the whole recipe book
still cannot map (``template_id IS NULL``), asks the LLM matcher for
proposals across all of them, and applies the approved subset in one write.

Availability, cost and picking only work for linked ingredients, so this is
what turns those screens from theoretical into useful for a recipe book
imported before the catalogue existed.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.core.public_api import core_api
from app.core.public_api.llm import LlmPurposeUnboundError
from app.i18n.service import get_current_lang

from ._schemas_linking import (
    BulkLinkIngredientsRequest,
    IngredientMatchProposal,
    IngredientTemplateLink,
    UnlinkedIngredient,
)
from .models import Recipe, RecipeIngredient
from .template_matcher import match_identical_names_async, match_templates

#: Distinct ingredient names one LLM call may carry. A backlog larger than
#: this is matched in further calls rather than one oversized prompt — the
#: catalogue side of the prompt is capped at 200 products already.
_MATCH_BATCH_SIZE = 100


async def list_unlinked_ingredients(
    db: AsyncSession, org_id: UUID
) -> list[UnlinkedIngredient]:
    """Every unlinked ingredient across the organization's recipes.

    Ordered by recipe name and the recipe's own ingredient order, so two
    calls return the same rows in the same order.
    """
    rows = (
        await db.execute(
            select(RecipeIngredient, Recipe.name)
            .join(Recipe, Recipe.id == RecipeIngredient.recipe_id)
            .where(
                Recipe.organization_id == org_id,
                RecipeIngredient.template_id.is_(None),
            )
            .order_by(
                Recipe.name,
                RecipeIngredient.sort_order,
                RecipeIngredient.id,
            )
        )
    ).all()
    return [
        UnlinkedIngredient(
            id=ingredient.id,
            recipe_id=ingredient.recipe_id,
            recipe_name=recipe_name,
            name=ingredient.name,
            match_name=(ingredient.ingredient_group_name or ingredient.name),
            quantity=ingredient.quantity,
            uom_symbol=ingredient.uom.symbol if ingredient.uom else None,
        )
        for ingredient, recipe_name in rows
    ]


async def count_ingredients(db: AsyncSession, org_id: UUID) -> int:
    """Every ingredient across the organization's recipes, linked or not."""
    return (
        await db.scalar(
            select(func.count())
            .select_from(RecipeIngredient)
            .join(Recipe, Recipe.id == RecipeIngredient.recipe_id)
            .where(Recipe.organization_id == org_id)
        )
        or 0
    )


async def suggest_matches(
    db: AsyncSession,
    org_id: UUID,
    usage_ctx: dict[str, Any] | None = None,
) -> tuple[list[IngredientMatchProposal], int]:
    """Match every unlinked ingredient to a product, without writing.

    Returns ``(proposals, considered)``. Identical names are matched once
    and the answer fans out to every row carrying the name — five recipes
    asking for "onion" cost one entry in the prompt. A name the model could
    not match has no proposal; a failed LLM call yields no proposals at all
    (the matcher's own graceful degradation).
    """
    unlinked = await list_unlinked_ingredients(db, org_id)
    if not unlinked:
        return [], 0

    names: list[str] = []
    seen: set[str] = set()
    for item in unlinked:
        key = item.match_name.strip()
        if key and key not in seen:
            seen.add(key)
            names.append(key)

    # A name that is a product's own name needs no model: matched first, and
    # with no AI connection at all. Only the rest are put to the matcher.
    template_id_by_name: dict[str, UUID] = {
        name: product.id
        for name, product in (
            await match_identical_names_async(db, org_id, names)
        ).items()
    }
    rest = [name for name in names if name not in template_id_by_name]
    try:
        for start in range(0, len(rest), _MATCH_BATCH_SIZE):
            batch = rest[start : start + _MATCH_BATCH_SIZE]
            results = await match_templates(db, org_id, batch, usage_ctx=usage_ctx)
            for result in results:
                if result.template_id is not None:
                    template_id_by_name[batch[result.ingredient_index]] = (
                        result.template_id
                    )
    except LlmPurposeUnboundError:
        # No AI connection: the identical names still stand as proposals.
        # With none of those either, the screen says to set one up.
        if not template_id_by_name:
            raise

    if not template_id_by_name:
        return [], len(unlinked)

    templates = await core_api.product_templates.get_many_async(
        db, org_id, list(set(template_id_by_name.values()))
    )
    proposals: list[IngredientMatchProposal] = []
    for item in unlinked:
        template_id = template_id_by_name.get(item.match_name.strip())
        template = templates.get(template_id) if template_id else None
        if template is None:
            continue
        proposals.append(
            IngredientMatchProposal(
                ingredient_id=item.id,
                template_id=template.id,
                template_name=template.name,
            )
        )
    return proposals, len(unlinked)


async def apply_links(
    db: AsyncSession, org_id: UUID, request: BulkLinkIngredientsRequest
) -> tuple[int, list[UUID]]:
    """Link the approved ingredients in one write.

    Validates the whole payload before touching a row: an unknown template
    or an ingredient outside the organization refuses with 404 and nothing
    is written. Returns ``(linked, recipe_ids)``.
    """
    # Last one wins for a duplicated ingredient: a caller sending the same
    # row twice with two products must not get a half-applied pair.
    by_ingredient: dict[UUID, IngredientTemplateLink] = {
        link.ingredient_id: link for link in request.links
    }

    templates = await core_api.product_templates.get_many_async(
        db, org_id, list({link.template_id for link in by_ingredient.values()})
    )
    if len(templates) != len({link.template_id for link in by_ingredient.values()}):
        raise NotFoundException('template', get_current_lang())

    ingredient_ids = list(by_ingredient)
    rows = {
        row.id: row
        for row in (
            await db.scalars(
                select(RecipeIngredient)
                .join(Recipe, Recipe.id == RecipeIngredient.recipe_id)
                .where(
                    RecipeIngredient.id.in_(ingredient_ids),
                    Recipe.organization_id == org_id,
                )
            )
        ).all()
    }
    if len(rows) != len(ingredient_ids):
        raise NotFoundException('ingredient', get_current_lang())

    touched: set[UUID] = set()
    for ingredient_id, link in by_ingredient.items():
        row = rows[ingredient_id]
        row.template_id = link.template_id
        touched.add(row.recipe_id)
    # The caller owns the transaction and commits; this is a flush.
    await db.flush()
    return len(by_ingredient), sorted(touched)
