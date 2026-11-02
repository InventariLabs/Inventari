from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import (
    NotFoundException,
    catalogue_refusal,
    map_service_errors,
)
from app.core.limiter import limiter
from app.core.public_api import core_api
from app.core.ssrf_guard import WebhookUrlRejectedError, validate_webhook_url
from app.i18n.service import get_current_lang
from app.schemas.pagination import PaginatedResponse

from .schemas import (
    Recipe as RecipeSchema,
)
from .schemas import (
    RecipeBulkDeleteRequest,
    RecipeBulkDeleteResponse,
    RecipeBulkTagRequest,
    RecipeBulkTagResponse,
    RecipeCreate,
    RecipeImportRequest,
    RecipeList,
    RecipePreview,
)
from .services import (
    annotate_recipes_with_availability,
    bulk_delete_recipes,
    bulk_tag_recipes,
    create_recipe,
    duplicate_recipe,
    get_recipe,
    list_recipes,
)


def _validate_external_url(url: str) -> None:
    """Refuse a URL that would aim the server at its own network.

    This used to read the hostname and stop: an IP literal in a private range
    was refused, but a *name* was not resolved, so a hostname whose owner
    points it at 169.254.169.254 walked through and the importer fetched it.
    The shared guard resolves the name and checks the address it gets — the
    same one the cover downloader on the neighbouring path already uses, and
    the same one that treats a name it cannot resolve as a refusal rather
    than a free pass.
    """
    try:
        validate_webhook_url(url, allow_private=False)
    except WebhookUrlRejectedError as exc:
        raise catalogue_refusal('url_must_be_public') from exc
    except ValueError as exc:
        # Malformed, no hostname, or a scheme the guard does not allow.
        raise catalogue_refusal('invalid_url_missing_host') from exc


async def _get_org_settings(db: AsyncSession, org_id: UUID) -> dict[str, Any] | None:
    return await core_api.organizations.get_settings_async(db, org_id)


def register_crud_routes(router: APIRouter) -> None:  # noqa: C901 - route registration, one block per endpoint
    @router.post('', response_model=RecipeSchema, status_code=status.HTTP_201_CREATED)
    async def create_recipe_endpoint(
        data: RecipeCreate,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        return await create_recipe(db, data, org_id, current_user.id)

    @router.get('', response_model=PaginatedResponse[RecipeList])
    async def list_recipes_endpoint(
        search: str | None = Query(None),
        tags: str | None = Query(None, description='Comma-separated tags'),
        is_favorite: bool | None = Query(None),
        collection_id: UUID | None = Query(None),
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
        sort: str = Query('newest', pattern='^(newest|name)$'),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        tags_list = [t.strip() for t in tags.split(',')] if tags else None
        recipes, total = await list_recipes(
            db,
            org_id,
            search=search,
            tags=tags_list,
            is_favorite=is_favorite,
            collection_id=collection_id,
            skip=offset,
            limit=limit,
            sort=sort,
        )
        annotated = await annotate_recipes_with_availability(db, list(recipes), org_id)
        return PaginatedResponse.from_slice(annotated, offset, limit, total)

    @router.post(
        '/bulk-delete',
        response_model=RecipeBulkDeleteResponse,
    )
    async def bulk_delete_recipes_endpoint(
        data: RecipeBulkDeleteRequest,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        deleted = await bulk_delete_recipes(
            db, data.recipe_ids, org_id, current_user.id
        )
        return RecipeBulkDeleteResponse(deleted=deleted)

    @router.post(
        '/bulk-tag',
        response_model=RecipeBulkTagResponse,
    )
    async def bulk_tag_recipes_endpoint(
        data: RecipeBulkTagRequest,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        tags = [tag.strip().lower() for tag in data.tags if tag.strip()]
        updated = await bulk_tag_recipes(db, data.recipe_ids, tags, org_id)
        return RecipeBulkTagResponse(updated=updated)

    @router.get('/available', response_model=PaginatedResponse[dict[str, Any]])
    async def available_recipes_endpoint(
        # "Available" means cookable: every ingredient on the shelf in the
        # quantity the recipe asks for. The default used to be half of them,
        # so the answer to "what can I cook" included meals that were missing
        # two ingredients out of four. Callers after a looser reading — a
        # "nearly there" list — ask for it by name.
        min_match: float = Query(1.0, ge=0.0, le=1.0),
        servings: int | None = Query(None, ge=1),
        tags: str | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> PaginatedResponse[dict[str, Any]]:
        tags_list = [t.strip() for t in tags.split(',')] if tags else None
        from .services import get_available_recipes

        recipes = await get_available_recipes(
            db, org_id, min_match=min_match, servings=servings, tags=tags_list
        )
        return PaginatedResponse.from_full_list(recipes, offset=offset, limit=limit)

    @router.get('/{recipe_id}', response_model=RecipeSchema)
    async def get_recipe_endpoint(
        recipe_id: UUID,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        lang = get_current_lang()
        recipe = await get_recipe(db, recipe_id, org_id)
        if not recipe:
            raise NotFoundException('recipe', lang)
        return recipe

    @router.post(
        '/{recipe_id}/duplicate',
        response_model=RecipeSchema,
        status_code=status.HTTP_201_CREATED,
    )
    async def duplicate_recipe_endpoint(
        recipe_id: UUID,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        lang = get_current_lang()
        duplicated = await duplicate_recipe(db, recipe_id, org_id, current_user.id)
        if not duplicated:
            raise NotFoundException('recipe', lang)
        return duplicated

    @router.post(
        '/import/preview',
        response_model=RecipePreview,
        status_code=status.HTTP_200_OK,
    )
    @limiter.limit('20/minute')
    @map_service_errors
    async def import_recipe_preview_endpoint(
        request: Request,
        data: RecipeImportRequest,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        import re as _re

        if data.format not in ('json', 'url'):
            raise catalogue_refusal('unsupported_import_format', format=data.format)
        if data.format == 'url' and (
            not data.url or not _re.match(r'^https?://', data.url)
        ):
            raise catalogue_refusal('invalid_url_scheme')
        if data.format == 'url' and data.url:
            _validate_external_url(data.url)
        from .import_export_service import preview_import

        org_settings = await _get_org_settings(db, org_id)
        preview = await preview_import(
            db,
            data.format,
            org_id,
            current_user.id,
            data=data.data,
            url=data.url,
            organization_settings=org_settings,
        )
        return preview

    @router.post(
        '/import', response_model=RecipeSchema, status_code=status.HTTP_201_CREATED
    )
    @map_service_errors
    async def import_recipe_endpoint(
        data: RecipeImportRequest,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        import re as _re

        if data.format not in ('json', 'url'):
            raise catalogue_refusal('unsupported_import_format', format=data.format)
        if data.format == 'url' and (
            not data.url or not _re.match(r'^https?://', data.url)
        ):
            raise catalogue_refusal('invalid_url_scheme')
        if data.format == 'url' and data.url:
            _validate_external_url(data.url)
        from .import_export_service import import_recipe

        recipe = await import_recipe(
            db,
            data.format,
            org_id,
            current_user.id,
            data=data.data,
            url=data.url,
        )
        return recipe
