"""A quantity typed on a record that predates its card is still stock that moved.

``Item.quantity`` and the warehouse ledger are two records of one stock, kept
in step by one bridge: a quantity edit on a carded record posts a movement
and a cost layer, and the shelf reads the record. A record whose ``template_id`` is NULL — an import,
a row from before the catalogue — left that bridge on its first line, and left
it silently: the number on the record moved, the shelf it stands on kept the
old one, the movement register stayed empty, and the location's card read
"Nothing has moved through here" beside the changed quantity.

The rule the document doors already follow applies to this door too: the
record's own words resolve — or mint — the card, and the stock the record
already held is posted as an opening before the edit moves any of it, so the
shelf starts from what the record says it holds instead of from a number the
ledger never counted.

An organization that keeps no warehouse modules used to be a different
silence: the bridge wrote nothing there, so nothing was minted behind the
record either. Now every organization keeps the register, and the same edit
gets the same answer whatever modules are on.

Fixtures keep identifiers, not ORM instances: the client writes on its own
connection, and an attribute read off an instance this session has since
committed would go to the database outside a greenlet.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper, ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.stock_move import StockMove, StockMoveReferenceType
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token

#: Modules with one that reads the register: ``documents`` declares that it
#: consumes StockQuant.
_LEDGER_MODULES = ['core', 'items', 'locations', 'categories', 'warehouse', 'stats']

#: The same organization without a single module that consumes StockQuant.
#: It used to keep ``Item.quantity`` as its only stock truth; it keeps the
#: register now, like every other.
_HOME_MODULES = ['core', 'items', 'locations', 'categories']


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


class _Room:
    """One organization, one shelf, and the record the pair is measured on."""

    def __init__(self) -> None:
        self.org_id: UUID
        self.headers: dict[str, str]
        self.shelf_id: UUID
        self.cardless_id: UUID


class _TwinRoom(_Room):
    """A room that also holds the carded twin of the cardless record."""

    def __init__(self) -> None:
        super().__init__()
        self.carded_id: UUID
        self.carded_template_id: UUID


async def _organization_async(
    db: AsyncSession, modules: list[str]
) -> tuple[UUID, dict[str, str]]:
    org = Organization(
        name=f'Ledger {uuid4().hex[:6]}',
        enabled_modules=modules,
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    org_id = org.id

    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'ledger_{uuid4().hex[:8]}@test.com'
    )
    await db.commit()
    return org_id, _auth(user)


async def _shelf_async(db: AsyncSession, org_id: UUID, user_id: UUID) -> UUID:
    storage_type = StorageType(
        name='Shelf',
        type_code=f'SHELF_{uuid4().hex[:6]}',
        behavior_mode='NONE',
    )
    db.add(storage_type)
    await db.flush()
    shelf = StorageLocation(
        name='Shelf A',
        organization_id=org_id,
        storage_type_id=storage_type.id,
        created_by=user_id,
    )
    db.add(shelf)
    await db.commit()
    return shelf.id


async def _cardless_record_async(
    db: AsyncSession,
    org_id: UUID,
    shelf_id: UUID,
    *,
    name: str,
    quantity: Decimal,
) -> UUID:
    """A record the way an import leaves one: a quantity, and no card."""
    item = Item(
        name=name,
        organization_id=org_id,
        storage_location_id=shelf_id,
        quantity=quantity,
    )
    db.add(item)
    await db.commit()
    return item.id


async def _on_shelf_async(
    db: AsyncSession, org_id: UUID, template_id: UUID, location_id: UUID
) -> Decimal:
    """What the shelf holds of the card, as the records' view sums them."""
    quantities = (
        await db.scalars(
            select(ShelfRow.quantity).where(
                ShelfRow.organization_id == org_id,
                ShelfRow.product_template_id == template_id,
                ShelfRow.storage_location_id == location_id,
            )
        )
    ).all()
    return sum(quantities, Decimal('0'))


async def _valued_async(db: AsyncSession, org_id: UUID, template_id: UUID) -> Decimal:
    """What the cost layers say is still held, which the report compares."""
    remaining = (
        await db.scalars(
            select(StockValuationLayer.remaining_qty).where(
                StockValuationLayer.organization_id == org_id,
                StockValuationLayer.product_template_id == template_id,
            )
        )
    ).all()
    return sum(remaining, Decimal('0'))


async def _moves_async(
    db: AsyncSession, org_id: UUID, item_id: UUID
) -> list[StockMove]:
    return list(
        (
            await db.scalars(
                select(StockMove).where(
                    StockMove.organization_id == org_id,
                    StockMove.reference_id == item_id,
                )
            )
        ).all()
    )


async def _template_of_async(db: AsyncSession, item_id: UUID) -> UUID | None:
    return await db.scalar(select(Item.template_id).where(Item.id == item_id))


async def _quantity_of_async(db: AsyncSession, item_id: UUID) -> Decimal:
    return await db.scalar(select(Item.quantity).where(Item.id == item_id))


async def _rows_async(db: AsyncSession, model: type, org_id: UUID) -> int:
    count = await db.scalar(
        select(func.count()).select_from(model).where(model.organization_id == org_id)
    )
    return count or 0


async def _edit_quantity_async(
    client: AsyncClient, room: _Room, item_id: UUID, quantity: int
) -> None:
    response = await client.put(
        f'/api/v1/items/{item_id}',
        headers=room.headers,
        json={'quantity': quantity},
    )
    assert response.status_code == status.HTTP_200_OK, response.text


