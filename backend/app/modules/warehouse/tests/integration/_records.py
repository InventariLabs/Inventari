"""Seed shelf state for document tests the way the application does: a record.

The records are the stock. Here it arrives as a record through the items
service (the path behind ``POST /items``), with its movement and its cost
layer, and a hold lands a reservation row the way an order does.

``sow`` takes an organization object or its id — the fixtures of this
suite name one or the other.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.product_template import ProductTemplate
from tests.integration._shelf import (
    put_on_shelf,
    reserve_for_an_order,
    run_in_async_session,
    shelf_keeper,
)


def sow(
    db: Session,
    engine: AsyncEngine,
    org: Any,
    template: ProductTemplate,
    location_id: uuid.UUID,
    quantity: Decimal | str | int,
    *,
    lot_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    expiry_date: date | None = None,
    backdate_days: int | None = None,
) -> Item:
    """One record of *template* on the shelf, *quantity* of it.

    ``backdate_days`` ages the record's receipt date after the fact, the way
    a fixture pins ``created_at``; ``owner_id`` puts the stock in a partner's
    name (consignment). Returns the record, so a test can name it in a
    document line or age it further.
    """
    db.commit()
    organization_id = org.id if hasattr(org, 'id') else org

    async def _put(session: AsyncSession) -> uuid.UUID:
        keeper = await shelf_keeper(session, organization_id)
        record = await put_on_shelf(
            session,
            keeper,
            template,
            location_id,
            quantity,
            lot_id=lot_id,
            owner_id=owner_id,
            expiry_date=expiry_date,
        )
        return record.id

    record_id = run_in_async_session(engine, _put)
    db.expire_all()
    record = db.get(Item, record_id)
    assert record is not None
    if backdate_days is not None:
        record.created_at = datetime.now(UTC) - timedelta(days=backdate_days)
        db.commit()
    return record


def hold(
    db: Session,
    engine: AsyncEngine,
    template: ProductTemplate,
    location_id: uuid.UUID,
    quantity: Decimal | str,
) -> None:
    """Hold *quantity* of *template* on the shelf the way an order does."""
    db.commit()

    async def _reserve(session: AsyncSession) -> None:
        await reserve_for_an_order(session, template, location_id, quantity)

    run_in_async_session(engine, _reserve)
    db.expire_all()


def shelf_record(
    db: Session,
    organization_id: uuid.UUID,
    template_id: uuid.UUID,
    location_id: uuid.UUID,
) -> Item:
    """A record standing on this shelf — the one a document line can name."""
    record = db.scalars(
        select(Item)
        .where(
            Item.organization_id == organization_id,
            Item.template_id == template_id,
            Item.storage_location_id == location_id,
            Item.is_deleted.is_(False),
        )
        .order_by(Item.created_at)
    ).first()
    assert record is not None, 'no record of this template stands on the shelf'
    return record


def shelf_quant(
    db: Session,
    organization_id: uuid.UUID,
    template_id: uuid.UUID,
    location_id: uuid.UUID,
    *,
    lot_id: uuid.UUID | None = None,
) -> ShelfRow:
    """What the records standing on this shelf hold, as one group.

    ``lot_id`` tells two batches of one product apart — the group's own key.
    """
    conditions = [
        ShelfRow.organization_id == organization_id,
        ShelfRow.product_template_id == template_id,
        ShelfRow.storage_location_id == location_id,
    ]
    if lot_id is not None:
        conditions.append(ShelfRow.lot_id == lot_id)
    return db.scalars(select(ShelfRow).where(*conditions)).one()
