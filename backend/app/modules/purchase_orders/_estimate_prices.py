"""Organization-currency supplier prices per stock unit, in one batch.

An offer quoted per kilogram cannot price a gram as a kilogram. Incompatible
units and foreign currency cannot answer a bare house-currency rate. Compare
the normalized rates, rather than the numbers printed in unlike offer units.
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.public_api import core_api


async def supplier_rates_async(
    db: AsyncSession, organization_id: UUID, ids: list[UUID], currency: str | None
) -> dict[UUID, Decimal]:
    """Return the cheapest usable current offer per requested stock unit.

    Like the existing quantity-free best-offer query, this is an indicative
    quote, not a procurement commitment to a volume tier.
    """
    if not ids or not currency:
        return {}
    if not await core_api.organizations.is_module_enabled_async(
        db, organization_id, 'purchase_orders'
    ):
        return {}
    from .models import PartnerPricelist

    today = await core_api.organizations.today_async(db, organization_id)
    offers = await db.scalars(
        select(PartnerPricelist)
        .options(selectinload(PartnerPricelist.product_template))
        .where(
            PartnerPricelist.organization_id == organization_id,
            PartnerPricelist.product_template_id.in_(ids),
            PartnerPricelist.currency == currency,
            PartnerPricelist.unit_price > 0,
            PartnerPricelist.valid_from <= today,
            PartnerPricelist.valid_to.is_(None) | (PartnerPricelist.valid_to >= today),
        )
    )
    uoms = {
        uom.id: uom
        for uom in await core_api.uoms.list_for_org_async(db, organization_id)
    }
    rates: dict[UUID, Decimal] = {}
    for offer in offers:
        stock_uom_id = offer.product_template.uom_id
        units = Decimal('1')
        if offer.uom_id is not None:
            units, ok = core_api.uoms.convert_quantity(
                units, uoms.get(stock_uom_id), uoms.get(offer.uom_id)
            )
            if not ok:
                continue
        price = offer.unit_price * units
        tid = offer.product_template_id
        if tid not in rates or price < rates[tid]:
            rates[tid] = price
    return rates
