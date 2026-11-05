from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import (
    AppException,
    NotFoundException,
    catalogue_refusal,
    map_service_errors,
)
from app.core.file_signature import validate_signature
from app.core.module_sdk import cover_leaf_of, served_url
from app.core.public_api import core_api
from app.core.upload_validation import format_size_limit, read_capped_upload
from app.i18n.service import get_current_lang, get_error_message

from ._helpers import resolve_servings_request
from ._recipe_cover import (
    ALLOWED_RECIPE_IMAGE_MIMES,
    MAX_COVER_BYTES,
    CoverUnreadableError,
    store_cover,
)
from ._schemas_picking import MAX_SCALE
from ._schemas_recipe import Recipe as RecipeSchema
from ._shopping_from_recipes import add_recipes_to_shopping_list
from ._shopping_rule import load_exclusions
from .cost_service import get_recipe_cost
from .nutrition_service import get_recipe_nutrition
from .schemas import (
    AddFromRecipesRequest,
    AddToShoppingListRequest,
    AddToShoppingListResponse,
    LinkIngredientTemplateRequest,
    RecipeAvailability,
    RecipeCost,
    RecipeImageResponse,
    RecipeNutrition,
)
from .services import get_recipe, get_recipe_availability, set_recipe_image_url

# Explicit image whitelist — startswith('image/') accepted image/svg+xml
# (script injection), image/jpg (non-standard), image/heic (unsupported), etc.
# The list and the storing live in `_recipe_cover`, beside the import path
# that has to obey the same rules.