@pytest.fixture
async def warehouse(
    real_async_db_session: AsyncSession, real_async_client: AsyncClient
) -> _TwinRoom:
    """An organization that keeps a ledger, holding both twins.

    The carded twin is created through the door, so its stock is in the ledger
    the way any carded record's is: a receipt layer and a movement. The
    cardless one is inserted the way an import leaves one. Between the two
    there is the card, and what follows from having it — nothing else.
    """
    db = real_async_db_session
    room = _TwinRoom()
    room.org_id, room.headers = await _organization_async(db, _LEDGER_MODULES)

    user_id = await db.scalar(
        select(User.id).where(User.organization_id == room.org_id)
    )
    room.shelf_id = await _shelf_async(db, room.org_id, user_id)

    created = await real_async_client.post(
        '/api/v1/items',
        headers=room.headers,
        json={
            'name': 'Carded Rye',
            'location_id': str(room.shelf_id),
            'quantity': 10,
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    room.carded_id = UUID(created.json()['id'])
    room.carded_template_id = await _template_of_async(db, room.carded_id)
    assert room.carded_template_id is not None

    room.cardless_id = await _cardless_record_async(
        db,
        room.org_id,
        room.shelf_id,
        name='Cardless Rye',
        quantity=Decimal('10'),
    )
    return room


@pytest.fixture
async def home(real_async_db_session: AsyncSession) -> _Room:
    """An organization that keeps no ledger: no module consumes StockQuant."""
    db = real_async_db_session
    room = _Room()
    room.org_id, room.headers = await _organization_async(db, _HOME_MODULES)

    user_id = await db.scalar(
        select(User.id).where(User.organization_id == room.org_id)
    )
    room.shelf_id = await _shelf_async(db, room.org_id, user_id)
    room.cardless_id = await _cardless_record_async(
        db,
        room.org_id,
        room.shelf_id,
        name='Home Rye',
        quantity=Decimal('10'),
    )
    return room


@pytest.mark.integration
class TestTheEditLeavesTheTraceACardedRecordLeaves:
    """The pair of PUTs differs in one thing: whether the record has a card."""

    async def test_a_cardless_record_moves_the_same_stock_a_carded_one_does(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        warehouse: _TwinRoom,
    ) -> None:
        db = real_async_db_session
        before = {}
        for item_id in (warehouse.carded_id, warehouse.cardless_id):
            before[item_id] = await _moves_async(db, warehouse.org_id, item_id)

        await _edit_quantity_async(
            real_async_client, warehouse, warehouse.carded_id, 13
        )
        await _edit_quantity_async(
            real_async_client, warehouse, warehouse.cardless_id, 13
        )

        adopted = await _template_of_async(db, warehouse.cardless_id)
        assert adopted is not None, (
            'the record is still outside the ledger: template_id is NULL, so no '
            'shelf, movement or cost layer could be keyed to it'
        )

        # The same shelf, by the same amount, for a record whose only
        # difference is that it had no card when the edit arrived.
        assert await _on_shelf_async(
            db, warehouse.org_id, warehouse.carded_template_id, warehouse.shelf_id
        ) == Decimal('13')
        assert await _on_shelf_async(
            db, warehouse.org_id, adopted, warehouse.shelf_id
        ) == Decimal('13')

        # The edit leaves the same movement on both: three in, marked as an
        # edit. The cardless record's shelf also opens with the ten it held
        # before — a movement of its own kind, so the shelf can be traced to
        # the ledger (the report's second pair) without the opening reading
        # as something the edit moved.
        twins = (
            (warehouse.carded_id, before[warehouse.carded_id], []),
            (
                warehouse.cardless_id,
                before[warehouse.cardless_id],
                [(StockMoveReferenceType.OPENING_BALANCE, Decimal('10'))],
            ),
        )
        for item_id, seen, opened in twins:
            given = {move.id for move in seen}
            gained = [
                move
                for move in await _moves_async(db, warehouse.org_id, item_id)
                if move.id not in given
            ]
            assert sorted(
                (move.reference_type, move.quantity) for move in gained
            ) == sorted([*opened, (StockMoveReferenceType.ITEM, Decimal('3'))]), (
                f'movements for {item_id}: the edit leaves one row, the opening '
                'one more'
            )
            for move in gained:
                assert move.to_location_id == warehouse.shelf_id
                assert move.from_location_id is None

        # And the layers behind the shelf agree, which is what the
        # reconciliation report measures: 10 held before the edit + 3 added.
        assert await _valued_async(
            db, warehouse.org_id, warehouse.carded_template_id
        ) == Decimal('13')
        assert await _valued_async(db, warehouse.org_id, adopted) == Decimal('13')


@pytest.mark.integration
class TestAnOrganizationWithoutRegisterModulesKeepsItToo:
    """The same record, the same request, two module sets — one answer."""

    async def test_a_cardless_record_joins_the_register_whatever_the_modules(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        warehouse: _TwinRoom,
        home: _Room,
    ) -> None:
        db = real_async_db_session

        await _edit_quantity_async(
            real_async_client, warehouse, warehouse.cardless_id, 13
        )
        await _edit_quantity_async(real_async_client, home, home.cardless_id, 13)

        # The card is adopted and the edit is registered in both. The home
        # organization used to get no card, no stock, no layer and no
        # movement — its record was its only truth, and a move of it was
        # refused for stock the register had never been told about.
        for room in (warehouse, home):
            assert await _quantity_of_async(db, room.cardless_id) == Decimal('13')
            adopted = await _template_of_async(db, room.cardless_id)
            assert adopted is not None
            assert await _on_shelf_async(
                db, room.org_id, adopted, room.shelf_id
            ) == Decimal('13')
            assert sorted(
                move.reference_type
                for move in await _moves_async(db, room.org_id, room.cardless_id)
            ) == [StockMoveReferenceType.ITEM, StockMoveReferenceType.OPENING_BALANCE]
