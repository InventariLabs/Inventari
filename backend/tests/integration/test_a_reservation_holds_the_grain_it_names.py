"""A reservation holds the grain and the amount its caller named.

``reserve_for_document_async`` is the promise a document makes against
stock: the rows it writes are what a draw must leave behind, so a
reservation that holds nothing when it said it held something — or holds
another shelf, another batch or another amount — is a promise the stock was
never checked against. The mutation run in ``docs/STOCK_MUTATION_REPORT.md``
showed the suite did not ask the call's own arguments back; these tests do,
on the direct call, with the smallest fixture that can ask.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_reservation import StockReservation
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.modules.warehouse.models import Document, DocumentLine
from app.services._stock_reservation import reserve_for_document_async
from tests.integration._shelf import put_on_shelf, shelf_keeper

pytestmark = pytest.mark.integration


@dataclass
class ReserveScene:
    organization_id: UUID
    user_id: UUID
    template: ProductTemplate
    first: UUID
    second: UUID


@pytest.fixture
async def scene(real_async_db_session: AsyncSession) -> ReserveScene:
    db = real_async_db_session
    organization = Organization(
        name=f'Reserve edges {uuid4().hex[:8]}',
        enabled_modules=['core', 'items', 'locations', 'categories'],
    )
    db.add(organization)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, organization, email=f'reserve-{uuid4().hex[:8]}@example.test'
    )
    storage_type = StorageType(
        name='Shelf',
        type_code=f'SHELF_{uuid4().hex[:6]}',
        behavior_mode='NONE',
        organization_id=organization.id,
    )
    db.add(storage_type)
    await db.flush()
    first, second = (
        StorageLocation(
            organization_id=organization.id,
            storage_type_id=storage_type.id,
            name=f'Reserve shelf {name} {uuid4().hex[:6]}',
            created_by=user.id,
        )
        for name in ('A', 'B')
    )
    template = ProductTemplate(
        name=f'Reserve product {uuid4().hex[:8]}',
        organization_id=organization.id,
    )
    db.add_all([first, second])
    db.add(template)
    await db.commit()
    return ReserveScene(
        organization_id=organization.id,
        user_id=user.id,
        template=template,
        first=first.id,
        second=second.id,
    )


async def _stock(
    db: AsyncSession,
    scene: ReserveScene,
    shelf: UUID,
    quantity: str,
    *,
    lot_id: UUID | None = None,
    owner_id: UUID | None = None,
    expiry_date: date | None = None,
) -> None:
    keeper = await shelf_keeper(db, scene.organization_id)
    await put_on_shelf(
        db,
        keeper,
        scene.template,
        shelf,
        quantity,
        lot_id=lot_id,
        owner_id=owner_id,
        expiry_date=expiry_date,
    )


async def _reserve(
    db: AsyncSession,
    scene: ReserveScene,
    shelf: UUID | None,
    quantity: str,
    *,
    document_id: UUID | None = None,
    document_line_id: UUID | None = None,
    **kwargs: object,
) -> object:
    return await reserve_for_document_async(
        db,
        scene.organization_id,
        scene.template.id,
        shelf,
        Decimal(quantity),
        document_id=document_id or uuid4(),
        document_line_id=document_line_id,
        **kwargs,
    )


def _held_total(result: object) -> Decimal:
    return sum(
        (slice_.quantity for slice_ in result.reserved),  # type: ignore[attr-defined]
        Decimal('0'),
    )


@pytest.mark.asyncio
async def test_a_reservation_of_nothing_holds_nothing(
    real_async_db_session: AsyncSession, scene: ReserveScene
) -> None:
    """Zero is answered as success without a row — not as a refusal."""
    db = real_async_db_session
    await _stock(db, scene, scene.first, '2')

    result = await _reserve(db, scene, scene.first, '0')

    assert result.success is True
    assert result.reserved == []
    assert result.unreserved_quantity == Decimal('0')
    assert result.message == 'No quantity to reserve'


@pytest.mark.asyncio
async def test_a_reservation_without_a_document_is_refused(
    real_async_db_session: AsyncSession, scene: ReserveScene
) -> None:
    """A hold without a document is a programming error, and says so."""
    db = real_async_db_session

    with pytest.raises(TypeError) as refusal:
        await reserve_for_document_async(
            db,
            scene.organization_id,
            scene.template.id,
            scene.first,
            Decimal('1'),
            document_id=None,  # type: ignore[arg-type]
        )

    assert str(refusal.value) == (
        'A reservation belongs to a document; none was named.'
    )


@pytest.mark.asyncio
async def test_a_reservation_of_one_holds_one(
    real_async_db_session: AsyncSession, scene: ReserveScene
) -> None:
    """One is a real hold, whatever a zero-quantity early return might think."""
    db = real_async_db_session
    await _stock(db, scene, scene.first, '2')

    result = await _reserve(db, scene, scene.first, '1')

    assert result.success is True
    assert result.message == ''
    assert _held_total(result) == Decimal('1')


@pytest.mark.asyncio
async def test_a_reservation_of_exactly_what_is_free_holds_it(
    real_async_db_session: AsyncSession, scene: ReserveScene
) -> None:
    """Asking for the whole shelf is not a shortfall by its last unit."""
    db = real_async_db_session
    await _stock(db, scene, scene.first, '2')

    result = await _reserve(db, scene, scene.first, '2')

    assert result.success is True
    assert _held_total(result) == Decimal('2')


@pytest.mark.asyncio
async def test_a_short_reservation_holds_nothing_and_names_the_shortfall(
    real_async_db_session: AsyncSession, scene: ReserveScene
) -> None:
    """A promise that cannot be kept in full is not made in part."""
    db = real_async_db_session
    await _stock(db, scene, scene.first, '2')

    result = await _reserve(db, scene, scene.first, '3')

    assert result.success is False
    assert result.reserved == []
    assert result.unreserved_quantity == Decimal('1')
    assert result.message == (
        f'Could not reserve {result.unreserved_quantity} of 3 for product '
        f'{scene.template.id}'
    )


@pytest.mark.asyncio
async def test_a_refused_reservation_is_logged_with_its_reason(
    real_async_db_session: AsyncSession,
    scene: ReserveScene,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The shortfall that reaches the screen also reaches the log, in words."""
    db = real_async_db_session
    await _stock(db, scene, scene.first, '2')

    with caplog.at_level(logging.WARNING, logger='app.services._stock_reservation'):
        result = await _reserve(db, scene, scene.first, '3')

    assert result.success is False
    assert caplog.records[-1].getMessage() == (
        f'Reservation refused, nothing held: {result.message}'
    )


