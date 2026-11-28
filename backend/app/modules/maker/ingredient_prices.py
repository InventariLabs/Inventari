"""Prices typed once for ingredients the records do not price.

The maker module owns the table; Core owns the order the estimate policy
asks its sources, and reaches this one through
``app.core.cost_estimates.register_typed_price_provider`` — the same shape
as a supplier's quotes, so an installation without the maker module keeps
estimating from layers alone.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import acquire_advisory_lock
from app.core.money import quantise
from app.core.public_api import core_api

from .models import MakerIngredientPrice


async def typed_rates_async(
    db: AsyncSession, organization_id: UUID, template_ids: list[UUID]
) -> dict[UUID, Decimal]:
    """Batch-read the organization's typed prices, keyed by product."""
    if not template_ids:
        return {}
    rows = await db.execute(
        select(
            MakerIngredientPrice.product_template_id,
            MakerIngredientPrice.unit_price,
        ).where(
            MakerIngredientPrice.organization_id == organization_id,
            MakerIngredientPrice.product_template_id.in_(template_ids),
        )
    )
    rates: dict[UUID, Decimal] = {}
    for template_id, price in rows.all():
        rates[template_id] = price
    return rates


def order_line_price(price: Decimal | None) -> Decimal | None:
    """A price as a purchase order line keeps it: to two decimals.

    A price per a small unit can round away to nothing; the line then carries
    no price for the buyer to fill in, since zero would order it as free.
    """
    if price is None:
        return None
    kept = quantise(price)
    return None if price and not kept else kept


async def get_typed_price_async(
    db: AsyncSession, organization_id: UUID, template_id: UUID
) -> Decimal | None:
    """The typed price of one product, or None when nobody typed one."""
    rates = await typed_rates_async(db, organization_id, [template_id])
    return rates.get(template_id)


async def set_typed_price_async(
    db: AsyncSession,
    organization_id: UUID,
    template_id: UUID,
    unit_price: Decimal | None,
) -> Decimal | None:
    """Set the product's typed price, or clear it when ``None``.

    A product from another organization's catalogue is refused before any
    row is written: the price belongs to the organization asking, but the
    product it names must be one that organization can see.
    """
    template = await core_api.product_templates.get_async(
        db, organization_id, template_id
    )
    if template is None:
        from app.core.exceptions import EntityNotFoundError

        raise EntityNotFoundError('product_template', str(template_id))

    # Two people typing a price for one product at the same time is a lost
    # update, not a duplicate row: serialise on the key the unique constraint
    # names, exactly as the formula's own writes do.
    await acquire_advisory_lock(db, f'maker_price:{organization_id}:{template_id}')
    if unit_price is None:
        await db.execute(
            delete(MakerIngredientPrice).where(
                MakerIngredientPrice.organization_id == organization_id,
                MakerIngredientPrice.product_template_id == template_id,
            )
        )
        return None

    row = (
        await db.execute(
            select(MakerIngredientPrice)
            .where(
                MakerIngredientPrice.organization_id == organization_id,
                MakerIngredientPrice.product_template_id == template_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        row = MakerIngredientPrice(
            organization_id=organization_id,
            product_template_id=template_id,
            unit_price=unit_price,
        )
        db.add(row)
    else:
        row.unit_price = unit_price
    return unit_price
