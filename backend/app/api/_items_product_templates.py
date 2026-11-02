from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Query,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db_facade
from app.core.contracts import (
    AuditAction,
    AuditTargetType,
    ProductTemplateDTO,
    SystemPermission,
    UserContextDTO,
)
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import (
    NotFoundException,
    catalogue_refusal,
)
from app.core.product_template_metadata import get_template_nutrition
from app.core.public_api import core_api
from app.schemas._common import SkuSchemaResponse
from app.schemas.product_template import (
    GeneratedProductCode,
    ProductTemplateClone,
    ProductTemplateCountResponse,
    ProductTemplateCreate,
    ProductTemplateLookupResult,
    ProductTemplateNutritionUpdate,
    ProductTemplateStockResponse,
    SkuSchemaConfig,
)
from app.schemas.product_template import (
    ProductTemplate as ProductTemplateSchema,
)
from app.services._product_template_writes import create_product_template_async
from app.services.audit_service import audit_value
from app.services.items._query_special import get_product_template_or_404
from app.services.items._template import (
    find_template_async,
    update_product_template_nutrition,
)
from app.services.items.low_stock import template_stock_total_async
from app.services.sku_service import SkuService
from app.services.valuation_service import ValuationService

router = APIRouter()


@router.patch(
    '/product-templates/{template_id}/nutrition', response_model=ProductTemplateSchema
)
async def update_template_nutrition(
    template_id: UUID,
    data: ProductTemplateNutritionUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
):
    """Update nutrition_info on a product template owned by the current organization."""
    org_id = require_org(current_user)
    before = await core_api.product_templates.get_async(db, org_id, template_id)
    try:
        template = await db.run_sync(
            lambda s: update_product_template_nutrition(
                s, template_id, org_id, data.nutrition_info
            )
        )
    except ValueError as exc:
        raise NotFoundException('product_template') from exc

    # Written here rather than in the service: that one is sync (the caller
    # hands it a session through ``run_sync``) and the journal writer is
    # async-only. Nutrition is an edit of a template like any other, and
    # this is the only path that makes it.
    was = get_template_nutrition(before) if before is not None else None
    now = get_template_nutrition(template)
    if was != now:
        await core_api.audit_log.log_action_async(
            db,
            organization_id=org_id,
            user_id=current_user.id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.PRODUCT_TEMPLATE,
            target_id=template_id,
            snapshot={
                'name': template.name,
                'before': {'nutrition': audit_value(was)},
                'after': {'nutrition': audit_value(now)},
            },
        )
    return template


def _local_lookup_result(
    *,
    template_id,
    name,
    brand,
    barcode,
    sku,
    uom_id,
    uom_symbol,
    uom_name,
    image_url,
    description,
) -> ProductTemplateLookupResult:
    """One local template as the lookup answer, unit symbols included."""
    return ProductTemplateLookupResult(
        product_template_id=template_id,
        name=name,
        brand=brand,
        barcode=barcode,
        sku=sku,
        uom_id=uom_id,
        uom_symbol=uom_symbol,
        uom_name=uom_name,
        image_url=image_url,
        description=description,
        weight_value=None,
        source='local',
    )


async def _uom_words_async(
    db: AsyncSession, uom_id: UUID | None, organization_id: UUID
) -> tuple[str | None, str | None]:
    """The unit's symbol and its name — what a screen shows beside the value.

    Asked of ``core_api.uoms`` rather than of the model: the API layer reads
    Core tables through the facade (AGENTS.md §3), and the unit's own row is
    no exception. Scoped to the organization: another tenant's unit reads as
    absent, the same as the unit it names never existing.
    """
    if uom_id is None:
        return None, None
    uom = await core_api.uoms.get_async(db, uom_id, organization_id)
    if uom is None:
        return None, None
    return uom.symbol, uom.name


