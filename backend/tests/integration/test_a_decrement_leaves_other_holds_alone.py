"""Taking stock off a shelf must not release somebody else's hold on it.

The quant's `decrement_quant_async` checked `available = quantity - reserved`
and then released `min(reserved, quantity)` without asking whose reservation
that was. So: document A reserves 5 of 10. Production, or another document,
takes 5 — the check passes, because 5 are genuinely free — and the hold A had
was gone while A's `StockReservation` rows still claimed 5. Five units were
left standing unprotected, and the next operation walked off with the stock
reserved for A.

There was never a case for releasing here: the draw refuses to take reserved
stock, so what remains after it still covers every reservation, and a
document letting go of its own runs earlier and separately. The draw is now
``take_from_the_records_async``, and a hold is the reservation rows alone —
the records' view counts them as the group's ``reserved_quantity``, so the
rows and the number cannot say different things; what is asserted is that
the rows are still there and still refuse.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import StockUnavailableError
from app.core.testing import ShelfRow
from app.models.product_template import ProductTemplate
from app.models.stock_reservation import StockReservation
from app.services._stock_quant_ops import take_from_the_records_async
from tests.integration._shelf import put_on_shelf, reserve_for_an_order, shelf_keeper

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

ON_SHELF = Decimal('10')
HELD_BY_A = Decimal('5')
TAKEN_BY_SOMEBODY_ELSE = Decimal('5')


async def _shelf_with_a_hold(
    db: AsyncSession, org_id, location_id
) -> tuple[ProductTemplate, uuid.UUID]:
    """Ten on the shelf, five of them held for document A; returns A's id."""
    template = ProductTemplate(
        organization_id=org_id,
        name=f'Held Product {uuid.uuid4().hex[:6]}',
        sku=f'HP-{uuid.uuid4().hex[:8]}',
    )
    db.add(template)
    await db.flush()

    keeper = await shelf_keeper(db, org_id)
    await put_on_shelf(db, keeper, template, location_id, ON_SHELF)
    # Document A's claim on those five, through the reserving path.
    document_a = await reserve_for_an_order(db, template, location_id, HELD_BY_A)
    await db.flush()
    return template, document_a


async def _group(db: AsyncSession, template: ProductTemplate, location_id) -> ShelfRow:
    row = await db.scalar(
        select(ShelfRow).where(
            ShelfRow.product_template_id == template.id,
            ShelfRow.storage_location_id == location_id,
        )
    )
    assert row is not None
    return row


async def _held_by(db: AsyncSession, document_id: uuid.UUID) -> Decimal:
    total = await db.scalar(
        select(func.coalesce(func.sum(StockReservation.quantity), 0)).where(
            StockReservation.document_id == document_id
        )
    )
    return Decimal(str(total))


async def test_the_hold_survives_a_draw(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
) -> None:
    db = real_async_db_session
    template, document_a = await _shelf_with_a_hold(
        db, async_test_household.id, async_test_storage_location.id
    )

    await take_from_the_records_async(
        db,
        async_test_household.id,
        template.id,
        async_test_storage_location.id,
        TAKEN_BY_SOMEBODY_ELSE,
    )

    group = await _group(db, template, async_test_storage_location.id)
    assert group.quantity == ON_SHELF - TAKEN_BY_SOMEBODY_ELSE
    assert await _held_by(db, document_a) == HELD_BY_A
    assert group.reserved_quantity == HELD_BY_A


async def test_what_is_held_still_cannot_be_taken(
    real_async_db_session: AsyncSession,
    async_test_household,
    async_test_storage_location,
) -> None:
    """The hold is worth keeping only if it still refuses the next request.

    Under the old release the second decrement went through: the first had
    zeroed the quant's reserved number, so the five units A was holding read
    as free.
    """
    db = real_async_db_session
    template, _document_a = await _shelf_with_a_hold(
        db, async_test_household.id, async_test_storage_location.id
    )

    await take_from_the_records_async(
        db,
        async_test_household.id,
        template.id,
        async_test_storage_location.id,
        TAKEN_BY_SOMEBODY_ELSE,
    )

    # The reason, not the sentence: the sentences are translated and name the
    # product and the place, so a substring match on one of them asserts the
    # English wording rather than the refusal.
    with pytest.raises(StockUnavailableError) as refusal:
        await take_from_the_records_async(
            db,
            async_test_household.id,
            template.id,
            async_test_storage_location.id,
            Decimal('1'),
        )

    # Every unit left is held, so the shelf says so rather than "not enough".
    assert refusal.value.code == StockUnavailableError.ALL_HELD
