"""Availability is read from the records, not from the quant table.

``core_api.stock.list_quants_async`` is where every module asks what stands
on a shelf and what of it is free: the documents' capacity and putaway, the
purchasing engine, the meal planner's shopping list, production's
availability, the stock take's corrections. It used to read ``stock_quants``,
which agreed with the records only because the bridge kept writing both.
It reads ``stock_quants_from_records`` — the records summed per product,
shelf, batch and owner, with the reservation rows beside them — so the
number every one of those readers sees is the records' own. The table is
gone now; every filter a reader asks by is checked against what the records
put on the shelves.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.public_api import core_api
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from tests.integration._shelf import put_on_shelf, reserve_for_an_order, shelf_keeper

pytestmark = pytest.mark.asyncio

_Key = tuple[UUID, UUID, UUID | None, UUID | None]


class _Pantry:
    def __init__(self) -> None:
        self.org: Organization
        self.keeper: UserContextDTO
        self.shelf_a: StorageLocation
        self.shelf_b: StorageLocation
        self.flour: ProductTemplate
        self.sugar: ProductTemplate
        self.batch: StockLot


@pytest.fixture
async def pantry(real_async_db_session: AsyncSession) -> _Pantry:
    """Two products on two shelves, a batch, an order's hold and an empty shelf.

    Flour: two records of one batch on shelf A (one group, two records
    behind it) and a batch-less record on shelf B. Sugar: a record on shelf
    A with an order holding part of it, and a record on shelf B used up.
    """
    db = real_async_db_session
    fixture = _Pantry()
    fixture.org = Organization(
        name=f'Pantry {uuid4().hex[:6]}', enabled_modules=['core']
    )
    db.add(fixture.org)
    await db.flush()
    fixture.keeper = await shelf_keeper(db, fixture.org.id)
    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    fixture.shelf_a, fixture.shelf_b = (
        StorageLocation(
            name=name,
            organization_id=fixture.org.id,
            storage_type_id=storage_type.id,
            created_by=fixture.keeper.id,
        )
        for name in ('Shelf A', 'Shelf B')
    )
    fixture.flour = ProductTemplate(name='Rye flour', organization_id=fixture.org.id)
    fixture.sugar = ProductTemplate(name='Sugar', organization_id=fixture.org.id)
    db.add_all([fixture.shelf_a, fixture.shelf_b, fixture.flour, fixture.sugar])
    await db.flush()
    batch = StockLot(
        organization_id=fixture.org.id, product_template_id=fixture.flour.id, name='L-1'
    )
    db.add(batch)
    await db.flush()
    fixture.batch = batch

    keeper, a, b = fixture.keeper, fixture.shelf_a.id, fixture.shelf_b.id
    await put_on_shelf(db, keeper, fixture.flour, a, 5, lot_id=batch.id)
    await put_on_shelf(db, keeper, fixture.flour, a, 3, lot_id=batch.id)
    await put_on_shelf(db, keeper, fixture.flour, b, 4)
    await put_on_shelf(db, keeper, fixture.sugar, a, 6)
    await reserve_for_an_order(db, fixture.sugar, a, 2)
    used_up = await put_on_shelf(db, keeper, fixture.sugar, b, 1)
    await core_api.items.update_quantity_async(
        db, fixture.org.id, used_up.id, Decimal('0'), user_id=keeper.id
    )
    await db.commit()
    return fixture


def _by_key(rows: Any) -> dict[_Key, tuple[Decimal, Decimal]]:
    """Rows keyed by their group, without the empty ones.

    A record used up to zero still stands, and the view has a row for its
    group at zero; it reads as nothing on the shelf.
    """
    return {
        (
            row.product_template_id,
            row.location_id,
            row.lot_id,
            row.owner_id,
        ): (row.quantity, row.reserved_quantity)
        for row in rows
        if row.quantity or row.reserved_quantity
    }


def _what_the_records_put_there(pantry: _Pantry) -> dict[_Key, tuple[Decimal, Decimal]]:
    """The pantry's groups, on hand and held, as the fixture put them there."""
    a, b = pantry.shelf_a.id, pantry.shelf_b.id
    return {
        (pantry.flour.id, a, pantry.batch.id, None): (Decimal('8'), Decimal('0')),
        (pantry.flour.id, b, None, None): (Decimal('4'), Decimal('0')),
        (pantry.sugar.id, a, None, None): (Decimal('6'), Decimal('2')),
    }


class TestEveryFilterReadsTheRecords:
    @pytest.mark.parametrize(
        'where',
        [
            'everything',
            'one product',
            'a batch of products',
            'one shelf',
            'a batch of shelves',
            'one product on one shelf',
        ],
    )
    async def test_row_for_row_with_the_records(
        self, real_async_db_session: AsyncSession, pantry: _Pantry, where: str
    ) -> None:
        filters: dict[str, Any] = {
            'everything': {},
            'one product': {'product_template_id': pantry.flour.id},
            'a batch of products': {
                'product_template_ids': [pantry.flour.id, pantry.sugar.id]
            },
            'one shelf': {'storage_location_id': pantry.shelf_a.id},
            'a batch of shelves': {'storage_location_ids': [pantry.shelf_b.id]},
            'one product on one shelf': {
                'product_template_id': pantry.sugar.id,
                'storage_location_id': pantry.shelf_a.id,
            },
        }[where]
        db = real_async_db_session

        read = await core_api.stock.list_quants_async(db, pantry.org.id, **filters)

        expected = {
            key: numbers
            for key, numbers in _what_the_records_put_there(pantry).items()
            if key[0] == filters.get('product_template_id', key[0])
            and key[0] in filters.get('product_template_ids', [key[0]])
            and key[1] == filters.get('storage_location_id', key[1])
            and key[1] in filters.get('storage_location_ids', [key[1]])
        }
        assert _by_key(read) == expected
        assert read, 'the pantry holds stock under every filter asked about'

    async def test_the_numbers_are_the_records(
        self, real_async_db_session: AsyncSession, pantry: _Pantry
    ) -> None:
        read = await core_api.stock.list_quants_async(
            real_async_db_session, pantry.org.id, product_template_id=pantry.sugar.id
        )

        # Six on shelf A with two of them held for an order; the record on
        # shelf B was used up.
        (on_a,) = [row for row in read if row.location_id == pantry.shelf_a.id]
        assert (on_a.quantity, on_a.reserved_quantity) == (Decimal('6'), Decimal('2'))
        assert on_a.available_quantity == Decimal('4')
