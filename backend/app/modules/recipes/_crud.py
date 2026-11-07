"""Recipe CRUD: create, read, list, update, delete."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.contracts import AuditAction, AuditTargetType
from app.core.contracts.events import RecipeCreatedPayload
from app.core.db_utils import escape_ilike, paginate_async
from app.core.exceptions import ConflictException
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message

from ._allergens import ALLERGEN_KEYS
from ._picking_lifecycle import terminate_session
from ._recipe_cover import adopt_remote_cover
from .events import RecipeEvent
from .models import PickingSession, Recipe, RecipeCollectionMember, RecipeIngredient
from .schemas import RecipeCreate, RecipeIngredientCreate, RecipeUpdate


def _attach_allergens(recipe: Recipe) -> None:
    """Set the computed ``allergens`` union (canonical order) on the ORM row.

    Called before a Recipe is serialized with ``Recipe`` (response) schema —
    the value is derived from the ingredients, not stored on the recipe.
    """
    found: set[str] = set()
    for ingredient in recipe.ingredients:
        found.update(ingredient.allergens or [])
    recipe.allergens = [key for key in ALLERGEN_KEYS if key in found]  # type: ignore[attr-defined]


def _attach_uom_symbols(recipe: Recipe) -> None:
    """Fill the read-time ``uom_symbol`` on each ingredient.

    The response schema declares ``uom_symbol`` as "Enriched at read time" —
    the model stores only ``uom_id``. Print views and countable-unit
    detection (clean-servings hint) read this field, so it must be populated
    alongside allergens before serialization.
    """
    for ingredient in recipe.ingredients:
        ingredient.uom_symbol = ingredient.uom.symbol if ingredient.uom else None  # type: ignore[attr-defined]


async def create_recipe(
    db: AsyncSession, data: RecipeCreate, organization_id: UUID, user_id: UUID
) -> Recipe:
    recipe = Recipe(
        organization_id=organization_id,
        created_by=user_id,
        name=data.name,
        description=data.description,
        instructions=data.instructions,
        servings=data.servings,
        prep_time_minutes=data.prep_time_minutes,
        image_url=data.image_url,
        source_url=data.source_url,
        tags=data.tags,
        is_favorite=data.is_favorite,
    )
    db.add(recipe)
    await db.flush()

    for idx, ing_data in enumerate(data.ingredients):
        ingredient = RecipeIngredient(
            recipe_id=recipe.id, **_ingredient_values(ing_data, idx)
        )
        db.add(ingredient)

    await core_api.events.emit_transactional_async(
        db,
        RecipeEvent.RECIPE_CREATED,
        RecipeCreatedPayload(
            organization_id=str(organization_id),
            recipe_id=str(recipe.id),
            name=recipe.name,
        ),
    )
    await db.flush()
    await db.refresh(recipe)
    await adopt_remote_cover(db, recipe, data.image_source_url)
    _attach_allergens(recipe)
    return recipe


async def get_recipe(
    db: AsyncSession, recipe_id: UUID, organization_id: UUID
) -> Recipe | None:
    result = await db.execute(
        select(Recipe)
        .options(selectinload(Recipe.ingredients))
        .where(Recipe.id == recipe_id, Recipe.organization_id == organization_id)
    )
    recipe = result.scalars().first()
    if recipe:
        _attach_allergens(recipe)
        _attach_uom_symbols(recipe)
    return recipe


async def list_recipes(
    db: AsyncSession,
    organization_id: UUID,
    search: str | None = None,
    tags: list[str] | None = None,
    is_favorite: bool | None = None,
    collection_id: UUID | None = None,
    offset: int = 0,
    limit: int = 50,
    sort: str = 'newest',
) -> tuple[list[Recipe], int]:
    """List recipes with pagination.

       Returns ``(items, total)`` — the total is computed independently of
       ``offset``/``limit`` so the client can render the result count and the
    real last page instead of guessing from the page size.
    """
    stmt = (
        select(Recipe)
        .options(selectinload(Recipe.ingredients))
        .where(Recipe.organization_id == organization_id)
    )
    if search:
        stmt = stmt.where(Recipe.name.ilike(f'%{escape_ilike(search)}%'))
    if tags:
        stmt = stmt.where(and_(*[Recipe.tags.contains([tag]) for tag in tags]))
    if is_favorite is not None:
        stmt = stmt.where(Recipe.is_favorite == is_favorite)
    if collection_id is not None:
        stmt = stmt.join(
            RecipeCollectionMember,
            RecipeCollectionMember.recipe_id == Recipe.id,
        ).where(RecipeCollectionMember.collection_id == collection_id)
    if sort == 'name':
        stmt = stmt.order_by(Recipe.name.asc())
    else:
        stmt = stmt.order_by(Recipe.is_favorite.desc(), Recipe.updated_at.desc())
    return await paginate_async(db, stmt, limit=limit, offset=offset)


def _ingredient_values(ing_data: RecipeIngredientCreate, idx: int) -> dict[str, Any]:
    """The writable columns of one ingredient, for both insert and update."""
    return {
        'template_id': ing_data.template_id,
        'name': ing_data.name,
        'display_text': ing_data.display_text,
        'ingredient_group_name': ing_data.ingredient_group_name,
        'quantity': ing_data.quantity,
        'uom_id': ing_data.uom_id,
        'is_optional': ing_data.is_optional,
        'is_spice': ing_data.is_spice,
        'picking_skip': ing_data.picking_skip,
        'sort_order': ing_data.sort_order if ing_data.sort_order else idx,
        'calories_kcal_per_100g': ing_data.calories_kcal_per_100g,
        'original_quantity': ing_data.original_quantity,
        'original_unit_text': ing_data.original_unit_text,
        'price': ing_data.price,
        'price_uom_id': ing_data.price_uom_id,
        'price_currency': ing_data.price_currency,
        'allergens': ing_data.allergens,
    }


async def _apply_ingredient_changes(
    db: AsyncSession, recipe: Recipe, incoming: list[RecipeIngredientCreate]
) -> None:
    """Update the ingredient list in place — never delete-then-recreate.

    Picking sessions point at ``recipe_ingredients`` rows, so replacing the
    whole list on every save wiped the consumption trace of sessions that were
    already finished. Rows the client sends back with their ``id`` are updated,
    rows it stops sending are deleted, and only genuinely new ones are inserted.
    """
    existing_result = await db.execute(
        select(RecipeIngredient)
        .where(RecipeIngredient.recipe_id == recipe.id)
        # Two concurrent saves would otherwise each read the list before the
        # other wrote it, and the loser's rows would be deleted as "no longer
        # sent" — taking their picking trace out of reach with them.
        .with_for_update()
    )
    existing = {row.id: row for row in existing_result.scalars().all()}

    kept: set[UUID] = set()
    for idx, ing_data in enumerate(incoming):
        values = _ingredient_values(ing_data, idx)
        row = existing.get(ing_data.id) if ing_data.id is not None else None
        if row is None:
            db.add(RecipeIngredient(recipe_id=recipe.id, **values))
            continue
        kept.add(row.id)
        for field, value in values.items():
            setattr(row, field, value)

    removed = [row_id for row_id in existing if row_id not in kept]
    if removed:
        # ON DELETE SET NULL on picking_session_items.ingredient_id detaches
        # the trace; its snapshot columns keep it readable.
        await db.execute(
            delete(RecipeIngredient).where(RecipeIngredient.id.in_(removed))
        )


async def update_recipe(
    db: AsyncSession, recipe: Recipe, data: RecipeUpdate
) -> Recipe | None:
    # Reject ingredient edits while a picking session is active.
    # Changing ingredients mid-pick would invalidate the session's checklist
    # and create inconsistent state. The caller must cancel or complete the
    # session first.
    if data.ingredients is not None:
        active_session_result = await db.execute(
            select(PickingSession)
            .where(
                PickingSession.recipe_id == recipe.id,
                PickingSession.organization_id == recipe.organization_id,
                PickingSession.status == 'active',
            )
            .with_for_update()
        )
        if active_session_result.scalars().first():
            raise ConflictException(
                code='PICKING_ACTIVE',
                message=get_error_message(
                    'picking_active_recipe_locked', get_current_lang()
                ),
            )

    for field, value in data.model_dump(
        exclude_unset=True, exclude={'ingredients'}
    ).items():
        setattr(recipe, field, value)

    if data.ingredients is not None:
        await _apply_ingredient_changes(db, recipe, data.ingredients)

    recipe.updated_at = datetime.now(UTC)
    recipe_id = recipe.id
    org_id = recipe.organization_id
    await db.flush()
    # Expire the instance so the identity map doesn't serve stale
    # relationship data (the session keeps the old ingredient
    # collection after delete + add).
    db.expire(recipe)
    refreshed = await get_recipe(db, recipe_id, org_id)
    return refreshed or recipe


async def _log_recipe_deletion(
    db: AsyncSession, recipe: Recipe, user_id: UUID, *, bulk: bool = False
) -> None:
    """Write the journal row for one recipe that is about to go.

    Deleting is the only act on a recipe the organization log carries — see
    the rule in ``AuditTargetType``: the row cannot be rebuilt from anything
    else, while its edits are its author's own work and would be noise. The
    name rides in the snapshot because after the delete there is nothing
    left to look it up from. Flushes inside the caller's transaction; the
    caller owns the commit.
    """
    await core_api.audit_log.log_action_async(
        db,
        organization_id=recipe.organization_id,
        user_id=user_id,
        action=AuditAction.HARD_DELETE,
        target_type=AuditTargetType.RECIPE,
        target_id=recipe.id,
        snapshot={'name': recipe.name},
        meta_data={'bulk': True} if bulk else None,
    )


async def delete_recipe(db: AsyncSession, recipe: Recipe, user_id: UUID) -> None:
    # Terminate any active picking sessions to restore consumed stock
    # before the CASCADE delete removes the session records.
    active_sessions = await db.execute(
        select(PickingSession)
        .where(
            PickingSession.recipe_id == recipe.id,
            PickingSession.organization_id == recipe.organization_id,
            PickingSession.status == 'active',
        )
        .with_for_update()
    )
    for session in active_sessions.scalars():
        await terminate_session(db, session, reason='recipe_delete')

    await _log_recipe_deletion(db, recipe, user_id)
    await db.delete(recipe)
    await db.flush()


async def duplicate_recipe(
    db: AsyncSession, recipe_id: UUID, organization_id: UUID, user_id: UUID
) -> Recipe | None:
    """Deep-copy a recipe as a starting point for variants.

    Copies name (suffixed " (copy)"), description, instructions, servings,
    prep time, tags and all ingredients. The copy starts fresh: no image_url,
    no source_url and is_favorite=False.
    """
    result = await db.execute(
        select(Recipe)
        .options(selectinload(Recipe.ingredients))
        .where(Recipe.id == recipe_id, Recipe.organization_id == organization_id)
        .with_for_update()
    )
    source = result.scalars().first()
    if not source:
        return None

    copy = Recipe(
        organization_id=organization_id,
        created_by=user_id,
        name=f'{source.name} (copy)',
        description=source.description,
        instructions=source.instructions,
        servings=source.servings,
        prep_time_minutes=source.prep_time_minutes,
        tags=list(source.tags) if source.tags else None,
        is_favorite=False,
    )
    db.add(copy)
    await db.flush()

    for ing in source.ingredients:
        db.add(
            RecipeIngredient(
                recipe_id=copy.id,
                template_id=ing.template_id,
                name=ing.name,
                display_text=ing.display_text,
                ingredient_group_name=ing.ingredient_group_name,
                quantity=ing.quantity,
                uom_id=ing.uom_id,
                is_optional=ing.is_optional,
                is_spice=ing.is_spice,
                picking_skip=ing.picking_skip,
                sort_order=ing.sort_order,
                calories_kcal_per_100g=ing.calories_kcal_per_100g,
                original_quantity=ing.original_quantity,
                original_unit_text=ing.original_unit_text,
                price=ing.price,
                price_uom_id=ing.price_uom_id,
                price_currency=ing.price_currency,
                allergens=list(ing.allergens or []),
            )
        )

    await db.flush()
    await db.refresh(copy)
    _attach_allergens(copy)
    return copy


async def bulk_delete_recipes(
    db: AsyncSession, recipe_ids: list[UUID], organization_id: UUID, user_id: UUID
) -> int:
    """Delete multiple recipes (org-scoped). Returns the number deleted.

    Active picking sessions are terminated first (restores consumed stock),
    matching the single-recipe delete path. Each recipe gets its own journal
    row, flagged ``meta_data.bulk`` — the same deletion made one at a time
    leaves the same rows, so the trace does not depend on which button was
    pressed (docs/subsystems/AUDIT.md).
    """
    if not recipe_ids:
        return 0
    result = await db.execute(
        select(Recipe).where(
            Recipe.organization_id == organization_id,
            Recipe.id.in_(recipe_ids),
        )
    )
    recipes = list(result.scalars().all())
    for recipe in recipes:
        active_sessions = await db.execute(
            select(PickingSession)
            .where(
                PickingSession.recipe_id == recipe.id,
                PickingSession.organization_id == organization_id,
                PickingSession.status == 'active',
            )
            .with_for_update()
        )
        for session in active_sessions.scalars():
            await terminate_session(db, session, reason='recipe_delete')
        await _log_recipe_deletion(db, recipe, user_id, bulk=True)
        await db.delete(recipe)
    await db.flush()
    return len(recipes)


async def bulk_tag_recipes(
    db: AsyncSession,
    recipe_ids: list[UUID],
    tags: list[str],
    organization_id: UUID,
) -> int:
    """Append tags to multiple recipes (deduplicated). Returns the number updated."""
    if not recipe_ids or not tags:
        return 0
    result = await db.execute(
        select(Recipe)
        .where(
            Recipe.organization_id == organization_id,
            Recipe.id.in_(recipe_ids),
        )
        .with_for_update()
    )
    recipes = list(result.scalars().all())
    for recipe in recipes:
        existing = list(recipe.tags) if recipe.tags else []
        merged = list(existing)
        for tag in tags:
            if tag not in merged:
                merged.append(tag)
        if merged != existing:
            recipe.tags = merged
            recipe.updated_at = datetime.now(UTC)
    await db.flush()
    return len(recipes)
