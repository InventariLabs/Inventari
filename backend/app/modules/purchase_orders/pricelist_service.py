"""Partner pricelist service — CRUD + procurement queries.

All functions are async and use ``db.flush()`` only (no commit) for
writes — the caller commits. Reads return ORM rows; the public API
wraps them in DTOs.

Key queries:
- ``list_for_partner_async`` — all offers from a supplier
- ``list_for_template_async`` — all suppliers for a product (price
  comparison)
- ``get_best_price_async`` — lowest unit_price currently valid for a
  template at a given date (optionally filtered by partner type)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictException, ServiceRejectionError
from app.i18n.service import get_current_lang, get_error_message
from app.modules.purchase_orders._service_settings import UNSET, _Unset
from app.modules.purchase_orders.models import PartnerPricelist


async def _reject_a_second_price_for_the_same_offer(
    db: AsyncSession,
    *,
    organization_id: UUID,
    partner_id: UUID,
    product_template_id: UUID,
    valid_from: date,
    valid_to: date | None,
    min_quantity: Decimal | None,
    exclude_id: UUID | None = None,
) -> None:
    """Refuse a second price for one supplier's one offer of one product.

    Two rows differing only in price answered the same question two ways, and
    ``get_best_price_async`` quietly took the cheaper one. So a buyer who
    corrected 62.62 to 55.00 kept getting 29.85 on the order, with nothing on
    the screen to say why. Refused rather than overwritten: which of the two
    is right is a fact about the supplier, not something this code can know.

    Only an exact match is refused — same validity window, same minimum
    quantity. Overlapping windows and different quantity tiers are how a real
    price list is written.
    """
    query = select(PartnerPricelist.id).where(
        PartnerPricelist.organization_id == organization_id,
        PartnerPricelist.partner_id == partner_id,
        PartnerPricelist.product_template_id == product_template_id,
        PartnerPricelist.valid_from == valid_from,
        PartnerPricelist.valid_to.is_(None)
        if valid_to is None
        else PartnerPricelist.valid_to == valid_to,
        PartnerPricelist.min_quantity.is_(None)
        if min_quantity is None
        else PartnerPricelist.min_quantity == min_quantity,
    )
    if exclude_id is not None:
        query = query.where(PartnerPricelist.id != exclude_id)
    if (await db.scalars(query)).first() is not None:
        raise ConflictException(
            code='PRICELIST_DUPLICATE',
            message=get_error_message('pricelist_duplicate', get_current_lang()),
        )


async def create_async(
    db: AsyncSession,
    *,
    organization_id: UUID,
    partner_id: UUID,
    product_template_id: UUID,
    unit_price: Decimal,
    valid_from: date,
    currency: str | None = None,
    uom_id: UUID | None = None,
    min_quantity: Decimal | None = None,
    valid_to: date | None = None,
    notes: str | None = None,
) -> PartnerPricelist:
    """Create a new price list entry. Raises ValueError on invalid input.

    ``currency`` defaults to the organization's own currency — the
       previous ``'USD'`` default was invisible in the form and followed the price
       all the way onto a purchase order line.
    """
    if unit_price <= 0:
        raise ServiceRejectionError(
            'pricelist_unit_price_not_positive', unit_price=unit_price
        )
    if valid_to is not None and valid_to < valid_from:
        raise ServiceRejectionError(
            'pricelist_valid_to_before_valid_from',
            valid_to=valid_to,
            valid_from=valid_from,
        )
    if min_quantity is not None and min_quantity <= 0:
        raise ServiceRejectionError(
            'pricelist_min_quantity_not_positive', min_quantity=min_quantity
        )

    await _reject_a_second_price_for_the_same_offer(
        db,
        organization_id=organization_id,
        partner_id=partner_id,
        product_template_id=product_template_id,
        valid_from=valid_from,
        valid_to=valid_to,
        min_quantity=min_quantity,
    )

    if not currency:
        from app.core.public_api import core_api

        org = await core_api.organizations.get_async(db, organization_id)
        currency = (org.currency if org else None) or 'USD'

    entry = PartnerPricelist(
        organization_id=organization_id,
        partner_id=partner_id,
        product_template_id=product_template_id,
        unit_price=unit_price,
        currency=currency,
        uom_id=uom_id,
        min_quantity=min_quantity,
        valid_from=valid_from,
        valid_to=valid_to,
        notes=notes,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry


async def get_async(
    db: AsyncSession,
    organization_id: UUID,
    entry_id: UUID,
) -> PartnerPricelist | None:
    """Return one entry (with partner + template + uom eagerly loaded)."""
    result = await db.scalars(
        select(PartnerPricelist)
        .options(
            selectinload(PartnerPricelist.partner),
            selectinload(PartnerPricelist.product_template),
            selectinload(PartnerPricelist.uom),
        )
        .where(
            PartnerPricelist.id == entry_id,
            PartnerPricelist.organization_id == organization_id,
        )
    )
    return result.first()


async def list_for_partner_async(
    db: AsyncSession,
    organization_id: UUID,
    partner_id: UUID,
    *,
    active_on: date | None = None,
    product_template_id: UUID | None = None,
) -> list[PartnerPricelist]:
    """All pricelist entries for one supplier.

    Args:
        active_on: If set, only include entries valid on that date.
        product_template_id: Optional template filter.
    """
    stmt = (
        select(PartnerPricelist)
        .options(
            selectinload(PartnerPricelist.partner),
            selectinload(PartnerPricelist.product_template),
            selectinload(PartnerPricelist.uom),
        )
        .where(
            PartnerPricelist.organization_id == organization_id,
            PartnerPricelist.partner_id == partner_id,
        )
    )
    if active_on is not None:
        stmt = stmt.where(
            PartnerPricelist.valid_from <= active_on,
            (PartnerPricelist.valid_to.is_(None))
            | (PartnerPricelist.valid_to >= active_on),
        )
    if product_template_id is not None:
        stmt = stmt.where(PartnerPricelist.product_template_id == product_template_id)
    stmt = stmt.order_by(
        PartnerPricelist.product_template_id,
        PartnerPricelist.unit_price,
        PartnerPricelist.id,
    )
    return list((await db.scalars(stmt)).all())


async def list_for_template_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    *,
    active_on: date | None = None,
) -> list[PartnerPricelist]:
    """All supplier offers for one product (price comparison view).

    Args:
        active_on: If set, only include entries valid on that date.
    """
    stmt = (
        select(PartnerPricelist)
        .options(
            selectinload(PartnerPricelist.partner),
            selectinload(PartnerPricelist.product_template),
            selectinload(PartnerPricelist.uom),
        )
        .where(
            PartnerPricelist.organization_id == organization_id,
            PartnerPricelist.product_template_id == product_template_id,
        )
    )
    if active_on is not None:
        stmt = stmt.where(
            PartnerPricelist.valid_from <= active_on,
            (PartnerPricelist.valid_to.is_(None))
            | (PartnerPricelist.valid_to >= active_on),
        )
    stmt = stmt.order_by(PartnerPricelist.unit_price, PartnerPricelist.id)
    return list((await db.scalars(stmt)).all())


async def get_best_price_async(
    db: AsyncSession,
    organization_id: UUID,
    product_template_id: UUID,
    *,
    on_date: date | None = None,
    quantity: Decimal | None = None,
) -> PartnerPricelist | None:
    """Return the cheapest currently valid offer for a template.

    Used for procurement's current quote. Indicative costs use the registered
    batch provider, which normalizes units and filters to house currency.

    Args:
        on_date: Reference date (defaults to the organization's own day —
            validity windows cut on the org's clock, not the server's).
        quantity: If set, prefer entries whose ``min_quantity`` <= quantity
            (volume-pricing tier). Falls back to entries with no
            min_quantity if no tier matches.
    """
    if on_date is not None:
        reference = on_date
    else:
        from app.core.public_api import core_api

        reference = await core_api.organizations.today_async(db, organization_id)

    stmt = (
        select(PartnerPricelist)
        .options(
            selectinload(PartnerPricelist.partner),
            selectinload(PartnerPricelist.product_template),
            selectinload(PartnerPricelist.uom),
        )
        .where(
            PartnerPricelist.organization_id == organization_id,
            PartnerPricelist.product_template_id == product_template_id,
            PartnerPricelist.valid_from <= reference,
            (PartnerPricelist.valid_to.is_(None))
            | (PartnerPricelist.valid_to >= reference),
        )
        .order_by(PartnerPricelist.unit_price)
    )
    entries = list((await db.scalars(stmt)).all())
    if not entries:
        return None

    if quantity is not None:
        tier_matches = [
            e
            for e in entries
            if e.min_quantity is not None and e.min_quantity <= quantity
        ]
        if tier_matches:
            return tier_matches[0]
    return entries[0]


async def update_async(
    db: AsyncSession,
    *,
    organization_id: UUID,
    entry_id: UUID,
    unit_price: Decimal | None = None,
    currency: str | None = None,
    uom_id: UUID | None | _Unset = UNSET,
    min_quantity: Decimal | None | _Unset = UNSET,
    valid_from: date | None = None,
    valid_to: date | None | _Unset = UNSET,
    notes: str | None | _Unset = UNSET,
) -> PartnerPricelist | None:
    """Patch an existing entry. Returns the updated row or None if missing.

    The clearable columns (uom_id, min_quantity, valid_to, notes — the
    nullable ones) answer three ways: UNSET leaves the column alone,
    ``None`` clears it, a value sets it. An entry with an end date has to
    be able to become open-ended again, and a value read only when not
    None made that impossible. unit_price, currency and valid_from are
    NOT NULL — they keep the two-way reading.
    """
    entry = await db.scalar(
        select(PartnerPricelist).where(
            PartnerPricelist.id == entry_id,
            PartnerPricelist.organization_id == organization_id,
        )
    )
    if entry is None:
        return None

    if unit_price is not None:
        if unit_price <= 0:
            raise ServiceRejectionError(
                'pricelist_unit_price_not_positive', unit_price=unit_price
            )
        entry.unit_price = unit_price
    if currency is not None:
        entry.currency = currency
    if not isinstance(uom_id, _Unset):
        entry.uom_id = uom_id
    if not isinstance(min_quantity, _Unset):
        if min_quantity is not None and min_quantity <= 0:
            raise ServiceRejectionError(
                'pricelist_min_quantity_not_positive', min_quantity=min_quantity
            )
        entry.min_quantity = min_quantity
    if valid_from is not None:
        entry.valid_from = valid_from
    if not isinstance(valid_to, _Unset):
        entry.valid_to = valid_to
    if not isinstance(notes, _Unset):
        entry.notes = notes

    if entry.valid_to is not None and entry.valid_to < entry.valid_from:
        raise ServiceRejectionError(
            'pricelist_valid_to_before_valid_from',
            valid_to=entry.valid_to,
            valid_from=entry.valid_from,
        )

    # An edit can walk an entry onto another one's dates just as easily as a
    # create can land on them.
    await _reject_a_second_price_for_the_same_offer(
        db,
        organization_id=organization_id,
        partner_id=entry.partner_id,
        product_template_id=entry.product_template_id,
        valid_from=entry.valid_from,
        valid_to=entry.valid_to,
        min_quantity=entry.min_quantity,
        exclude_id=entry.id,
    )

    await db.flush()
    await db.refresh(entry)
    return entry


async def delete_async(
    db: AsyncSession,
    organization_id: UUID,
    entry_id: UUID,
) -> bool:
    """Delete an entry. Returns True if a row was removed."""
    entry = await db.scalar(
        select(PartnerPricelist).where(
            PartnerPricelist.id == entry_id,
            PartnerPricelist.organization_id == organization_id,
        )
    )
    if entry is None:
        return False
    await db.delete(entry)
    await db.flush()
    return True
