from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.contracts.dtos import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import NotFoundException, ServiceRejectionError
from app.core.module_sdk import PaginatedResponse
from app.core.modules import require_module
from app.core.public_api import core_api
from app.i18n.service import get_current_lang

from .tax_rate_assignment_service import (
    country_rate_offer,
    list_category_assignments_async,
    name_rate_async,
    product_assignment_async,
)
from .tax_rate_schemas import (
    CategoryTaxRateOut,
    CountryRateOffer,
    CountryRatesOut,
    NameTaxRate,
    ProductTaxRateOut,
    TaxRateCreate,
    TaxRateOut,
    TaxRateUpdate,
    TaxSummaryLine,
    TaxSummaryResponse,
)
from .tax_rate_service import (
    compute_tax_summary,
    create_tax_rate,
    delete_tax_rate,
    get_tax_rate,
    list_tax_rates,
    update_tax_rate,
)

router = APIRouter(dependencies=[Depends(require_module('warehouse'))])


@router.get('/tax-rates', response_model=PaginatedResponse[TaxRateOut])
async def list_rates(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    rates = await list_tax_rates(db, org_id)
    return PaginatedResponse.from_full_list(rates, offset=offset, limit=limit)


@router.post('/tax-rates', response_model=TaxRateOut, status_code=201)
async def create_rate(
    data: TaxRateCreate,
    _: None = require_permission('warehouse:manage'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    return await create_tax_rate(
        db,
        org_id,
        data.name,
        data.rate,
        user_id=current_user.id,
        **data.model_dump(exclude={'name', 'rate'}),
    )


async def _org_country(db: AsyncSession, org_id: UUID) -> str | None:
    org = await core_api.organizations.get_async(db, org_id)
    return org.country if org else None


async def _log_named_rate(
    db: AsyncSession,
    current_user: UserContextDTO,
    target_type: AuditTargetType,
    target_id: UUID,
    rate: Decimal | None,
) -> None:
    """The rate goods take is part of their catalogue entry: it is journalled.

    The number, not the row's id: the journal is read by a person, and a
    rate renamed or deleted later must not change what the entry says.
    """
    await core_api.audit_log.log_action_async(
        db,
        organization_id=require_org(current_user),
        user_id=current_user.id,
        action=AuditAction.UPDATE,
        target_type=target_type,
        target_id=target_id,
        snapshot={'tax_rate': str(rate) if rate is not None else None},
    )


async def _check_rate(
    db: AsyncSession, org_id: UUID, rate_id: UUID | None
) -> Decimal | None:
    """The rate named, refused when it is not the organization's."""
    if rate_id is None:
        return None
    tr = await get_tax_rate(db, org_id, rate_id)
    if tr is None:
        raise NotFoundException('tax_rate', get_current_lang())
    return tr.rate


@router.get('/tax-rates/country', response_model=CountryRatesOut)
async def country_rates(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> CountryRatesOut:
    """The standard and reduced rates the organization's country knows."""
    country = await _org_country(db, require_org(current_user))
    return CountryRatesOut(
        country=country,
        rates=[
            CountryRateOffer(name=name, rate=rate, is_standard=is_standard)
            for name, rate, is_standard in country_rate_offer(country)
        ],
    )


@router.get(
    '/tax-rates/categories', response_model=PaginatedResponse[CategoryTaxRateOut]
)
async def list_category_rates(
    limit: int = Query(200, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """Every category that names a rate."""
    rows = await list_category_assignments_async(db, require_org(current_user))
    return PaginatedResponse.from_full_list(
        [CategoryTaxRateOut(category_id=c, tax_rate_id=r) for c, r in rows],
        offset=offset,
        limit=limit,
    )


@router.put('/tax-rates/categories/{category_id}', response_model=NameTaxRate)
async def name_category_rate(
    category_id: UUID,
    data: NameTaxRate,
    _: None = require_permission('warehouse:manage'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> NameTaxRate:
    """The rate the category's goods take; ``null`` clears it."""
    org_id = require_org(current_user)
    if await core_api.categories.get_by_id_async(db, org_id, category_id) is None:
        raise NotFoundException('category', get_current_lang())
    rate = await _check_rate(db, org_id, data.tax_rate_id)
    await name_rate_async(db, org_id, data.tax_rate_id, category_id=category_id)
    await _log_named_rate(db, current_user, AuditTargetType.CATEGORY, category_id, rate)
    return data


async def _product_rate_out(
    db: AsyncSession, org_id: UUID, template_id: UUID
) -> ProductTaxRateOut:
    if not await core_api.product_templates.exists_for_org_async(
        db, org_id, template_id
    ):
        raise NotFoundException('product_template', get_current_lang())
    own, by_category = await product_assignment_async(db, org_id, template_id)
    return ProductTaxRateOut(
        product_template_id=template_id,
        tax_rate_id=own,
        category_tax_rate_id=by_category,
    )


@router.get('/tax-rates/products/{template_id}', response_model=ProductTaxRateOut)
async def get_product_rate(
    template_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ProductTaxRateOut:
    """The rate the product names, and the one its category would give it."""
    return await _product_rate_out(db, require_org(current_user), template_id)


@router.put('/tax-rates/products/{template_id}', response_model=ProductTaxRateOut)
async def name_product_rate(
    template_id: UUID,
    data: NameTaxRate,
    _: None = require_permission('warehouse:manage'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> ProductTaxRateOut:
    """The rate the product's goods take over its category's; ``null`` clears it."""
    org_id = require_org(current_user)
    await _product_rate_out(db, org_id, template_id)
    rate = await _check_rate(db, org_id, data.tax_rate_id)
    await name_rate_async(db, org_id, data.tax_rate_id, product_template_id=template_id)
    await _log_named_rate(
        db,
        current_user,
        AuditTargetType.PRODUCT_TEMPLATE,
        template_id,
        rate,
    )
    return await _product_rate_out(db, org_id, template_id)


@router.get('/tax-rates/{rate_id}', response_model=TaxRateOut)
async def get_rate(
    rate_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    tr = await get_tax_rate(db, org_id, rate_id)
    if not tr:
        raise NotFoundException('tax_rate', get_current_lang())
    return tr


@router.put('/tax-rates/{rate_id}', response_model=TaxRateOut)
async def update_rate(
    rate_id: UUID,
    data: TaxRateUpdate,
    _: None = require_permission('warehouse:manage'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    updates = data.model_dump(exclude_none=True)
    if not updates:
        raise ServiceRejectionError('no_fields_to_update')
    tr = await update_tax_rate(db, org_id, rate_id, user_id=current_user.id, **updates)
    if not tr:
        raise NotFoundException('tax_rate', get_current_lang())
    return tr


@router.delete('/tax-rates/{rate_id}', status_code=204)
async def delete_rate(
    rate_id: UUID,
    _: None = require_permission('warehouse:manage'),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> None:
    org_id = require_org(current_user)
    if not await delete_tax_rate(db, org_id, rate_id, user_id=current_user.id):
        raise NotFoundException('tax_rate', get_current_lang())


@router.get('/tax-summary', response_model=TaxSummaryResponse)
async def tax_summary(
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> TaxSummaryResponse:
    org_id = require_org(current_user)
    org = await core_api.organizations.get_async(db, org_id)

    summary_lines = await compute_tax_summary(db, org_id)

    total_net = Decimal('0.00')
    total_tax = Decimal('0.00')
    total_gross = Decimal('0.00')
    line_items: list[TaxSummaryLine] = []
    for row in summary_lines:
        line_items.append(
            TaxSummaryLine(
                tax_rate=row['tax_rate'],
                tax_code=None,
                net=row['net'],
                tax=row['tax'],
                gross=row['gross'],
                line_count=row['line_count'],
            )
        )
        total_net += row['net']
        total_tax += row['tax']
        total_gross += row['gross']

    return TaxSummaryResponse(
        org_tax_id=getattr(org, 'tax_id', None) if org else None,
        org_country=getattr(org, 'country', None) if org else None,
        currency=org.currency if org else None,
        lines=line_items,
        total_net=total_net,
        total_tax=total_tax,
        total_gross=total_gross,
    )
