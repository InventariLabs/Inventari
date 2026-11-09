"""Recipe CRUD, catalog and module settings endpoints.

Prefix: ``/recipes`` (mounted under ``/api/v1/maker/recipes``).
Separate from the legacy ``/bom`` endpoints, which remain as thin
adapters for compatibility. Once the FE migrates to these endpoints,
the ``/bom/*`` routes can be deprecated.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
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
from app.core.module_sdk import journal_config_change, record_settings
from app.core.public_api import core_api
from app.i18n.service import get_current_lang, get_error_message

from . import cost_rollup, recipe_service, stock_consumption
from ._router_bom import _attach_child_names
from ._schemas_bom import BoMLineRead
from ._schemas_recipes import (
    AvailabilityResponse,
    BoMLineCreateForRecipe,
    BoMLineUpdate,
    IngredientAvailabilityItem,
    MakerSettingsRead,
    MakerSettingsUpdate,
    RecipeBridgeRead,
    RecipeCatalogItem,
    RecipeCatalogResponse,
    RecipeCostLineCreate,
    RecipeCostLineRead,
    RecipeCostLineUpdate,
    RecipeCreate,
    RecipeFromCulinaryCreate,
    RecipeRead,
    RecipeUpdate,
)
from .exceptions import DuplicateBomLineError, RecipeInUseError
from .models import MakerRecipe

router = APIRouter(prefix='/recipes', tags=['maker'])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _enrich_recipe_name(
    db: AsyncSession, org_id: UUID, recipe: MakerRecipe
) -> str | None:
    template = await core_api.product_templates.get_async(
        db, org_id, recipe.output_template_id
    )
    return template.name if template else None


async def _output_uom_symbol(
    db: AsyncSession, org_id: UUID, recipe: MakerRecipe
) -> str | None:
    """The unit a batch yield is counted in.

    The recipe may state its own; otherwise the output product's applies.
    """
    uom_id = recipe.batch_yield_uom_id
    if uom_id is None:
        template = await core_api.product_templates.get_async(
            db, org_id, recipe.output_template_id
        )
        uom_id = template.uom_id if template else None
    if uom_id is None:
        return None
    uom = await core_api.uoms.get_async(db, uom_id, org_id)
    return uom.symbol if uom else None


# ---------------------------------------------------------------------------
# Module settings
# ---------------------------------------------------------------------------

settings_router = APIRouter(prefix='/settings', tags=['maker'])


@settings_router.get('', response_model=MakerSettingsRead)
async def get_maker_settings(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> MakerSettingsRead:
    settings = await recipe_service.get_settings(db, org_id)
    return MakerSettingsRead.model_validate(settings)


@settings_router.patch(
    '',
    response_model=MakerSettingsRead,
    dependencies=[require_permission('maker:manage')],
)
async def update_maker_settings(
    data: MakerSettingsUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> MakerSettingsRead:
    # Copied before the write: the service mutates this same row.
    before = record_settings(
        await recipe_service.get_settings(db, org_id, for_update=True)
    )
    settings = await recipe_service.update_settings(
        db,
        org_id,
        reference_direction=data.reference_direction,
        allow_overproduction=data.allow_overproduction,
        availability_check_scope=data.availability_check_scope,
        create_on_shortage_strategy=data.create_on_shortage_strategy,
    )
    await db.refresh(settings)
    # Whether a run may go ahead short of ingredients, or make more than
    # planned, is a rule every production order is held to.
    await journal_config_change(
        db,
        org_id,
        current_user.id,
        module='maker',
        subject='settings',
        keys={
            'reference_direction',
            'allow_overproduction',
            'availability_check_scope',
            'create_on_shortage_strategy',
        },
        before=before,
        after=settings,
    )
    return MakerSettingsRead.model_validate(settings)


# ---------------------------------------------------------------------------
# Catalog (GET /recipes)
# ---------------------------------------------------------------------------


@router.get('', response_model=RecipeCatalogResponse)
async def list_recipes(
    search: str | None = Query(None),
    output_template_id: UUID | None = Query(
        None, description='Only formulas producing this product'
    ),
    sort: str = Query('newest', pattern='^(newest|oldest|name)$'),
    # ``skip`` stays the wire name: the maker screens send it and the REST
    # query shipped with 0.11. Everything below the router says ``offset``.
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> RecipeCatalogResponse:
    """List all recipes in the org as catalog cards.

    ``output_template_id`` narrows the catalog to one product's formulas —
    a product can carry several, and a caller holding only the product has
    no other way to reach them.
    """
    recipes, total = await recipe_service.list_catalog(
        db,
        org_id,
        search=search,
        output_template_id=output_template_id,
        sort=sort,
        offset=skip,
        limit=limit,
    )

    # Batch enrichment: template names + last unit cost.
    recipe_ids = [r.id for r in recipes]
    template_ids = list({r.output_template_id for r in recipes})

    # Template names.
    templates = await core_api.product_templates.list_for_org_async(
        db, org_id, limit=10_000
    )
    template_names = {t.id: t.name for t in templates}
    template_uom_ids = {t.id: t.uom_id for t in templates}
    template_image_urls = {t.id: t.image_url for t in templates}
    uom_symbols = {
        uom.id: uom.symbol for uom in await core_api.uoms.list_for_org_async(db, org_id)
    }
    # On-hand stock per template — one batched query, not per-row N+1.
    template_stock = await stock_consumption.get_stock_totals(db, org_id, template_ids)

    # Last unit cost + last produced at.
    last_costs = await recipe_service.get_last_unit_costs(db, org_id, recipe_ids)

    # Org-level reference direction — one settings fetch for the whole page.
    settings = await recipe_service.get_settings(db, org_id)
    reference_direction = settings.reference_direction

    # Ingredient counts.
    ingredient_counts: dict[UUID, int] = {}
    if recipe_ids:
        from sqlalchemy import func
        from sqlalchemy import select as sa_select

        from .models import BoMLine

        count_rows = await db.execute(
            sa_select(BoMLine.recipe_id, func.count(BoMLine.id))
            .where(
                BoMLine.organization_id == org_id,
                BoMLine.recipe_id.in_(recipe_ids),
            )
            .group_by(BoMLine.recipe_id)
        )
        ingredient_counts = {row.recipe_id: row[1] for row in count_rows.all()}

    # Never-run recipes get today's estimate, computed for the page in one
    # batched pass: the explosion, the unit catalogue and the rates are
    # shared across the page, where a rollup per row made the query count
    # grow with the page size.
    estimate_requests = [
        (recipe, recipe.batch_yield_qty)
        for recipe in recipes
        if last_costs.get(recipe.id) is None
        and ingredient_counts.get(recipe.id, 0) > 0
        and recipe.batch_yield_qty
    ]
    estimates = (
        await cost_rollup.compute_cost_rollups_for_recipes(
            db, org_id, estimate_requests
        )
        if estimate_requests
        else {}
    )

    def _yield_uom_symbol(recipe: MakerRecipe) -> str | None:
        uom_id = recipe.batch_yield_uom_id or template_uom_ids.get(
            recipe.output_template_id
        )
        return uom_symbols.get(uom_id) if uom_id else None

    items = []
    for recipe in recipes:
        last_run = last_costs.get(recipe.id)
        unit_cost = last_run.unit_cost if last_run else None
        uncosted = last_run.uncosted_ingredients if last_run else 0
        estimated_unit_cost = None
        estimated_uncosted = 0
        if last_run is None and ingredient_counts.get(recipe.id, 0) > 0:
            # Never run: the card's number is today's estimate from the same
            # rollup the cost tab computes — the dash it used to show read
            # as "the system does not know" one click before the same
            # application showed the number. A recipe with a run keeps the
            # run's figure, under a label that says so. Quantized to the
            # run's four decimals: a raw division printed 4.200000 next to
            # the run's 4.2000 and read as a different precision, not a
            # different time.
            rollup = estimates.get(recipe.id)
            if recipe.batch_yield_qty and rollup is not None and rollup.total > 0:
                estimated_unit_cost = (rollup.total / recipe.batch_yield_qty).quantize(
                    Decimal('0.0001')
                )
                estimated_uncosted = rollup.unrated_count
        result = None
        # A margin measured against a cost that left ingredients out is
        # overstated by exactly what was left out, and it is the number
        # somebody prices from.
        if (
            recipe.reference_price is not None
            and unit_cost is not None
            and not uncosted
        ):
            result = recipe.reference_price - unit_cost
        items.append(
            RecipeCatalogItem(
                id=recipe.id,
                output_template_id=recipe.output_template_id,
                name=recipe.name,
                output_template_name=template_names.get(recipe.output_template_id),
                output_template_image_url=template_image_urls.get(
                    recipe.output_template_id
                ),
                batch_yield_qty=recipe.batch_yield_qty,
                batch_yield_uom_symbol=_yield_uom_symbol(recipe),
                is_default=recipe.is_default,
                ingredient_count=ingredient_counts.get(recipe.id, 0),
                unit_cost=unit_cost,
                uncosted_ingredients=uncosted,
                estimated_unit_cost=estimated_unit_cost,
                estimated_uncosted_ingredients=estimated_uncosted,
                reference_price=recipe.reference_price,
                result=result,
                reference_direction=reference_direction,
                stock_qty=template_stock.get(recipe.output_template_id),
                last_produced_at=last_run.completed_at if last_run else None,
            )
        )

    return RecipeCatalogResponse.from_slice(
        items=items, offset=skip, limit=limit, total=total
    )


# ---------------------------------------------------------------------------
# Recipe CRUD
# ---------------------------------------------------------------------------


@router.get('/{recipe_id}', response_model=RecipeRead)
async def get_recipe(
    recipe_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> RecipeRead:
    recipe = await recipe_service.get_recipe(db, org_id, recipe_id)
    if recipe is None:
        raise NotFoundException('maker_recipe', get_current_lang())
    name = await _enrich_recipe_name(db, org_id, recipe)

    # Ingredient lines + fixed cost lines (selectin-loaded relationships).
    lines = list(recipe.lines)
    cost_lines = list(recipe.cost_lines)
    await _attach_child_names(db, org_id, lines)

    # Cheap AVCO cost estimate per unit of output (None without a BOM).
    estimated_unit_cost = None
    if lines:
        estimated_unit_cost = await cost_rollup.compute_unit_cost(
            db,
            org_id,
            recipe.output_template_id,
            recipe.batch_yield_qty,
            recipe_id=recipe.id,
        )

    data = {
        k: v
        for k, v in recipe.__dict__.items()
        if not k.startswith('_') and k not in ('lines', 'cost_lines')
    }
    return RecipeRead(
        **data,
        output_template_name=name,
        batch_yield_uom_symbol=await _output_uom_symbol(db, org_id, recipe),
        lines=lines,
        cost_lines=cost_lines,
        estimated_unit_cost=estimated_unit_cost,
    )


@router.post(
    '/from-recipe',
    response_model=RecipeBridgeRead,
    status_code=201,
    dependencies=[require_permission('maker:manage')],
)
@map_service_errors
async def create_recipe_from_culinary(
    data: RecipeFromCulinaryCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> RecipeBridgeRead:
    """Create a maker recipe as a frozen snapshot of a culinary recipe.

    The culinary recipe is resolved through the recipes module's public API
    (``recipes_api``); when the recipe does not exist in this organization —
    including when the recipes module is disabled — the endpoint returns
    404, so the bridge degrades gracefully instead of 500-ing.
    """
    exists = await core_api.product_templates.exists_for_org_async(
        db, org_id, data.output_template_id
    )
    if not exists:
        raise NotFoundException('output_template', get_current_lang())

    try:
        recipe, created = await recipe_service.create_recipe_from_culinary(
            db, org_id, data, current_user
        )
    except IntegrityError as exc:
        raise ConflictException(
            'RECIPE_NAME_TAKEN',
            get_error_message('recipe_name_taken', get_current_lang()),
        ) from exc

    await db.refresh(recipe)
    name = await _enrich_recipe_name(db, org_id, recipe)
    return RecipeBridgeRead(
        **{k: v for k, v in recipe.__dict__.items() if not k.startswith('_')},
        output_template_name=name,
        batch_yield_uom_symbol=await _output_uom_symbol(db, org_id, recipe),
        created=created,
    )


@router.post(
    '',
    response_model=RecipeRead,
    status_code=201,
    dependencies=[require_permission('maker:manage')],
)
async def create_recipe(
    data: RecipeCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> RecipeRead:
    # Verify template exists in org.
    exists = await core_api.product_templates.exists_for_org_async(
        db, org_id, data.output_template_id
    )
    if not exists:
        raise NotFoundException('output_template', get_current_lang())

    try:
        recipe = await recipe_service.create_recipe(db, org_id, data, current_user)
    except IntegrityError as exc:
        raise ConflictException(
            'RECIPE_NAME_TAKEN',
            get_error_message('recipe_name_taken', get_current_lang()),
        ) from exc

    await db.refresh(recipe)
    name = await _enrich_recipe_name(db, org_id, recipe)
    return RecipeRead(
        **{k: v for k, v in recipe.__dict__.items() if not k.startswith('_')},
        output_template_name=name,
        batch_yield_uom_symbol=await _output_uom_symbol(db, org_id, recipe),
    )


@router.patch(
    '/{recipe_id}',
    response_model=RecipeRead,
    dependencies=[require_permission('maker:manage')],
)
@map_service_errors
async def update_recipe(
    recipe_id: UUID,
    data: RecipeUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> RecipeRead:
    recipe = await recipe_service.update_recipe(
        db, org_id, recipe_id, data, current_user
    )

    await db.refresh(recipe)
    name = await _enrich_recipe_name(db, org_id, recipe)
    return RecipeRead(
        **{k: v for k, v in recipe.__dict__.items() if not k.startswith('_')},
        output_template_name=name,
        batch_yield_uom_symbol=await _output_uom_symbol(db, org_id, recipe),
    )


@router.delete(
    '/{recipe_id}',
    status_code=204,
    dependencies=[require_permission('maker:manage')],
)
@map_service_errors
async def delete_recipe(
    recipe_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> None:
    try:
        await recipe_service.delete_recipe(db, org_id, recipe_id, current_user)
    except RecipeInUseError as exc:
        raise ConflictException('RECIPE_IN_USE', str(exc)) from exc


# ---------------------------------------------------------------------------
# BOM lines
# ---------------------------------------------------------------------------


@router.post(
    '/{recipe_id}/bom-lines',
    response_model=BoMLineRead,
    status_code=201,
    dependencies=[require_permission('maker:manage')],
)
@map_service_errors
async def add_bom_line(
    recipe_id: UUID,
    data: BoMLineCreateForRecipe,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> BoMLineRead:
    try:
        line = await recipe_service.add_bom_line(
            db, org_id, recipe_id, data, current_user
        )
    except DuplicateBomLineError as exc:
        raise ConflictException('DUPLICATE_BOM_LINE', str(exc)) from exc
    await db.refresh(line)
    return BoMLineRead.model_validate(line)


@router.patch(
    '/{recipe_id}/bom-lines/{line_id}',
    response_model=BoMLineRead,
    dependencies=[require_permission('maker:manage')],
)
@map_service_errors
async def update_bom_line(
    recipe_id: UUID,
    line_id: UUID,
    data: BoMLineUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> BoMLineRead:
    line = await recipe_service.update_bom_line(
        db, org_id, recipe_id, line_id, data, current_user
    )
    await db.refresh(line)
    return BoMLineRead.model_validate(line)


@router.delete(
    '/{recipe_id}/bom-lines/{line_id}',
    status_code=204,
    dependencies=[require_permission('maker:manage')],
)
@map_service_errors
async def delete_bom_line(
    recipe_id: UUID,
    line_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> None:
    await recipe_service.delete_bom_line(db, org_id, recipe_id, line_id, current_user)


# ---------------------------------------------------------------------------
# Cost lines
# ---------------------------------------------------------------------------


@router.post(
    '/{recipe_id}/cost-lines',
    response_model=RecipeCostLineRead,
    status_code=201,
    dependencies=[require_permission('maker:manage')],
)
@map_service_errors
async def create_cost_line(
    recipe_id: UUID,
    data: RecipeCostLineCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> RecipeCostLineRead:
    cost_line = await recipe_service.create_cost_line(
        db, org_id, recipe_id, data, current_user
    )
    await db.refresh(cost_line)
    return RecipeCostLineRead.model_validate(cost_line)


@router.patch(
    '/{recipe_id}/cost-lines/{line_id}',
    response_model=RecipeCostLineRead,
    dependencies=[require_permission('maker:manage')],
)
@map_service_errors
async def update_cost_line(
    recipe_id: UUID,
    line_id: UUID,
    data: RecipeCostLineUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> RecipeCostLineRead:
    cost_line = await recipe_service.update_cost_line(
        db, org_id, line_id, data, current_user
    )
    await db.refresh(cost_line)
    return RecipeCostLineRead.model_validate(cost_line)


@router.delete(
    '/{recipe_id}/cost-lines/{line_id}',
    status_code=204,
    dependencies=[require_permission('maker:manage')],
)
@map_service_errors
async def delete_cost_line(
    recipe_id: UUID,
    line_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> None:
    await recipe_service.delete_cost_line(db, org_id, line_id, current_user)


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


@router.get(
    '/{recipe_id}/availability',
    response_model=AvailabilityResponse,
)
@map_service_errors
async def get_recipe_availability(
    recipe_id: UUID,
    batches: Decimal | None = Query(None, gt=0),
    location_id: UUID | None = Query(None),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> AvailabilityResponse:
    """Check ingredient availability for producing ``batches`` of a recipe.

    Returns per-ingredient ``{needed, available, shortage, uom, convertible}``
    plus ``max_batches`` (the bottleneck ingredient limits how many full
    batches can be produced from current stock).

    ``location_id`` overrides the org-level ``availability_check_scope``
    (GLOBAL vs PER_LOCATION). When omitted, the scope setting applies;
    PER_LOCATION without a location context falls back to GLOBAL.
    """
    from . import availability_service

    effective_location_id = await availability_service.resolve_check_location(
        db, org_id, requested_location_id=location_id
    )
    result = await availability_service.compute_availability(
        db, org_id, recipe_id, batches=batches, location_id=effective_location_id
    )

    return AvailabilityResponse(
        max_batches=result.max_batches,
        has_shortage=result.has_shortage,
        has_unknown=result.has_unknown,
        ingredients=[
            IngredientAvailabilityItem(
                child_template_id=ing.child_template_id,
                child_template_name=ing.child_template_name,
                needed=ing.needed,
                available=ing.available,
                shortage=ing.shortage,
                uom_symbol=ing.uom_symbol,
                convertible=ing.convertible,
                available_uom_symbol=ing.available_uom_symbol,
                to_buy=ing.to_buy,
                to_buy_uom_symbol=ing.to_buy_uom_symbol,
            )
            for ing in result.ingredients
        ],
    )
