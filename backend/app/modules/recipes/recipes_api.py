"""Public API surface for the recipes module.

Exposes read-only aggregates that other modules (or CoreAPI) can call
without importing the recipes module's models directly. The recipes
module owns the ``Recipe`` and ``RecipeIngredient`` tables; any
cross-module read must go through this facade.

Cross-module contract:
- Read-only access to recipes-owned data
- Org-scoped (every call takes ``org_id``)
- Backward-compatible (additive changes only)
- Graceful degradation (callers handle ``None`` / ``[]``)
"""
# architecture: allow_direct_db_access
# reason: Cross-module JOIN of recipes-owned RecipeIngredient with Core ProductTemplate cannot be expressed through CoreAPI

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.product_template import ProductTemplate

from .models.recipe import Recipe, RecipeIngredient


@dataclass(frozen=True)
class RecipeSnapshotIngredient:
    """One culinary ingredient mapped to a product template (maker bridge).

    ``template_id`` is ``None`` for free-text ingredients that were never
    linked to a template — the consumer (maker BoM snapshot) skips those.
    """

    template_id: UUID | None
    name: str
    quantity: Decimal
    uom_id: UUID | None = None
    uom_symbol: str | None = None


@dataclass(frozen=True)
class RecipeSnapshot:
    """Lightweight, org-scoped read model of a culinary recipe.

    Used by the maker module's ``from-recipe`` bridge to build a
    production recipe from a culinary one. Deliberately minimal — only the
    fields the bridge needs, so the recipes module can evolve freely.
    """

    id: UUID
    name: str
    servings: int
    ingredients: list[RecipeSnapshotIngredient] = field(default_factory=list)


class RecipesAPI:
    """Public API for the recipes module."""

    @staticmethod
    async def list_templates_with_recipe_usage_async(
        db: AsyncSession,
        org_id: UUID,
        limit: int = 200,
    ) -> list[ProductTemplate]:
        """List org + global templates ordered by recipe-ingredient usage.

        Templates referenced by this org's recipe ingredients surface
        first (the most likely relevant matches for LLM-prompt catalog
        dumps), then alphabetical. Used by the recipes
        ``template_matcher`` and the CoreAPI Tier 2 read-model
        ``core_api.product_templates.list_for_org_with_recipe_usage_async``.

        Returns ORM ``ProductTemplate`` rows so callers can read any
        column without DTO round-tripping. The query is a single
        aggregate subquery + outer join (cheap on indexed PKs).
        """
        usage = (
            select(
                RecipeIngredient.template_id,
                func.count().label('ref_count'),
            )
            .join(Recipe, RecipeIngredient.recipe_id == Recipe.id)
            .where(
                RecipeIngredient.template_id.isnot(None),
                Recipe.organization_id == org_id,
            )
            .group_by(RecipeIngredient.template_id)
            .subquery()
        )
        result = await db.execute(
            select(ProductTemplate)
            .outerjoin(usage, usage.c.template_id == ProductTemplate.id)
            .where(
                or_(
                    ProductTemplate.organization_id == org_id,
                    ProductTemplate.organization_id.is_(None),
                )
            )
            .order_by(
                func.coalesce(usage.c.ref_count, 0).desc(),
                ProductTemplate.name,
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_recipe_snapshot_async(
        db: AsyncSession,
        org_id: UUID,
        recipe_id: UUID,
    ) -> RecipeSnapshot | None:
        """Return the culinary recipe as a maker-bridge snapshot, or ``None``.

        Org-scoped: a recipe of another organization is invisible (same
        contract as every recipes read path). Ingredients are mapped to
        product templates (``template_id``) with their quantity and
        structural UoM — free-text ingredients keep ``template_id=None``.

        Graceful degradation: returns ``None`` for a missing recipe or a
        disabled module, never raises — callers decide how to react.
        """
        result = await db.execute(
            select(Recipe)
            .where(
                Recipe.id == recipe_id,
                Recipe.organization_id == org_id,
            )
            .options(
                selectinload(Recipe.ingredients).selectinload(RecipeIngredient.uom)
            )
        )
        recipe = result.scalar_one_or_none()
        if recipe is None:
            return None
        return RecipeSnapshot(
            id=recipe.id,
            name=recipe.name,
            servings=recipe.servings,
            ingredients=[
                RecipeSnapshotIngredient(
                    template_id=ing.template_id,
                    name=ing.name,
                    quantity=ing.quantity,
                    uom_id=ing.uom_id,
                    uom_symbol=ing.uom.symbol if ing.uom is not None else None,
                )
                for ing in recipe.ingredients
            ],
        )


recipes_api = RecipesAPI()


async def rank_templates_by_recipe_usage(
    db: AsyncSession, org_id: UUID, limit: int = 200
) -> list[ProductTemplate]:
    """Order product templates by how often this org's recipes use them."""
    return await recipes_api.list_templates_with_recipe_usage_async(
        db, org_id, limit=limit
    )


__all__ = ['RecipesAPI', 'recipes_api']