def register_extras_routes(router: APIRouter) -> None:  # noqa: C901, PLR0915 - route registration, one block per endpoint
    @router.get('/{recipe_id}/availability', response_model=RecipeAvailability)
    async def recipe_availability_endpoint(
        recipe_id: UUID,
        servings: int = Query(0, ge=0, description='0 = use recipe default'),
        scale: Decimal | None = Query(None, gt=0, le=MAX_SCALE),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        lang = get_current_lang()
        recipe = await get_recipe(db, recipe_id, org_id)
        if not recipe:
            raise NotFoundException('recipe', lang)
        srv = resolve_servings_request(recipe.servings, servings, scale)
        # The exclusions ride along so the card's "Add missing" door opens
        # exactly when the list rule behind it would add a line — the flag
        # is what the door's frontend mirror reads.
        exclusions = await load_exclusions(db, org_id)
        return await get_recipe_availability(
            db, recipe, org_id, srv, exclusions=exclusions
        )

    @router.get('/{recipe_id}/nutrition', response_model=RecipeNutrition)
    async def get_recipe_nutrition_endpoint(
        recipe_id: UUID,
        servings: int = Query(default=None, ge=1),
        scale: Decimal | None = Query(None, gt=0, le=MAX_SCALE),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        lang = get_current_lang()
        recipe = await get_recipe(db, recipe_id, org_id)
        if not recipe:
            raise NotFoundException('recipe', lang)
        effective_servings = resolve_servings_request(recipe.servings, servings, scale)
        result = await get_recipe_nutrition(
            db, recipe, org_id, effective_servings, lang=lang
        )
        return result

    @router.post(
        '/{recipe_id}/ingredients/{ingredient_id}/link-template',
        response_model=RecipeSchema,
    )
    async def link_ingredient_template(
        recipe_id: UUID,
        ingredient_id: UUID,
        data: LinkIngredientTemplateRequest,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        """Link a recipe ingredient to a ProductTemplate.

        Availability, cost and picking only work for ingredients with a
        template — this endpoint lets the user fix that from the recipe
        detail view without editing the whole recipe.

        Deliberately not gated on an active picking session. The gate in
        ``update_recipe`` guards against the ingredient *list* changing under
        a running session; naming the product an ingredient already stands
        for changes nothing the session counted, and the sheet re-reads the
        session afterwards.
        """
        lang = get_current_lang()
        recipe = await get_recipe(db, recipe_id, org_id)
        if not recipe:
            raise NotFoundException('recipe')
        template = await core_api.product_templates.get_async(
            db, org_id, data.template_id
        )
        if template is None:
            raise NotFoundException('template', lang)
        ingredient = next(
            (ing for ing in recipe.ingredients if ing.id == ingredient_id), None
        )
        if ingredient is None:
            raise NotFoundException('ingredient')
        ingredient.template_id = data.template_id
        # keep: refresh below re-reads the recipe, so the ingredient change must be flushed first
        await db.flush()
        await db.refresh(recipe)
        return recipe

    @router.post(
        '/shopping-list/add-from-recipes',
        response_model=AddToShoppingListResponse,
    )
    @map_service_errors
    async def add_from_recipes_to_shopping_list(
        data: AddFromRecipesRequest,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> AddToShoppingListResponse:
        """Add what several recipes still need to one shopping list.

        Same stock check and merge as the single-recipe button; goods two
        recipes share are bought once.
        """
        return await add_recipes_to_shopping_list(
            db,
            org_id,
            current_user.id,
            data.recipe_ids,
            servings=data.servings,
            scale=data.scale,
            shopping_list_id=data.shopping_list_id,
            lang=get_current_lang(),
        )

    @router.post(
        '/{recipe_id}/add-to-shopping-list',
        response_model=AddToShoppingListResponse,
    )
    @map_service_errors
    async def add_missing_to_shopping_list(
        recipe_id: UUID,
        data: AddToShoppingListRequest,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> AddToShoppingListResponse:
        return await add_recipes_to_shopping_list(
            db,
            org_id,
            current_user.id,
            [recipe_id],
            servings=data.servings,
            scale=data.scale,
            shopping_list_id=data.shopping_list_id,
            lang=get_current_lang(),
        )

    @router.post('/{recipe_id}/image', response_model=RecipeImageResponse)
    async def upload_recipe_image(
        recipe_id: UUID,
        image: UploadFile = File(...),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> RecipeImageResponse:
        lang = get_current_lang()
        recipe = await get_recipe(db, recipe_id, org_id)
        if recipe is None:
            raise NotFoundException('recipe')

        if (
            not image.content_type
            or image.content_type not in ALLOWED_RECIPE_IMAGE_MIMES
        ):
            # Refusals on this route carry the same shape as the other image
            # doors — {code, message} — so a client that reads the code reads
            # this one too, instead of matching on the sentence.
            raise catalogue_refusal('only_image_files_allowed')

        # Capped while reading, like the core's image doors: `await
        # image.read()` copies the whole body into memory first, so a body far
        # over the limit is already there by the time the limit refuses it.
        try:
            content = await read_capped_upload(image, lang, MAX_COVER_BYTES)
        except ValueError as exc:
            raise AppException(
                status_code=413,
                code='FILE_TOO_LARGE',
                # The shared key is parameterized ({limit}) — every caller
                # has to hand it the number, or the template reaches the
                # reader with the placeholder still in it.
                message=get_error_message(
                    'image_too_large', lang, limit=format_size_limit(MAX_COVER_BYTES)
                ),
            ) from exc
        # Verify magic bytes match the declared image type
        validate_signature(content, image.content_type)

        # Re-encoded on the way in, like an imported one: the same
        # normalising, and EXIF — which on a phone photograph carries where it
        # was taken — does not survive the trip.
        try:
            stored_key = await store_cover(
                org_id, recipe_id, content, image.content_type
            )
        except CoverUnreadableError as exc:
            # A right magic number on the front of a file the decoder cannot
            # finish reading used to be stored and served back as a broken
            # frame.
            raise catalogue_refusal('image_unreadable') from exc

        # The row keeps the storage key; the address the client is handed is
        # built from it, so switching backends changes no row.
        await set_recipe_image_url(db, recipe, stored_key)
        return RecipeImageResponse(image_url=served_url(stored_key))

    @router.delete('/{recipe_id}/image', status_code=status.HTTP_204_NO_CONTENT)
    async def delete_recipe_image(
        recipe_id: UUID,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> None:
        lang = get_current_lang()
        recipe = await get_recipe(db, recipe_id, org_id)
        if not recipe:
            raise NotFoundException('recipe', lang)

        if recipe.image_url:
            # The row is writable through the recipe form, so it never names
            # the object this deletes: another recipe's cover in the same
            # organization would otherwise be picked. Only the cover's file
            # name is read, and the key is rebuilt from this organization and
            # this recipe — the facade owns the ``<org>/recipes/`` prefix.
            leaf = cover_leaf_of(recipe.image_url)
            if leaf:
                try:
                    await core_api.file_storage.delete_for_org_async(
                        org_id, 'recipes', f'{recipe_id}/{leaf}'
                    )
                except FileNotFoundError:
                    pass

        await set_recipe_image_url(db, recipe, None)

    @router.get('/{recipe_id}/cost', response_model=RecipeCost)
    async def get_recipe_cost_endpoint(
        recipe_id: UUID,
        servings: int = Query(
            default=0, ge=0, description='Servings (0 = use recipe default)'
        ),
        scale: Decimal | None = Query(None, gt=0, le=MAX_SCALE),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        lang = get_current_lang()
        recipe = await get_recipe(db, recipe_id, org_id)
        if not recipe:
            raise NotFoundException('recipe', lang)
        effective_servings = resolve_servings_request(recipe.servings, servings, scale)
        if not await core_api.settings.get_async(
            db, org_id, 'recipes', 'enable_cost_calculation', default=True
        ):
            return {
                'recipe_id': recipe.id,
                'enabled': False,
                'servings': effective_servings,
                'estimated_cost': None,
                'currency': None,
                'cost_coverage': 0.0,
                'mixed_currencies': False,
                'missing_cost_ingredients': [],
                'ingredients': [],
            }
        result = await get_recipe_cost(db, recipe, org_id, effective_servings)
        return result

    @router.get('/{recipe_id}/export')
    async def export_recipe_endpoint(
        recipe_id: UUID,
        format: str = Query('json', description='json | schema_org'),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        lang = get_current_lang()
        recipe = await get_recipe(db, recipe_id, org_id)
        if not recipe:
            raise NotFoundException('recipe', lang)
        from .import_export_service import export_recipe_json, export_recipe_schema_org

        if format == 'json':
            return export_recipe_json(recipe)
        if format == 'schema_org':
            return export_recipe_schema_org(recipe)
        raise catalogue_refusal('unsupported_export_format', format=format)
