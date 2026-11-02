"""Meal Planner sub-router — all /meal-plans endpoints."""

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.db_utils import acquire_advisory_lock, paginate_async
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    map_service_errors,
)
from app.core.module_sdk import PaginatedResponse
from app.core.modules import require_module
from app.i18n.service import get_current_lang, get_error_message
from app.modules.recipes._meal_plan import (
    add_entry_async,
    bulk_save_entries_async,
    cook_entry_async,
    copy_plan_to_week_async,
    count_meal_plans_async,
    create_meal_plan_async,
    delete_entry_async,
    delete_meal_plan_async,
    generate_shopping_list_async,
    get_meal_plan_async,
    get_suggestions_async,
    list_meal_plans_async,
    update_entry_async,
    update_meal_plan_async,
)
from app.modules.recipes._name_matching import match_key
from app.modules.recipes.models import MealSlot
from app.modules.recipes.schemas import (
    BulkEntriesSave,
    CopyPlanRequest,
    CopyPlanResponse,
    MealPlanCreate,
    MealPlanEntryCreate,
    MealPlanEntrySchema,
    MealPlanEntryUpdate,
    MealPlanListItem,
    MealPlanSchema,
    MealPlanUpdate,
    PickingStartResponse,
    ShoppingExclusionCreate,
    ShoppingExclusionSchema,
    ShoppingListGenerationResult,
    SuggestedRecipe,
)

router = APIRouter(dependencies=[Depends(require_module('recipes'))])


# ── Plan CRUD ──────────────────────────────────────────────────────────────────


# ── Shopping Exclusions ────────────────────────────────────────────────────────


@router.get('/exclusions', response_model=PaginatedResponse[ShoppingExclusionSchema])
async def list_exclusions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> PaginatedResponse[ShoppingExclusionSchema]:
    org_id = require_org(current_user)
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    from app.modules.recipes.models import ShoppingExclusion

    rows, total = await paginate_async(
        db,
        select(ShoppingExclusion)
        .where(ShoppingExclusion.organization_id == org_id)
        .options(joinedload(ShoppingExclusion.template))
        .order_by(ShoppingExclusion.name, ShoppingExclusion.id),
        limit=limit,
        offset=offset,
    )
    items = [
        ShoppingExclusionSchema(
            id=row.id,
            name=row.name,
            name_normalized=row.name_normalized,
            template_id=row.template_id,
            template_name=row.template.name if row.template else None,
            template_barcode=row.template.barcode if row.template else None,
            template_image_url=row.template.image_url if row.template else None,
            created_at=row.created_at,
        )
        for row in rows
    ]
    return PaginatedResponse.from_slice(items, offset=offset, limit=limit, total=total)


