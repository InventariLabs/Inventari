"""The stock page's numbers are the records'.

``GET /stock-quants`` walks the anchors — one per product on a shelf — for its
rows, sums each group's records (and its reservation rows) beside them, and
takes its count off the records. It used to read its row keys from the quant
table, and a quantity written over the table's head could not change what the
page said; the table is gone (``quantdrop01``), and so is the only shape that
could. What the page says of a group is pinned here.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper, ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.uom import Uom, UomCategory
from app.models.user import User
from app.services.token_service import create_access_token
from tests.integration._holds import hold_async
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


class _Bench:
    """One product, one shelf, and the records a test puts on it."""

    def __init__(self) -> None:
        self.org: Organization
        self.user: User
        self.shelf: StorageLocation
        self.flour: ProductTemplate


@pytest.fixture
async def bench(real_async_db_session: AsyncSession) -> _Bench:
    db = real_async_db_session
    fixture = _Bench()

    fixture.org = Organization(
        name=f'Records shelf {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations'],
    )
    db.add(fixture.org)
    await db.commit()
    await db.refresh(fixture.org)

    fixture.user = await ModuleTestHelper.create_user_async(
        db, fixture.org, email=f'keeper_{uuid4().hex[:8]}@test.com'
    )
    await db.commit()

    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()

    fixture.shelf = StorageLocation(
        name='Aisle',
        organization_id=fixture.org.id,
        storage_type_id=storage_type.id,
        created_by=fixture.user.id,
    )
    db.add(fixture.shelf)
    await db.flush()

    category = UomCategory(
        name=f'Mass {uuid4().hex[:6]}', organization_id=fixture.org.id
    )
    db.add(category)
    await db.flush()
    kilo = Uom(
        organization_id=fixture.org.id,
        name='Kilogram',
        symbol='kg',
        category_id=category.id,
        factor=1.0,
        is_reference=True,
    )
    db.add(kilo)
    await db.flush()

    fixture.flour = ProductTemplate(
        name='Rye flour', organization_id=fixture.org.id, uom_id=kilo.id
    )
    db.add(fixture.flour)
    await db.commit()
    return fixture


def _record(bench: _Bench, quantity: str) -> Item:
    return Item(
        organization_id=bench.org.id,
        name='Rye flour',
        template_id=bench.flour.id,
        storage_location_id=bench.shelf.id,
        quantity=Decimal(quantity),
    )


async def _ask(
    client: AsyncClient, bench: _Bench, **params: object
) -> tuple[list[dict], int]:
    response = await client.get(
        '/api/v1/stock-quants', params=params, headers=_auth(bench.user)
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    body = response.json()
    return body['items'], body['total']


class TestThePageCountsTheRecords:
    async def test_the_shelf_holds_what_the_records_sum(
        self,
        real_async_client: AsyncClient,
        bench: _Bench,
        real_async_db_session: AsyncSession,
    ) -> None:
        db = real_async_db_session
        # Two records of the group: the page prints one row, their sum.
        db.add_all([_record(bench, '4'), _record(bench, '3')])
        await db.run_sync(anchor_pending_records)
        await db.commit()

        rows, total = await _ask(real_async_client, bench)
        assert total == 1
        assert Decimal(str(rows[0]['quantity'])) == Decimal('7')

    async def test_the_promise_is_the_group_own_reservation_rows(
        self,
        real_async_client: AsyncClient,
        bench: _Bench,
        real_async_db_session: AsyncSession,
    ) -> None:
        db = real_async_db_session
        db.add(_record(bench, '10'))
        await db.run_sync(anchor_pending_records)
        await db.commit()
        grain = await db.scalar(
            select(ShelfRow).where(ShelfRow.product_template_id == bench.flour.id)
        )
        assert grain is not None
        await hold_async(db, grain, Decimal('4'))
        await db.commit()

        rows, _ = await _ask(real_async_client, bench)
        assert Decimal(str(rows[0]['reserved_quantity'])) == Decimal('4')
        assert Decimal(str(rows[0]['available_quantity'])) == Decimal('6')

    async def test_an_empty_group_hides_until_asked_for(
        self,
        real_async_client: AsyncClient,
        bench: _Bench,
        real_async_db_session: AsyncSession,
    ) -> None:
        db = real_async_db_session
        # The records carried everything away; a zero record is what is left.
        db.add(_record(bench, '0'))
        await db.run_sync(anchor_pending_records)
        await db.commit()

        # Emptiness is decided off the records: a group none of whose
        # records holds anything is hidden unless asked for.
        rows, total = await _ask(real_async_client, bench)
        assert total == 0
        assert rows == []

        rows, total = await _ask(real_async_client, bench, include_empty='true')
        assert total == 1
        assert Decimal(str(rows[0]['quantity'])) == Decimal('0')