@router.get(
    '/product-templates/lookup', response_model=ProductTemplateLookupResult | None
)
async def lookup_product_template(
    barcode: str | None = Query(None, description='Barcode/EAN to look up'),
    sku: str | None = Query(None, description='SKU to look up'),
    name: str | None = Query(
        None,
        description='Product name to look up — the same matching the create path uses',
    ),
    brand: str | None = Query(None, description='Brand, to narrow a name lookup'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
):
    """
    Look up a product template by barcode, SKU, or the name a form is typing.

    If sku is provided → lookup by SKU (case-insensitive, UPPER).
    If barcode is provided → searches local ProductTemplate, then OFF if enabled.
    If name (and optionally brand) is provided → the same matching the item
    create path does, so a form can show the unit the record will land with
    before it is saved instead of guessing a second answer.

    A product the catalogue does not know answers ``null`` rather than 404:
    it is the normal case for every new product, asked while its name is
    typed, so it is an answer and not an error.
    """
    org_id = require_org(current_user)

    if not barcode and not sku and not name:
        raise catalogue_refusal('barcode_or_sku_required')

    if sku:
        template_dto = await core_api.product_templates.lookup_by_sku_async(
            db, org_id, sku.upper()
        )
        if template_dto:
            symbol, uom_name = await _uom_words_async(db, template_dto.uom_id, org_id)
            return _local_lookup_result(
                template_id=template_dto.id,
                name=template_dto.name,
                brand=template_dto.brand,
                barcode=template_dto.barcode,
                sku=template_dto.sku,
                uom_id=template_dto.uom_id,
                uom_symbol=symbol,
                uom_name=uom_name,
                image_url=template_dto.image_url,
                description=template_dto.description,
            )
        return None

    if barcode:
        from app.core.barcode import normalize_barcode

        normalized = normalize_barcode(barcode) or barcode

        local = await find_template_async(db, org_id, barcode=barcode)
        if local is not None:
            symbol, uom_name = await _uom_words_async(db, local.uom_id, org_id)
            return _local_lookup_result(
                template_id=local.id,
                name=local.name,
                brand=local.brand,
                barcode=local.barcode,
                sku=local.sku,
                uom_id=local.uom_id,
                uom_symbol=symbol,
                uom_name=uom_name,
                image_url=local.image_url,
                description=local.description,
            )

        module_enabled = await core_api.organizations.is_module_enabled_async(
            db, org_id, 'nutrition'
        )
        if module_enabled:
            from app.modules.nutrition.services import off_service

            off_data: dict | None = None
            if db_facade.ProductsSessionLocal is not None:
                import asyncio

                products_db = db_facade.ProductsSessionLocal()
                try:
                    off_data = await asyncio.to_thread(
                        off_service.fetch_product, normalized, products_db
                    )
                finally:
                    products_db.close()

            if off_data:
                return ProductTemplateLookupResult(
                    product_template_id=None,
                    name=off_data.get('name', ''),
                    brand=off_data.get('brand'),
                    barcode=normalized,
                    sku=None,
                    uom_id=None,
                    uom_symbol=None,
                    uom_name=None,
                    image_url=off_data.get('image_url'),
                    description=None,
                    weight_value=None,
                    source='off',
                )

        return None

    assert name is not None
    # The name door answers with the same matching the create path uses, so
    # the unit a form shows and the unit the record lands with are one answer.
    template = await find_template_async(db, org_id, name=name, brand=brand)
    if template is None:
        return None

    symbol, uom_name = await _uom_words_async(db, template.uom_id, org_id)
    return _local_lookup_result(
        template_id=template.id,
        name=template.name,
        brand=template.brand,
        barcode=template.barcode,
        sku=template.sku,
        uom_id=template.uom_id,
        uom_symbol=symbol,
        uom_name=uom_name,
        image_url=template.image_url,
        description=template.description,
    )


@router.get('/product-templates/sku-schema', response_model=dict | None)
async def get_sku_schema(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
):
    """Get SKU naming schema for current organization."""
    org_id = require_org(current_user)
    return await db.run_sync(lambda s: SkuService.get_schema(s, org_id))


@router.put('/product-templates/sku-schema', response_model=SkuSchemaResponse)
async def update_sku_schema(
    data: dict,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ORG_SETTINGS_WRITE),
):
    """Configure SKU naming schema. Requires org:settings:write."""
    # How every SKU in the organization is spelled is a setting, not a record:
    # a member who may add a product may not redefine the naming of the ones
    # already there. The docstring claimed as much long before anything did.
    org_id = require_org(current_user)

    validated = SkuSchemaConfig(**data)
    await db.run_sync(
        lambda s: SkuService.set_schema(s, org_id, validated.model_dump())
    )
    return {'sku_schema': validated.model_dump()}


@router.post('/product-templates/generate-barcode', response_model=GeneratedProductCode)
async def generate_product_barcode(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
):
    """A fresh internal code for the product form's barcode field.

    Nothing is assigned here: the form fills the field and the product's save
    writes it, so the same button serves a new product and an existing one.
    """
    org_id = require_org(current_user)
    return GeneratedProductCode(
        barcode=await SkuService.generate_internal_barcode_async(db, org_id)
    )


