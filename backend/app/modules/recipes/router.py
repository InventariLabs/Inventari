from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_read_write,
)
from app.core.exceptions import catalogue_status_refusal
from app.core.module_sdk import PaginatedResponse
from app.core.modules import require_module

from ._router_collections import register_collection_routes
from ._router_crud import register_crud_routes
from ._router_extras import register_extras_routes
from ._router_ingredient_matching import register_ingredient_matching_routes
from ._router_picking import register_picking_routes
from .ingredient_defaults_router import router as ingredient_defaults_router
from .meal_planner.router import router as meal_planner_router
from .schemas import (
    Recipe as RecipeSchema,
)
from .schemas import (
    RecipeTagItem,
    RecipeUpdate,
    TagColorRequest,
    TagColorResponse,
    TagDeleteResponse,
    TagMergeRequest,
    TagMergeResponse,
    UnitConversionCreate,
    UnitConversionSchema,
    UnitConversionUpdate,
)
from .services import delete_recipe, get_recipe, update_recipe
from .tag_service import delete_tag, list_tags, merge_tags, upsert_tag_color
from .unit_conversion_service import (
    create_conversion,
    delete_conversion,
    list_conversions,
    update_conversion,
)

# The module gate alone let every member of an organization write everything
# here, which produced a rule nobody would choose: a read-only account could
# not cook a recipe — that consumes stock, and `recipes:consume` guards it —
# but could delete one. Both neighbours of this module already mount the pair.
router = APIRouter(
    dependencies=[
        Depends(require_module('recipes')),
        require_read_write('recipes:read', 'recipes:write'),
    ]
)

router.include_router(meal_planner_router, prefix='/meal-plans')
router.include_router(ingredient_defaults_router)


@router.get('/tags', response_model=PaginatedResponse[RecipeTagItem])
async def list_tags_endpoint(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None),
    tags: str | None = Query(None, description='Comma-separated tags'),
    is_favorite: bool | None = Query(None),
    collection_id: UUID | None = Query(None),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    tags_list = [t.strip() for t in tags.split(',')] if tags else None
    found = await list_tags(
        db,
        org_id,
        search=search,
        tags=tags_list,
        is_favorite=is_favorite,
        collection_id=collection_id,
    )
    return PaginatedResponse.from_full_list(found, offset=offset, limit=limit)


@router.post('/tags/merge', response_model=TagMergeResponse)
async def merge_tags_endpoint(
    data: TagMergeRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    return await merge_tags(db, data.old_tag, data.new_tag, org_id)


@router.delete('/tags/{tag_name}', response_model=TagDeleteResponse)
async def delete_tag_endpoint(
    tag_name: str,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    return await delete_tag(db, tag_name, org_id)


@router.patch('/tags/{tag_name}/color', response_model=TagColorResponse)
async def set_tag_color_endpoint(
    tag_name: str,
    data: TagColorRequest,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    return await upsert_tag_color(db, tag_name, data.color, org_id)


@router.get('/unit-conversions', response_model=PaginatedResponse[UnitConversionSchema])
async def list_unit_conversions_endpoint(
    lang: str = Query('en', max_length=5),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    conversions = await list_conversions(db, org_id)
    return PaginatedResponse.from_full_list(conversions, offset=offset, limit=limit)


@router.post(
    '/unit-conversions',
    response_model=UnitConversionSchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_unit_conversion_endpoint(
    data: UnitConversionCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    return await create_conversion(
        db,
        organization_id=org_id,
        ingredient_key=data.ingredient_key,
        ingredient_name=data.ingredient_name,
        source_unit=data.source_unit,
        metric_quantity=data.metric_quantity,
        metric_unit=data.metric_unit,
        category=data.category,
        lang=data.lang,
    )


@router.put(
    '/unit-conversions/{conversion_id}',
    response_model=UnitConversionSchema,
)
async def update_unit_conversion_endpoint(
    conversion_id: UUID,
    data: UnitConversionUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    result = await update_conversion(
        db,
        conversion_id=conversion_id,
        organization_id=org_id,
        **data.model_dump(exclude_none=True),
    )
    if not result:
        raise catalogue_status_refusal(
            'conversion_not_found', status.HTTP_404_NOT_FOUND
        )
    return result


@router.delete(
    '/unit-conversions/{conversion_id}',
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_unit_conversion_endpoint(
    conversion_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> None:
    deleted = await delete_conversion(db, conversion_id, org_id)
    if not deleted:
        raise catalogue_status_refusal(
            'conversion_not_found_or_system', status.HTTP_404_NOT_FOUND
        )


# Static collection routes MUST be registered before the dynamic
# /{recipe_id} routes, otherwise FastAPI would shadow them.
register_collection_routes(router)
register_crud_routes(router)
register_picking_routes(router)
register_extras_routes(router)
register_ingredient_matching_routes(router)


@router.put('/{recipe_id}', response_model=RecipeSchema)
async def update_recipe_endpoint(
    recipe_id: UUID,
    data: RecipeUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> Any:
    recipe = await get_recipe(db, recipe_id, org_id)
    if not recipe:
        raise catalogue_status_refusal('recipe_not_found', status.HTTP_404_NOT_FOUND)
    result = await update_recipe(db, recipe, data)
    if result is None:
        raise catalogue_status_refusal('recipe_not_found', status.HTTP_404_NOT_FOUND)
    return result


@router.delete('/{recipe_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipe_endpoint(
    recipe_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> None:
    recipe = await get_recipe(db, recipe_id, org_id)
    if not recipe:
        raise catalogue_status_refusal('recipe_not_found', status.HTTP_404_NOT_FOUND)
    await delete_recipe(db, recipe, current_user.id)
