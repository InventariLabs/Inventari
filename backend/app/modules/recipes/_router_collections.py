"""Recipe collections routes."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import catalogue_status_refusal, map_service_errors
from app.core.module_sdk import PaginatedResponse

from ._collections import (
    add_recipe_to_collection_async,
    create_collection_async,
    delete_collection_async,
    list_collections_async,
    remove_recipe_from_collection_async,
    update_collection_async,
)
from .schemas import (
    RecipeCollectionCreate,
    RecipeCollectionMemberRequest,
    RecipeCollectionMemberResponse,
    RecipeCollectionSchema,
    RecipeCollectionUpdate,
)


def register_collection_routes(router: APIRouter) -> None:
    @router.post(
        '/collections',
        response_model=RecipeCollectionSchema,
        status_code=status.HTTP_201_CREATED,
    )
    @map_service_errors
    async def create_collection_endpoint(
        data: RecipeCollectionCreate,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        collection = await create_collection_async(db, org_id, current_user.id, data)
        return RecipeCollectionSchema(
            id=collection.id,
            name=collection.name,
            icon=collection.icon,
            parent_id=collection.parent_id,
        )

    @router.get(
        '/collections', response_model=PaginatedResponse[RecipeCollectionSchema]
    )
    async def list_collections_endpoint(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        collections = await list_collections_async(db, org_id)
        return PaginatedResponse.from_full_list(collections, offset=offset, limit=limit)

    @router.put(
        '/collections/{collection_id}',
        response_model=RecipeCollectionSchema,
    )
    @map_service_errors
    async def update_collection_endpoint(
        collection_id: UUID,
        data: RecipeCollectionUpdate,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        collection = await update_collection_async(db, org_id, collection_id, data)
        if collection is None:
            raise catalogue_status_refusal(
                'recipe_not_found', status.HTTP_404_NOT_FOUND
            )
        return RecipeCollectionSchema(
            id=collection.id,
            name=collection.name,
            icon=collection.icon,
            parent_id=collection.parent_id,
        )

    @router.delete(
        '/collections/{collection_id}',
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_collection_endpoint(
        collection_id: UUID,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> None:
        deleted = await delete_collection_async(db, org_id, collection_id)
        if not deleted:
            raise catalogue_status_refusal(
                'recipe_not_found', status.HTTP_404_NOT_FOUND
            )

    @router.post(
        '/collections/{collection_id}/recipes',
        response_model=RecipeCollectionMemberResponse,
        status_code=status.HTTP_201_CREATED,
    )
    @map_service_errors
    async def add_recipe_to_collection_endpoint(
        collection_id: UUID,
        data: RecipeCollectionMemberRequest,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        await add_recipe_to_collection_async(db, org_id, collection_id, data.recipe_id)
        # Idempotent: already a member returns the same mapping.
        return RecipeCollectionMemberResponse(
            collection_id=collection_id, recipe_id=data.recipe_id
        )

    @router.delete(
        '/collections/{collection_id}/recipes/{recipe_id}',
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def remove_recipe_from_collection_endpoint(
        collection_id: UUID,
        recipe_id: UUID,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> None:
        removed = await remove_recipe_from_collection_async(
            db, org_id, collection_id, recipe_id
        )
        if not removed:
            raise catalogue_status_refusal(
                'recipe_not_found', status.HTTP_404_NOT_FOUND
            )
