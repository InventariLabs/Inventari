"""Put stock on a shelf the way the application does: through a record.

The records are the stock: what a shelf holds is what its live records hold,
summed per batch and owner by the records' view. Here the stock arrives as
a record created through the items service, the path behind ``POST /items``:
the record stands in its group's anchor, the ledger gets the movement, the
valuation its layer — the shelf the application builds, and no other.

The synchronous suite has no async session to hand the service. It either
takes the door a person does — ``post_on_shelf``, ``POST /items`` through the
test client — or, for what that door cannot say (a batch, an order's hold),
runs the same helpers in an async session of its own with
``run_in_async_session``.

A reservation is not part of it: ``reserve_for_an_order`` holds stock the
way an order does, with a reservation row the records' view counts.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.core.contracts import UserContextDTO
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.user import User
from app.schemas.item import ItemCreate
from app.services.items import create_item


async def shelf_keeper(db: AsyncSession, organization_id: UUID) -> UserContextDTO:
    """Someone to put stock on the shelves in the name of; nobody signs in as them.

    The record's history and the movement name the user who made them, and
    both refer to a row in ``users``, so the name has to be a real one.
    """
    user = User(
        email=f'shelf-keeper-{uuid4().hex[:8]}@example.test',
        hashed_password='!',
        full_name='Shelf keeper',
        organization_id=organization_id,
        role='user',
    )
    db.add(user)
    await db.flush()
    return UserContextDTO(id=user.id, organization_id=organization_id)


async def put_on_shelf(
    db: AsyncSession,
    keeper: UserContextDTO | User,
    template: ProductTemplate,
    location_id: UUID,
    quantity: Decimal | str | int,
    *,
    lot_id: UUID | None = None,
    owner_id: UUID | None = None,
    expiry_date: date | None = None,
    purchase_price: Decimal | str | None = None,
    currency: str | None = None,
) -> Item:
    """One record of *template* on the shelf, *quantity* of it, in the batch and owner named.

    The record finds its card the way a typed one does — by barcode, then by
    name and brand — so the card is checked afterwards: a test whose product
    shares a name with another card of the organization would otherwise put
    its stock on the wrong product without a word.
    """
    user = UserContextDTO(id=keeper.id, organization_id=keeper.organization_id)
    item = await create_item(
        db,
        ItemCreate(
            name=template.name,
            brand=template.brand,
            barcode=template.barcode,
            location_id=location_id,
            quantity=Decimal(str(quantity)),
            expiry_date=expiry_date,
            purchase_price=(
                Decimal(str(purchase_price)) if purchase_price is not None else None
            ),
            currency=currency,
        ),
        user,
        lot_id=lot_id,
        owner_id=owner_id,
    )
    assert item.template_id == template.id, (
        f'the record for {template.name!r} found another card '
        f'({item.template_id}); give the product a name or a barcode of its own'
    )
    return item


async def reserve_for_an_order(
    db: AsyncSession,
    template: ProductTemplate,
    location_id: UUID,
    quantity: Decimal | str | int,
) -> UUID:
    """Hold *quantity* of *template* on the shelf for an order; returns the order's id.

    An order's hold is a reservation row for its document, the rows the
    records' view counts; the platform refuses a reservation without one.
    """
    from app.core.public_api import core_api

    order_id = uuid4()
    result = await core_api.stock.reserve_for_document_async(
        db,
        template.organization_id,
        template.id,
        location_id,
        Decimal(str(quantity)),
        document_id=order_id,
    )
    assert result.unreserved_quantity == 0, (
        f'the shelf could not hold {quantity} of {template.name!r} for the '
        f'order: {result.message or "short by " + str(result.unreserved_quantity)}'
    )
    return order_id


def post_on_shelf(
    client: Any,
    headers: dict[str, str],
    template: ProductTemplate,
    location_id: UUID,
    quantity: Decimal | str | int,
    *,
    purchase_price: Decimal | str | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    """``put_on_shelf`` for a synchronous test: the record goes in through ``POST /items``.

    The request names the product the way ``put_on_shelf`` does, and the
    card it lands on is checked the same way. Returns the created record.
    """
    body: dict[str, Any] = {
        'name': template.name,
        'brand': template.brand,
        'barcode': template.barcode,
        'location_id': str(location_id),
        'quantity': str(quantity),
    }
    if purchase_price is not None:
        body['purchase_price'] = str(purchase_price)
    if currency is not None:
        body['currency'] = currency
    response = client.post('/api/v1/items', json=body, headers=headers)
    assert response.status_code == 201, response.text
    record = response.json()
    assert record['template_id'] == str(template.id), (
        f'the record for {template.name!r} found another card '
        f'({record["template_id"]}); give the product a name or a barcode of its own'
    )
    return record


def run_in_async_session[T](
    engine: AsyncEngine, work: Callable[[AsyncSession], Awaitable[T]]
) -> T:
    """Run *work* in an async session of its own on *engine*, and commit it.

    For a synchronous test: commit what the test wrote first, so the session
    sees it, and expire the test's session afterwards, so the test sees what
    *work* wrote.
    """

    async def _run() -> T:
        maker = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with maker() as session:
            result = await work(session)
            await session.commit()
            return result

    return asyncio.run(_run())


def anchor_pending_records(session: Session) -> None:
    """Create the anchors of the records *session* is about to write.

    A record with a card names its group's anchor by a foreign key, and the
    application creates the anchor when it locks the group before writing
    (``core_api.stock.lock_async``). A test that adds an ``Item`` straight to
    the session skips that door, so it calls this before the flush — the one
    row per group the door would have added, and nothing else: no lock, no
    quant, no movement. For an async session:
    ``await db.run_sync(anchor_pending_records)``.
    """
    anchor_groups(
        session,
        [
            (obj.organization_id, obj.template_id, obj.storage_location_id)
            for obj in (*session.new, *session.dirty)
            if isinstance(obj, Item)
        ],
    )


def anchor_groups(
    session: Session, groups: Iterable[tuple[UUID, UUID | None, UUID | None]]
) -> None:
    """Create the anchors of *groups* — ``(organization, card, shelf)`` — unless they exist.

    For records written as rows (``insert(Item)`` with a list of values),
    which never pass through the session's pending objects.
    """
    from sqlalchemy.dialects.postgresql import insert

    from app.models.stock_anchor import StockAnchor

    keys = sorted({g for g in groups if g[1] is not None and g[2] is not None}, key=str)
    if not keys:
        return
    with session.no_autoflush:
        session.execute(
            insert(StockAnchor)
            .values(
                [
                    {
                        'organization_id': org,
                        'product_template_id': template,
                        'storage_location_id': location,
                    }
                    for org, template, location in keys
                ]
            )
            .on_conflict_do_nothing(
                index_elements=[
                    'organization_id',
                    'product_template_id',
                    'storage_location_id',
                ]
            )
        )