@pytest.mark.asyncio
async def test_a_reservation_holds_only_the_shelf_it_names(
    real_async_db_session: AsyncSession, scene: ReserveScene
) -> None:
    """Stock on another shelf is not this shelf's to promise."""
    db = real_async_db_session
    await _stock(db, scene, scene.second, '2')

    result = await _reserve(db, scene, scene.first, '1')

    assert result.success is False
    assert result.reserved == []


@pytest.mark.asyncio
async def test_a_reservation_follows_the_strategy_it_is_given(
    real_async_db_session: AsyncSession, scene: ReserveScene
) -> None:
    """The default FIFO holds the record filled first, not the FEFO batch.

    The template says FEFO; the call does not say otherwise, so the
    signature's FIFO is what the hold follows. Mutating the strategy handed
    to the plan would quietly reserve the batch that expires sooner.
    """
    db = real_async_db_session
    scene.template.removal_strategy = 'FEFO'
    db.add(scene.template)
    await db.commit()
    far = StockLot(
        organization_id=scene.organization_id,
        product_template_id=scene.template.id,
        name='FAR',
    )
    soon = StockLot(
        organization_id=scene.organization_id,
        product_template_id=scene.template.id,
        name='SOON',
    )
    db.add_all([far, soon])
    await db.flush()
    today = date.today()
    now = datetime.now(UTC)
    await _stock(
        db,
        scene,
        scene.first,
        '2',
        lot_id=far.id,
        expiry_date=today + timedelta(days=90),
    )
    await _stock(
        db,
        scene,
        scene.second,
        '2',
        lot_id=soon.id,
        expiry_date=today + timedelta(days=2),
    )
    # The removal order reads the record's receipt time: the FEFO batch is
    # filled later, so FIFO and FEFO answer differently.
    await db.execute(
        Item.__table__.update()
        .where(Item.template_id == scene.template.id, Item.lot_id == far.id)
        .values(created_at=now - timedelta(days=5))
    )
    await db.commit()

    result = await _reserve(db, scene, None, '1')

    assert [slice_.lot_id for slice_ in result.reserved] == [far.id]


@pytest.mark.asyncio
async def test_a_reservation_row_names_the_line_it_was_made_for(
    real_async_db_session: AsyncSession, scene: ReserveScene
) -> None:
    """The row keeps the line, so a line's hold can be told from its siblings'."""
    db = real_async_db_session
    await _stock(db, scene, scene.first, '2')
    document = Document(
        organization_id=scene.organization_id,
        type='OUT',
        number='TEST/1',
        created_by=scene.user_id,
    )
    line = DocumentLine(
        product_template_id=scene.template.id,
        quantity=Decimal('1'),
        expected_quantity=Decimal('1'),
        done_quantity=Decimal('0'),
        line_number=1,
    )
    document.lines.append(line)
    db.add(document)
    await db.commit()

    await _reserve(
        db,
        scene,
        scene.first,
        '1',
        document_id=document.id,
        document_line_id=line.id,
    )

    row = (
        await db.scalars(
            select(StockReservation).where(StockReservation.document_id == document.id)
        )
    ).one()
    assert row.document_line_id == line.id


@pytest.mark.asyncio
async def test_a_reservation_names_the_owner_whose_goods_it_holds(
    real_async_db_session: AsyncSession, scene: ReserveScene
) -> None:
    """A consignor's stock is held under the consignor, not the organization."""
    db = real_async_db_session
    owner = Partner(
        organization_id=scene.organization_id, name='Consignor', type='SUPPLIER'
    )
    db.add(owner)
    await db.flush()
    await _stock(db, scene, scene.first, '2', owner_id=owner.id)

    result = await _reserve(db, scene, scene.first, '1')

    assert result.success is True
    assert [slice_.owner_id for slice_ in result.reserved] == [owner.id]