@router.post(
    '/product-templates/{template_id}/clone',
    response_model=ProductTemplateSchema,
    status_code=status.HTTP_201_CREATED,
)
async def clone_product_template(
    template_id: UUID,
    data: ProductTemplateClone,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
):
    """Clone a product template.

    Creates a new template with:
    - name and barcode from the request
    - sku auto-generated via SkuService
    - brand, uom, image_url, weight_value copied from the original
    """
    from app.services._product_template_writes import clone_template

    org_id = require_org(current_user)

    try:
        return await clone_template(
            db,
            original_id=template_id,
            new_name=data.name,
            new_barcode=data.barcode,
            organization_id=org_id,
            user_id=current_user.id,
        )
    except ValueError as exc:
        raise NotFoundException('product_template') from exc


@router.get(
    '/product-templates',
    # list-envelope-exception: autocomplete, the first matches capped by limit
    response_model=list[ProductTemplateDTO],
)
async def search_product_templates(
    search: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(10, ge=1, le=50),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
):
    """Search product templates by name (fuzzy ILIKE, org + global).

    Used by the recipe ingredient autocomplete — returns templates
    ranked by relevance, never raising for empty results.
    """
    org_id = require_org(current_user)
    return await core_api.product_templates.search_fuzzy_async(
        db, org_id, search, limit=limit
    )


@router.get(
    '/product-templates/count',
    response_model=ProductTemplateCountResponse,
)
async def count_product_templates(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
):
    """Count templates the org can pick from (org-scoped + global).

       Lets the frontend answer "is the catalog empty" before a form opens —
       the search endpoint needs a 2-char query, so an empty catalog was only
    discoverable inside the picker.
    """
    org_id = require_org(current_user)
    count = await core_api.product_templates.count_for_org_async(db, org_id)
    return ProductTemplateCountResponse(count=count)


@router.get(
    '/product-templates/{template_id}/stock',
    response_model=ProductTemplateStockResponse,
)
async def get_product_template_stock(
    template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
):
    """How much of this product the organization holds on its shelves.

    The threshold on a product is one value for the product, so the screen
    that sets it has to show the quantity it will be measured against.
    Showing the opened record's own quantity instead made the shortcut
    "set the alert to what is here now" set it to a fraction of what is
    there now, on any product kept in more than one place.

    Summed the same way the dashboard tile and the purchasing engine sum —
    internal locations only. See ``app.services.items.low_stock``.
    """
    org_id = require_org(current_user)

    def _symbol_of_an_existing_template(session) -> str | None:
        # The unit is read where the object still has a session: reaching
        # for the lazy relationship after `run_sync` returns raises
        # MissingGreenlet, and the 404 guard has to run either way.
        template = get_product_template_or_404(session, template_id, org_id)
        return template.uom.symbol if template.uom else None

    uom_symbol = await db.run_sync(_symbol_of_an_existing_template)
    total = await template_stock_total_async(db, org_id, template_id)
    return ProductTemplateStockResponse(
        product_template_id=template_id,
        total_quantity=total,
        uom_symbol=uom_symbol,
    )


@router.get(
    '/product-templates/{template_id}',
    response_model=ProductTemplateSchema,
)
async def get_product_template(
    template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_READ),
):
    """Get a product template by ID including this organization's layer-average rate.

    Stock value is FIFO; the rate is the average cost of the cost layers
    still on hand (source fields keep the historical ``avco`` label).

    The rate is computed here rather than read off the row. It used to be a
    cached column on ``product_templates``, and a global template — the whole
    default catalogue — is one row shared by every organization: the number
    there belonged to whichever organization had last taken a delivery, so this
    endpoint handed one organization another's purchase cost.
    """
    org_id = require_org(current_user)
    template = await db.run_sync(
        lambda s: get_product_template_or_404(s, template_id, org_id)
    )
    rate = await ValuationService.get_current_valuation_rate_async(
        db, org_id, template_id
    )
    return ProductTemplateSchema.model_validate(template).model_copy(
        update={'current_valuation_rate': float(rate) if rate is not None else None}
    )


@router.post(
    '/product-templates',
    response_model=ProductTemplateSchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_product_template(
    data: ProductTemplateCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    _: object = require_permission(SystemPermission.ITEMS_WRITE),
):
    """Create a new ProductTemplate.

    Used by seed/test paths that need a template row before items can be
    attached (an item without a template_id stands outside the stock
    register — no group, no movement, no cost layer — until it gets one).
    """
    org_id = require_org(current_user)
    return await create_product_template_async(
        db,
        org_id,
        name=data.name,
        brand=data.brand,
        barcode=data.barcode,
        sku=data.sku,
        description=data.description,
        image_url=data.image_url,
        meta_data=data.meta_data,
        uom_id=data.uom_id,
        weight_value=data.weight_value,
        weight_uom_id=data.weight_uom_id,
        volume_value=data.volume_value,
        volume_uom_id=data.volume_uom_id,
        min_quantity=data.min_quantity,
        user_id=current_user.id,
    )
