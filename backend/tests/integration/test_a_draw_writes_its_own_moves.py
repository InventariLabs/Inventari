"""The outbound draw writes the movements of what it takes, in the same call.

``take_from_the_records_async`` plans the draw from the records under the
anchors, writes each record it names and mirrors the quants beside them. The
movements were left to the caller, which wrote them one by one from the
breakdown the draw handed back — the record's number and the register's row
in two calls, the shape the stock synchronization rule refuses, because two
calls are two chances to write one. The draw writes them now, one per batch
it took: a movement names no record, so two records of one batch leaving
together are that batch leaving, and a recall follows the batch.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import StockUnavailableError
from app.core.public_api import core_api
from app.models.stock_move import StockMove, StockMoveReferenceType

from ._core_api_helpers import make_template
from ._shelf import put_on_shelf

pytestmark = pytest.mark.integration


class _Shelf:
    """Batch A in two records (three, then four) and batch B in one (five), on one shelf."""

    def __init__(self, db, org_id, user, location_id, template_id, lot_a, lot_b):
        self.db = db
        self.org_id = org_id
        self.user = user
        self.location_id = location_id
        self.template_id = template_id
        self.lot_a = lot_a
        self.lot_b = lot_b
        self.document_id = uuid4()

    async def take(self, quantity: str, lot_id: UUID | None = None):
        return await core_api.stock.take_from_the_records_async(
            self.db,
            self.org_id,
            self.template_id,
            self.location_id,
            Decimal(quantity),
            lot_id=lot_id,
            user_id=self.user.id,
            reference_type=StockMoveReferenceType.DOCUMENT,
            reference_id=self.document_id,
        )

    async def moves(self) -> list[StockMove]:
        return list(
            await self.db.scalars(
                select(StockMove).where(
                    StockMove.organization_id == self.org_id,
                    StockMove.reference_id == self.document_id,
                )
            )
        )


@pytest.fixture
async def shelf(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
    async_test_user,
) -> _Shelf:
    db = real_async_db_session
    org_id = async_test_household.id
    template = await db.run_sync(lambda s: make_template(s, org_id))
    lot_a, lot_b = [
        await core_api.stock.get_or_create_lot_async(
            db=db, organization_id=org_id, product_template_id=template.id, name=name
        )
        for name in ('A', 'B')
    ]
    for quantity, lot_id in (('3', lot_a), ('4', lot_a), ('5', lot_b)):
        await put_on_shelf(
            db,
            async_test_user,
            template,
            async_test_storage_location.id,
            Decimal(quantity),
            lot_id=lot_id,
        )
    await db.commit()
    return _Shelf(
        db,
        org_id,
        async_test_user,
        async_test_storage_location.id,
        template.id,
        lot_a,
        lot_b,
    )


async def test_a_draw_writes_one_move_per_batch_it_took(shelf: _Shelf) -> None:
    """Three records, two batches, one call: two movements, each the batch's whole take."""
    taken = await shelf.take('12')

    moves = await shelf.moves()
    assert sorted((m.lot_id, m.quantity) for m in moves) == sorted(
        [(shelf.lot_a, Decimal('7')), (shelf.lot_b, Decimal('5'))]
    )
    for move in moves:
        assert move.from_location_id == shelf.location_id
        assert move.to_location_id is None
        assert move.product_template_id == shelf.template_id
        assert move.reference_type == StockMoveReferenceType.DOCUMENT
        assert move.created_by == shelf.user.id
    # What it hands back is what it wrote, so a caller has nothing left to add.
    assert sorted((t.lot_id, t.consumed) for t in taken) == sorted(
        (m.lot_id, m.quantity) for m in moves
    )


async def test_a_named_batch_leaves_as_that_batch(shelf: _Shelf) -> None:
    await shelf.take('5', lot_id=shelf.lot_a)

    assert [(m.lot_id, m.quantity) for m in await shelf.moves()] == [
        (shelf.lot_a, Decimal('5'))
    ]


async def test_a_refused_draw_writes_no_move(shelf: _Shelf) -> None:
    with pytest.raises(StockUnavailableError):
        await shelf.take('13')

    assert await shelf.moves() == []