@router.post(
    '/exclusions',
    response_model=ShoppingExclusionSchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_exclusion(
    data: ShoppingExclusionCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ShoppingExclusionSchema:
    org_id = require_org(current_user)
    from sqlalchemy import select

    from app.modules.recipes.models import ShoppingExclusion

    name_normalized = match_key(data.name)

    # TOCTOU guard: lock the (org, name) slot so concurrent requests
    # don't both see "no existing" and double-insert.
    await acquire_advisory_lock(db, f'recipes.exclusion:{org_id}:{name_normalized}')

    existing = await db.scalar(
        select(ShoppingExclusion).where(
            ShoppingExclusion.organization_id == org_id,
            ShoppingExclusion.name_normalized == name_normalized,
        )
    )
    if existing:
        raise ConflictException(
            code='EXCLUSION_EXISTS',
            message=get_error_message('shopping_exclusion_exists', get_current_lang()),
        )
    exclusion = ShoppingExclusion(
        organization_id=org_id,
        name=data.name.strip(),
        name_normalized=name_normalized,
        template_id=data.template_id,
    )
    db.add(exclusion)
    await db.flush()
    await db.refresh(exclusion)
    return ShoppingExclusionSchema(
        id=exclusion.id,
        name=exclusion.name,
        name_normalized=exclusion.name_normalized,
        template_id=exclusion.template_id,
        created_at=exclusion.created_at,
    )


@router.delete('/exclusions/{exclusion_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_exclusion(
    exclusion_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    org_id = require_org(current_user)
    lang = get_current_lang()
    from app.core.db_utils import get_org_owned_or_404_async
    from app.modules.recipes.models import ShoppingExclusion

    exclusion = await get_org_owned_or_404_async(
        db, ShoppingExclusion, exclusion_id, org_id, resource='exclusion', lang=lang
    )
    await db.delete(exclusion)
    await db.flush()


@router.post('', response_model=MealPlanSchema, status_code=status.HTTP_201_CREATED)
@map_service_errors
async def create_plan(
    data: MealPlanCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    return await create_meal_plan_async(
        db, data, org_id, current_user.id, lang=get_current_lang()
    )


@router.get('', response_model=PaginatedResponse[MealPlanListItem])
async def list_plans(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    plans = await list_meal_plans_async(db, org_id, start_date, end_date, offset, limit)
    total = await count_meal_plans_async(db, org_id, start_date, end_date)
    return PaginatedResponse.from_slice(plans, offset=offset, limit=limit, total=total)


@router.get(
    '/suggestions',
    # list-envelope-exception: the best matches for one slot, capped by count
    response_model=list[SuggestedRecipe],
)
async def suggest_recipes(
    target_date: date = Query(..., alias='date'),
    slot: MealSlot = Query(...),
    count: int = Query(default=5, ge=1, le=20),
    plan_id: UUID | None = Query(default=None),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    return await get_suggestions_async(
        db, org_id, target_date, slot.value, count, plan_id
    )


@router.get('/{plan_id}', response_model=MealPlanSchema)
async def get_plan(
    plan_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    result = await get_meal_plan_async(db, plan_id, org_id)
    if result is None:
        raise NotFoundException('meal_plan', get_current_lang())
    return result


@router.put('/{plan_id}', response_model=MealPlanSchema)
@map_service_errors
async def update_plan(
    plan_id: UUID,
    data: MealPlanUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    return await update_meal_plan_async(db, plan_id, data, org_id)


@router.delete('/{plan_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(
    plan_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    org_id = require_org(current_user)
    deleted = await delete_meal_plan_async(db, plan_id, org_id, current_user.id)
    if not deleted:
        raise NotFoundException('meal_plan', get_current_lang())


@router.post('/{plan_id}/copy-to', response_model=CopyPlanResponse)
@map_service_errors
async def copy_plan_to_week(
    plan_id: UUID,
    data: CopyPlanRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> CopyPlanResponse:
    org_id = require_org(current_user)
    schema, copied, skipped = await copy_plan_to_week_async(
        db, plan_id, data, org_id, current_user.id, get_current_lang()
    )
    return CopyPlanResponse(plan=schema, copied=copied, skipped=skipped)


# ── Entries ────────────────────────────────────────────────────────────────────


@router.post(
    '/{plan_id}/entries',
    response_model=MealPlanEntrySchema,
    status_code=status.HTTP_201_CREATED,
)
@map_service_errors
async def add_plan_entry(
    plan_id: UUID,
    data: MealPlanEntryCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    return await add_entry_async(db, plan_id, data, org_id)


@router.put('/{plan_id}/entries/{entry_id}', response_model=MealPlanEntrySchema)
@map_service_errors
async def update_plan_entry(
    plan_id: UUID,
    entry_id: UUID,
    data: MealPlanEntryUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    return await update_entry_async(db, plan_id, entry_id, data, org_id)


@router.delete('/{plan_id}/entries/{entry_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan_entry(
    plan_id: UUID,
    entry_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    org_id = require_org(current_user)
    deleted = await delete_entry_async(db, plan_id, entry_id, org_id)
    if not deleted:
        raise NotFoundException('meal_plan_entry', get_current_lang())


@router.post('/{plan_id}/entries/bulk', response_model=MealPlanSchema)
@map_service_errors
async def bulk_save_plan_entries(
    plan_id: UUID,
    data: BulkEntriesSave,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    return await bulk_save_entries_async(db, plan_id, data, org_id)


# ── Shopping List Generation ───────────────────────────────────────────────────


@router.post(
    '/{plan_id}/generate-shopping-list', response_model=ShoppingListGenerationResult
)
@map_service_errors
async def generate_plan_shopping_list(
    plan_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    lang = get_current_lang()
    return await generate_shopping_list_async(
        db, plan_id, org_id, current_user.id, lang
    )


# ── Cook Now ───────────────────────────────────────────────────────────────────


@router.post(
    '/{plan_id}/entries/{entry_id}/cook',
    response_model=PickingStartResponse,
    dependencies=[require_permission('recipes:consume')],
)
@map_service_errors
async def cook_plan_entry(
    plan_id: UUID,
    entry_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    return await cook_entry_async(db, plan_id, entry_id, org_id, current_user.id)
