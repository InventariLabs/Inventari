"""Partner pricelist REST endpoints.

Mounted at:
- POST   /api/v1/purchase-orders/pricelist
- GET    /api/v1/purchase-orders/pricelist/{entry_id}
- PATCH  /api/v1/purchase-orders/pricelist/{entry_id}
- DELETE /api/v1/purchase-orders/pricelist/{entry_id}
- GET    /api/v1/purchase-orders/pricelist/by-partner/{partner_id}
- GET    /api/v1/purchase-orders/pricelist/by-template/{template_id}
- GET    /api/v1/purchase-orders/pricelist/best-for-template/{template_id}

The "by-partner" and "by-template" aliases mirror these endpoints:
- GET /partners/{id}/pricelist
- GET /product-templates/{id}/supplier-prices
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import NotFoundException
from app.core.module_sdk import PaginatedResponse
from app.i18n.service import get_current_lang

from . import pricelist_service
from ._journal import journal_pricelist_change, pricelist_state
from ._service_settings import UNSET
from ._update_canon import refuse_named_nulls
from .schemas import (
    PartnerPricelistCreate,
    PartnerPricelistSchema,
    PartnerPricelistUpdate,
)


def register_pricelist_routes(router: APIRouter) -> None:
    @router.post(
        '/pricelist',
        response_model=PartnerPricelistSchema,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_pricelist_entry(
        data: PartnerPricelistCreate,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> PartnerPricelistSchema:
        entry = await pricelist_service.create_async(
            db,
            organization_id=org_id,
            partner_id=data.partner_id,
            product_template_id=data.product_template_id,
            unit_price=data.unit_price,
            currency=data.currency,
            uom_id=data.uom_id,
            min_quantity=data.min_quantity,
            valid_from=data.valid_from,
            valid_to=data.valid_to,
            notes=data.notes,
        )
        await journal_pricelist_change(
            db,
            org_id,
            current_user.id,
            entry,
            before=None,
            after=pricelist_state(entry),
        )
        return PartnerPricelistSchema.model_validate(entry)

    @router.get(
        '/pricelist/{entry_id}',
        response_model=PartnerPricelistSchema,
    )
    async def get_pricelist_entry(
        entry_id: UUID,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> PartnerPricelistSchema:
        entry = await pricelist_service.get_async(db, org_id, entry_id)
        if not entry:
            raise NotFoundException('pricelist_entry', get_current_lang())
        return PartnerPricelistSchema.model_validate(entry)

    @router.patch(
        '/pricelist/{entry_id}',
        response_model=PartnerPricelistSchema,
    )
    async def update_pricelist_entry(
        entry_id: UUID,
        data: PartnerPricelistUpdate,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> PartnerPricelistSchema:
        # Presence decides: a key the payload names travels to the service
        # even when its value is None (a cleared field), a key it leaves out
        # stays UNSET (leave the column alone). The same contract the
        # settings endpoint speaks. unit_price, currency and valid_from
        # back NOT NULL columns, so naming one with null is refused by
        # name (§2b) instead of reaching the service and no-op'ing.
        refuse_named_nulls(data, {'unit_price', 'currency', 'valid_from'})
        # Read the entry as it is before the service writes to the same row.
        existing = await pricelist_service.get_async(db, org_id, entry_id)
        before = pricelist_state(existing) if existing else None
        entry = await pricelist_service.update_async(
            db,
            organization_id=org_id,
            entry_id=entry_id,
            unit_price=data.unit_price,
            currency=data.currency,
            uom_id=data.uom_id if 'uom_id' in data.model_fields_set else UNSET,
            min_quantity=(
                data.min_quantity if 'min_quantity' in data.model_fields_set else UNSET
            ),
            valid_from=data.valid_from,
            valid_to=(data.valid_to if 'valid_to' in data.model_fields_set else UNSET),
            notes=data.notes if 'notes' in data.model_fields_set else UNSET,
        )
        if entry is None:
            raise NotFoundException('pricelist_entry', get_current_lang())
        await journal_pricelist_change(
            db,
            org_id,
            current_user.id,
            entry,
            before=before,
            after=pricelist_state(entry),
        )
        return PartnerPricelistSchema.model_validate(entry)

    @router.delete(
        '/pricelist/{entry_id}',
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_pricelist_entry(
        entry_id: UUID,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> None:
        existing = await pricelist_service.get_async(db, org_id, entry_id)
        before = pricelist_state(existing) if existing else None
        removed = await pricelist_service.delete_async(db, org_id, entry_id)
        if not removed or existing is None or before is None:
            raise NotFoundException('pricelist_entry', get_current_lang())
        await journal_pricelist_change(
            db, org_id, current_user.id, existing, before=before, after=None
        )

    @router.get(
        '/pricelist/by-partner/{partner_id}',
        response_model=PaginatedResponse[PartnerPricelistSchema],
    )
    async def list_pricelist_by_partner(
        partner_id: UUID,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        active_on: date | None = Query(default=None),
        product_template_id: UUID | None = Query(default=None),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> PaginatedResponse[PartnerPricelistSchema]:
        entries = await pricelist_service.list_for_partner_async(
            db,
            org_id,
            partner_id,
            active_on=active_on,
            product_template_id=product_template_id,
        )
        return PaginatedResponse.from_full_list(
            [PartnerPricelistSchema.model_validate(e) for e in entries],
            offset=offset,
            limit=limit,
        )

    @router.get(
        '/pricelist/by-template/{template_id}',
        response_model=PaginatedResponse[PartnerPricelistSchema],
    )
    async def list_pricelist_by_template(
        template_id: UUID,
        active_on: date | None = Query(default=None),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> PaginatedResponse[PartnerPricelistSchema]:
        entries = await pricelist_service.list_for_template_async(
            db, org_id, template_id, active_on=active_on
        )
        return PaginatedResponse.from_full_list(
            [PartnerPricelistSchema.model_validate(e) for e in entries],
            offset=offset,
            limit=limit,
        )

    @router.get(
        '/pricelist/best-for-template/{template_id}',
        response_model=PartnerPricelistSchema | None,
    )
    async def get_best_pricelist_for_template(
        template_id: UUID,
        on_date: date | None = Query(default=None),
        quantity: Decimal | None = Query(default=None, gt=0),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> PartnerPricelistSchema | None:
        entry = await pricelist_service.get_best_price_async(
            db, org_id, template_id, on_date=on_date, quantity=quantity
        )
        if entry is None:
            return None
        return PartnerPricelistSchema.model_validate(entry)
