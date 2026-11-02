"""A ledger you cannot narrow is an ornament.

The movement history arrived with one filter — the product — and a hard
limit. A warehouse never comes to it with "show me everything": it comes
with "what happened on aisle 2 last week", "where did batch L-7 go", "what
did this delivery note actually move", "who wrote off those six".

So the ledger takes the question apart: product, place (including everything
below it, because a location is a tree), batch, source document, person,
a window of dates, and direction. It answers with a page and a total, not
with the first two hundred rows and no way to know there were more.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token

_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


class _Ledger:
    """The little warehouse every assertion below reads from."""

    def __init__(self) -> None:
        self.org: Organization
        self.user: User
        self.other_user: User
        self.warehouse: StorageLocation
        self.aisle_one: StorageLocation
        self.aisle_two: StorageLocation
        self.yard: StorageLocation
        self.flour: ProductTemplate
        self.sugar: ProductTemplate
        self.lot: StockLot
        self.document_id: UUID
        self.moves: dict[str, StockMove]


async def _location(
    db: AsyncSession,
    org: Organization,
    user: User,
    storage_type: StorageType,
    name: str,
    parent: StorageLocation | None = None,
) -> StorageLocation:
    location = StorageLocation(
        name=name,
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=user.id,
        parent_id=parent.id if parent is not None else None,
    )
    db.add(location)
    await db.flush()
    return location


@pytest.fixture
async def ledger(real_async_db_session: AsyncSession) -> _Ledger:
    db = real_async_db_session
    fixture = _Ledger()

    fixture.org = Organization(
        name=f'Ledger Questions {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations'],
    )
    db.add(fixture.org)
    await db.commit()
    await db.refresh(fixture.org)

    fixture.user = await ModuleTestHelper.create_user_async(
        db, fixture.org, email=f'keeper_{uuid4().hex[:8]}@test.com'
    )
    fixture.other_user = await ModuleTestHelper.create_user_async(
        db, fixture.org, email=f'picker_{uuid4().hex[:8]}@test.com'
    )
    await db.commit()

    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()

    fixture.warehouse = await _location(
        db, fixture.org, fixture.user, storage_type, 'Warehouse'
    )
    fixture.aisle_one = await _location(
        db, fixture.org, fixture.user, storage_type, 'Aisle 1', fixture.warehouse
    )
    fixture.aisle_two = await _location(
        db, fixture.org, fixture.user, storage_type, 'Aisle 2', fixture.warehouse
    )
    fixture.yard = await _location(db, fixture.org, fixture.user, storage_type, 'Yard')

    fixture.flour = ProductTemplate(name='Flour', organization_id=fixture.org.id)
    fixture.sugar = ProductTemplate(name='Sugar', organization_id=fixture.org.id)
    db.add_all([fixture.flour, fixture.sugar])
    await db.flush()

    fixture.lot = StockLot(
        organization_id=fixture.org.id,
        product_template_id=fixture.flour.id,
        name='L-7',
    )
    db.add(fixture.lot)
    await db.flush()

    fixture.document_id = uuid4()
    fixture.moves = {}

    def _move(key: str, **kwargs: object) -> None:
        move = StockMove(organization_id=fixture.org.id, **kwargs)  # type: ignore[arg-type]
        db.add(move)
        fixture.moves[key] = move

    # A delivery lands on aisle 1 ten days ago.
    _move(
        'receipt',
        product_template_id=fixture.flour.id,
        to_location_id=fixture.aisle_one.id,
        quantity=Decimal('10.000'),
        created_by=fixture.user.id,
        completed_at=_NOW - timedelta(days=10),
        reference_type='document',
        reference_id=fixture.document_id,
    )
    # Half of it walks to aisle 2 five days ago.
    _move(
        'transfer',
        product_template_id=fixture.flour.id,
        from_location_id=fixture.aisle_one.id,
        to_location_id=fixture.aisle_two.id,
        quantity=Decimal('4.000'),
        created_by=fixture.user.id,
        completed_at=_NOW - timedelta(days=5),
        reference_type='transfer',
    )
    # Someone else ships two of the batch out yesterday.
    _move(
        'dispatch',
        product_template_id=fixture.flour.id,
        from_location_id=fixture.aisle_two.id,
        quantity=Decimal('2.000'),
        lot_id=fixture.lot.id,
        created_by=fixture.other_user.id,
        completed_at=_NOW - timedelta(days=1),
        reference_type='document',
        reference_id=fixture.document_id,
    )
    # And a different product arrives in the yard, outside the warehouse tree.
    _move(
        'yard_receipt',
        product_template_id=fixture.sugar.id,
        to_location_id=fixture.yard.id,
        quantity=Decimal('7.000'),
        created_by=fixture.other_user.id,
        completed_at=_NOW,
        reference_type='item',
    )

    await db.commit()
    for move in fixture.moves.values():
        await db.refresh(move)
    return fixture


async def _ask(
    client: AsyncClient, ledger: _Ledger, **params: object
) -> tuple[list[dict], int]:
    response = await client.get(
        '/api/v1/stock-moves', params=params, headers=_auth(ledger.user)
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    body = response.json()
    return body['items'], body['total']


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheLedgerAnswersAQuestion:
    async def test_the_whole_ledger_comes_back_with_its_total(
        self, real_async_client: AsyncClient, ledger: _Ledger
    ) -> None:
        rows, total = await _ask(real_async_client, ledger)

        assert total == 4
        assert len(rows) == 4
        # Newest first: the yard receipt is today, the delivery ten days old.
        assert rows[0]['id'] == str(ledger.moves['yard_receipt'].id)
        assert rows[-1]['id'] == str(ledger.moves['receipt'].id)

    async def test_a_place_answers_for_everything_below_it(
        self, real_async_client: AsyncClient, ledger: _Ledger
    ) -> None:
        """A location is a tree; asking about the warehouse means its aisles."""
        rows, total = await _ask(
            real_async_client, ledger, location_id=str(ledger.warehouse.id)
        )

        assert total == 3
        assert {row['id'] for row in rows} == {
            str(ledger.moves['receipt'].id),
            str(ledger.moves['transfer'].id),
            str(ledger.moves['dispatch'].id),
        }

    async def test_one_aisle_answers_for_itself(
        self, real_async_client: AsyncClient, ledger: _Ledger
    ) -> None:
        rows, _ = await _ask(
            real_async_client, ledger, location_id=str(ledger.aisle_two.id)
        )

        # Both the arrival and the departure name aisle 2.
        assert {row['id'] for row in rows} == {
            str(ledger.moves['transfer'].id),
            str(ledger.moves['dispatch'].id),
        }

    @pytest.mark.parametrize(
        ('direction', 'expected'),
        [
            ('in', {'receipt', 'yard_receipt'}),
            ('out', {'dispatch'}),
            ('internal', {'transfer'}),
        ],
    )
    async def test_direction_reads_the_pair_of_locations(
        self,
        real_async_client: AsyncClient,
        ledger: _Ledger,
        direction: str,
        expected: set[str],
    ) -> None:
        rows, _ = await _ask(real_async_client, ledger, direction=direction)

        assert {row['id'] for row in rows} == {
            str(ledger.moves[key].id) for key in expected
        }

    async def test_a_batch_answers_for_its_own_movements(
        self, real_async_client: AsyncClient, ledger: _Ledger
    ) -> None:
        rows, total = await _ask(real_async_client, ledger, lot_id=str(ledger.lot.id))

        assert total == 1
        assert rows[0]['id'] == str(ledger.moves['dispatch'].id)

    async def test_a_document_answers_for_what_it_moved(
        self, real_async_client: AsyncClient, ledger: _Ledger
    ) -> None:
        rows, total = await _ask(
            real_async_client,
            ledger,
            reference_type='document',
            reference_id=str(ledger.document_id),
        )

        assert total == 2
        assert {row['id'] for row in rows} == {
            str(ledger.moves['receipt'].id),
            str(ledger.moves['dispatch'].id),
        }

    async def test_a_person_answers_for_what_they_did(
        self, real_async_client: AsyncClient, ledger: _Ledger
    ) -> None:
        rows, total = await _ask(
            real_async_client, ledger, user_id=str(ledger.other_user.id)
        )

        assert total == 2
        assert {row['id'] for row in rows} == {
            str(ledger.moves['dispatch'].id),
            str(ledger.moves['yard_receipt'].id),
        }

    async def test_a_window_is_read_on_the_date_the_movement_happened(
        self, real_async_client: AsyncClient, ledger: _Ledger
    ) -> None:
        """``completed_at`` is when the goods moved; ``created_at`` is when
        the row was written. A back-dated correction must land in the week it
        belongs to, not the week someone typed it in."""
        rows, total = await _ask(
            real_async_client,
            ledger,
            since=(_NOW - timedelta(days=7)).isoformat(),
            until=(_NOW - timedelta(hours=12)).isoformat(),
        )

        assert total == 2
        assert {row['id'] for row in rows} == {
            str(ledger.moves['transfer'].id),
            str(ledger.moves['dispatch'].id),
        }

    async def test_a_page_says_how_much_it_left_behind(
        self, real_async_client: AsyncClient, ledger: _Ledger
    ) -> None:
        first, total = await _ask(real_async_client, ledger, limit=2, offset=0)
        second, _ = await _ask(real_async_client, ledger, limit=2, offset=2)

        assert total == 4
        assert len(first) == 2
        assert len(second) == 2
        assert {row['id'] for row in first}.isdisjoint({row['id'] for row in second})

    async def test_the_product_filter_still_narrows(
        self, real_async_client: AsyncClient, ledger: _Ledger
    ) -> None:
        rows, total = await _ask(
            real_async_client, ledger, product_template_id=str(ledger.sugar.id)
        )

        assert total == 1
        assert rows[0]['id'] == str(ledger.moves['yard_receipt'].id)
