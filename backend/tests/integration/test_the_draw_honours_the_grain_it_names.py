"""The draw takes the grain its caller named, and nothing else.

``take_from_the_records_async`` is the one call every outbound stock move
goes through — a dispatch, a scrap, a production run's ingredient — and its
arguments are a contract: the shelf it names, the batch, the owner, the
removal strategy and whether a held batch may be consumed. The mutation run
in ``docs/STOCK_MUTATION_REPORT.md`` found that the suite before this file
let several of those arguments be dropped or flipped without a test failing:
the draw still moved *some* stock, and no assertion looked at *which*.

Each test below pins one of those arguments on the direct call, so the
question a mutant changes is asked with the smallest fixture that can ask
it. They are not property tests — the generated sequences in
``test_the_stock_posting_invariants_hold.py`` cover the shapes a sequence can
take; these cover the edges a sequence rarely lands on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import StockUnavailableError
from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import LotStatus, StockLot
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.modules.warehouse.models import Document
from app.services._stock_draw import plan_draw_async
from app.services._stock_quant_ops import take_from_the_records_async
from app.services._stock_reservation import reserve_for_document_async
from tests.integration._shelf import put_on_shelf, shelf_keeper

pytestmark = pytest.mark.integration


@dataclass
class DrawScene:
    organization_id: UUID
    user_id: UUID
    template: ProductTemplate
    first: UUID
    second: UUID


@pytest.fixture
async def scene(real_async_db_session: AsyncSession) -> DrawScene:
    db = real_async_db_session
    organization = Organization(
        name=f'Draw edges {uuid4().hex[:8]}',
        enabled_modules=['core', 'items', 'locations', 'categories'],
    )
    db.add(organization)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, organization, email=f'draw-{uuid4().hex[:8]}@example.test'
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
            name=f'Draw shelf {name} {uuid4().hex[:6]}',
            created_by=user.id,
        )
        for name in ('A', 'B')
    )
    template = ProductTemplate(
        name=f'Draw product {uuid4().hex[:8]}',
        organization_id=organization.id,
    )
    db.add_all([first, second])
    db.add(template)
    await db.commit()
    return DrawScene(
        organization_id=organization.id,
        user_id=user.id,
        template=template,
        first=first.id,
        second=second.id,
    )


async def _stock(
    db: AsyncSession,
    scene: DrawScene,
    shelf: UUID,
    quantity: str,
    *,
    lot_id: UUID | None = None,
    owner_id: UUID | None = None,
    expiry_date: date | None = None,
) -> Item:
    keeper = await shelf_keeper(db, scene.organization_id)
    return await put_on_shelf(
        db,
        keeper,
        scene.template,
        shelf,
        quantity,
        lot_id=lot_id,
        owner_id=owner_id,
        expiry_date=expiry_date,
    )


async def _lot(
    db: AsyncSession,
    scene: DrawScene,
    name: str,
    *,
    status: str = LotStatus.ACTIVE.value,
) -> StockLot:
    lot = StockLot(
        organization_id=scene.organization_id,
        product_template_id=scene.template.id,
        name=name,
        status=status,
    )
    db.add(lot)
    await db.flush()
    return lot


async def _take(
    db: AsyncSession,
    scene: DrawScene,
    shelf: UUID | None,
    quantity: str,
    **kwargs: object,
) -> list:
    return await take_from_the_records_async(
        db,
        scene.organization_id,
        scene.template.id,
        shelf,
        Decimal(quantity),
        **kwargs,
    )


async def _on_shelf(
    db: AsyncSession, scene: DrawScene, shelf: UUID, lot_id: UUID | None = None
) -> Decimal:
    return Decimal(
        str(
            await db.scalar(
                select(Item.quantity).where(
                    Item.organization_id == scene.organization_id,
                    Item.template_id == scene.template.id,
                    Item.storage_location_id == shelf,
                    Item.lot_id.is_not_distinct_from(lot_id),
                    Item.is_deleted.is_(False),
                )
            )
            or 0
        )
    )


@pytest.mark.asyncio
async def test_a_draw_of_nothing_takes_nothing(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """Zero on every shelf is an empty draw, not a refusal and not a draw."""
    db = real_async_db_session
    await _stock(db, scene, scene.first, '3')

    taken = await _take(db, scene, None, '0')

    assert taken == []
    assert await _on_shelf(db, scene, scene.first) == Decimal('3')


@pytest.mark.asyncio
async def test_a_draw_of_nothing_asks_nothing_of_the_batch_it_names(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """Zero on every shelf returns before the batch is checked, held or not.

    The early return is the whole answer to an empty every-shelf draw: it
    comes before the named batch's consumable check, so a held batch is not
    refused for a draw that takes none of it.
    """
    db = real_async_db_session
    held = await _lot(db, scene, f'HELD-{uuid4().hex[:6]}', status=LotStatus.HELD.value)
    await _stock(db, scene, scene.first, '3', lot_id=held.id)

    taken = await _take(db, scene, None, '0', lot_id=held.id)

    assert taken == []
    assert await _on_shelf(db, scene, scene.first, held.id) == Decimal('3')


@pytest.mark.asyncio
async def test_a_named_shelf_plans_a_zero_draw_instead_of_short_circuiting_it(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """A zero draw on a named shelf is planned and refused, not answered empty.

    Only the every-shelf call returns before planning when nothing is asked;
    a named shelf goes through the plan, so a stocked shelf that gives
    nothing is the held refusal, no matter how little was asked for.
    """
    db = real_async_db_session
    await _stock(db, scene, scene.first, '3')

    with pytest.raises(StockUnavailableError) as refusal:
        await _take(db, scene, scene.first, '0')

    assert refusal.value.code == StockUnavailableError.ALL_HELD
    assert await _on_shelf(db, scene, scene.first) == Decimal('3')


@pytest.mark.asyncio
async def test_a_draw_of_one_on_every_shelf_takes_that_one(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """The every-shelf draw is for a positive quantity; one is positive."""
    db = real_async_db_session
    await _stock(db, scene, scene.first, '3')
    await _stock(db, scene, scene.second, '3')

    taken = await _take(db, scene, None, '1')

    assert len(taken) == 1
    assert taken[0].consumed == Decimal('1')


@pytest.mark.asyncio
async def test_a_default_draw_leaves_a_held_batch_alone(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """A draw that follows the removal order may not consume a held batch.

    The held batch is the older one, so a strategy that ignored the status
    would take it first; the draw must skip to the active batch.
    """
    db = real_async_db_session
    held = await _lot(db, scene, 'HELD', status=LotStatus.HELD.value)
    active = await _lot(db, scene, 'ACTIVE')
    today = date.today()
    await _stock(
        db,
        scene,
        scene.first,
        '2',
        lot_id=held.id,
        expiry_date=today - timedelta(days=30),
    )
    await _stock(
        db,
        scene,
        scene.second,
        '2',
        lot_id=active.id,
        expiry_date=today + timedelta(days=30),
    )

    taken = await _take(db, scene, None, '1')

    assert [(entry.lot_id, entry.storage_location_id) for entry in taken] == [
        (active.id, scene.second)
    ]
    assert await _on_shelf(db, scene, scene.first, held.id) == Decimal('2')


@pytest.mark.asyncio
async def test_a_held_batch_named_by_the_door_is_refused_unless_it_says_otherwise(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """A dispatch may not consume a recalled batch; a scrap of it may.

    This is the one pair of calls where ``require_active_lot=False`` is the
    difference between "take this batch" and "take anything but this batch":
    the door that names a recalled batch is disposing of it, and the door
    that names it on a dispatch is refused.
    """
    db = real_async_db_session
    held = await _lot(db, scene, 'RECALLED', status=LotStatus.HELD.value)
    await _stock(db, scene, scene.first, '2', lot_id=held.id)

    with pytest.raises(ValueError, match='cannot be consumed'):
        await _take(db, scene, scene.first, '1', lot_id=held.id)

    taken = await _take(
        db, scene, scene.first, '1', lot_id=held.id, require_active_lot=False
    )

    assert taken[0].lot_id == held.id
    assert await _on_shelf(db, scene, scene.first, held.id) == Decimal('1')


@pytest.mark.asyncio
async def test_a_default_draw_does_not_take_another_owners_goods(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """The organization's own goods are the default; another owner's are not.

    The only stock on the shelf belongs to somebody else. A default draw has
    nothing to take and refuses; a draw that names that owner — or asks for
    anyone's goods — finds it.
    """
    db = real_async_db_session
    owner = Partner(
        organization_id=scene.organization_id, name='Consignor', type='SUPPLIER'
    )
    db.add(owner)
    await db.flush()
    await _stock(db, scene, scene.first, '2', owner_id=owner.id)

    with pytest.raises(StockUnavailableError):
        await _take(db, scene, scene.first, '1')

    named = await _take(db, scene, scene.first, '1', owner_id=owner.id)
    assert named[0].owner_id == owner.id

    anyone = await _take(db, scene, scene.first, '1', any_owner=True)
    assert anyone[0].owner_id == owner.id


@pytest.mark.asyncio
async def test_a_draw_naming_a_batch_takes_only_that_batch(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """The batch the caller names is the batch that leaves, and only it.

    Two batches stand on the shelf; the draw names the younger one, and the
    older one is untouched.
    """
    db = real_async_db_session
    older = await _lot(db, scene, 'OLDER')
    named = await _lot(db, scene, 'NAMED')
    today = date.today()
    await _stock(
        db,
        scene,
        scene.first,
        '2',
        lot_id=older.id,
        expiry_date=today + timedelta(days=10),
    )
    await _stock(
        db,
        scene,
        scene.first,
        '2',
        lot_id=named.id,
        expiry_date=today + timedelta(days=30),
    )

    taken = await _take(db, scene, scene.first, '1', lot_id=named.id)

    assert [entry.lot_id for entry in taken] == [named.id]
    assert await _on_shelf(db, scene, scene.first, older.id) == Decimal('2')


@pytest.mark.asyncio
async def test_a_draw_naming_a_batch_holds_to_the_shelf(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """A named shelf is a limit: the same batch on another shelf is not it."""
    db = real_async_db_session
    lot = await _lot(db, scene, 'ELSEWHERE')
    await _stock(db, scene, scene.second, '2', lot_id=lot.id)

    with pytest.raises(StockUnavailableError):
        await _take(db, scene, scene.first, '1', lot_id=lot.id)


@pytest.mark.asyncio
async def test_a_draw_of_exactly_what_the_shelf_holds_takes_it_all(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """A draw that asks for the whole shelf is not "short" by its last unit."""
    db = real_async_db_session
    await _stock(db, scene, scene.first, '2')

    taken = await _take(db, scene, scene.first, '2')

    assert [entry.consumed for entry in taken] == [Decimal('2')]
    assert await _on_shelf(db, scene, scene.first) == Decimal('0')


@pytest.mark.asyncio
async def test_a_foreign_batch_is_not_read_for_its_status(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """Another organization's batch answers like one that is not here.

    The organization scope on the status lookup is not a nicety: without
    it, a caller naming a foreign batch learns its name and its state from
    the refusal. The draw must answer with the stock refusal — nothing of
    this product in that batch — not with the batch's own sentence.
    """
    db = real_async_db_session
    other = Organization(
        name=f'Draw foreign {uuid4().hex[:8]}',
        enabled_modules=['core', 'items', 'locations', 'categories'],
    )
    db.add(other)
    await db.flush()
    foreign_template = ProductTemplate(
        name=f'Foreign product {uuid4().hex[:8]}', organization_id=other.id
    )
    db.add(foreign_template)
    await db.flush()
    foreign_lot = StockLot(
        organization_id=other.id,
        product_template_id=foreign_template.id,
        name='FOREIGN-HELD',
        status=LotStatus.HELD.value,
    )
    db.add(foreign_lot)
    await db.commit()

    with pytest.raises(StockUnavailableError):
        await _take(db, scene, scene.first, '1', lot_id=foreign_lot.id)


@pytest.mark.asyncio
async def test_an_explicit_strategy_wins_over_the_templates(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """The caller's strategy is passed to the plan, not swallowed by it.

    The template says FEFO; the draw says FIFO, so the record filled first
    leaves first even though the other batch expires sooner.
    """
    db = real_async_db_session
    scene.template.removal_strategy = 'FEFO'
    db.add(scene.template)
    await db.commit()
    old_fill = await _lot(db, scene, 'OLD-FILL')
    soon = await _lot(db, scene, 'SOON')
    today = date.today()
    now = datetime.now(UTC)
    await _stock(
        db,
        scene,
        scene.first,
        '2',
        lot_id=old_fill.id,
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
    # The stock was filled in the order above; the removal order reads the
    # record's receipt time, so make the first shelf the older one.
    await db.execute(
        Item.__table__.update()
        .where(Item.template_id == scene.template.id)
        .values(created_at=now)
    )
    await db.execute(
        Item.__table__.update()
        .where(
            Item.template_id == scene.template.id,
            Item.storage_location_id == scene.first,
        )
        .values(created_at=now - timedelta(days=5))
    )
    await db.commit()

    taken = await _take(db, scene, None, '1', removal_strategy='FIFO')

    assert taken[0].lot_id == old_fill.id


@pytest.mark.asyncio
async def test_the_record_a_draw_writes_names_who_took_it_and_on_what(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """The record's history carries the caller and the document behind the draw.

    ``take_from_the_records_async`` states each record through the items
    service, and the service's history row is where "who moved this and on
    whose instruction" lives. Passing no user or no document there left the
    row reading like a quantity somebody typed in by hand.
    """
    db = real_async_db_session
    record = await _stock(db, scene, scene.first, '5')
    document = Document(
        organization_id=scene.organization_id,
        type='OUT',
        number=f'TMP-{uuid4().hex[:8]}',
        created_by=scene.user_id,
    )
    db.add(document)
    await db.commit()

    await _take(
        db,
        scene,
        scene.first,
        '2',
        user_id=scene.user_id,
        source_document_id=document.id,
        history_changes={'reason': 'draw'},
    )
    await db.commit()

    history = (
        await db.scalars(
            select(ItemHistory)
            .where(
                ItemHistory.item_id == record.id,
                ItemHistory.user_id == scene.user_id,
            )
            .order_by(ItemHistory.created_at.desc())
        )
    ).first()
    assert history is not None, 'the draw left no history row naming its caller'
    assert history.source_document_id == document.id
    assert history.changes is not None
    assert history.changes.get('reason') == 'draw'


async def _dated_batches(
    db: AsyncSession, scene: DrawScene
) -> tuple[StockLot, StockLot]:
    """A FEFO template with a soon batch on the second shelf and a far one first.

    They are written in that order and then the far batch is back-dated, so
    FIFO and FEFO answer differently and the plan's choice says which one
    ran.
    """
    scene.template.removal_strategy = 'FEFO'
    db.add(scene.template)
    await db.commit()
    far = await _lot(db, scene, 'FAR')
    soon = await _lot(db, scene, 'SOON')
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
    await db.execute(
        Item.__table__.update()
        .where(Item.template_id == scene.template.id, Item.lot_id == far.id)
        .values(created_at=now - timedelta(days=5))
    )
    await db.commit()
    return far, soon


@pytest.mark.asyncio
async def test_a_plan_with_no_strategy_follows_the_template(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """A caller that names no strategy gets the template's own.

    The taking call always resolves the strategy before it plans, so a plan
    that forgot to is only visible on the public read-only plan — where a
    document asks what it *would* draw before opening the door.
    """
    db = real_async_db_session
    _, soon = await _dated_batches(db, scene)

    plan = await plan_draw_async(
        db, scene.organization_id, scene.template.id, None, Decimal('1')
    )

    assert [draw.lot_id for draw in plan.draws] == [soon.id]


@pytest.mark.asyncio
async def test_a_shelf_holding_only_zero_is_empty_not_held(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """A record at zero is not stock: the shelf reads empty, not "all held"."""
    db = real_async_db_session
    await _stock(db, scene, scene.first, '0')

    plan = await plan_draw_async(
        db,
        scene.organization_id,
        scene.template.id,
        scene.first,
        Decimal('1'),
        strategy='FIFO',
    )

    assert plan.draws == []
    assert plan.free == Decimal('0')
    assert plan.on_shelf is False


@pytest.mark.asyncio
async def test_a_batchless_draw_carries_the_date_the_goods_arrived_with(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """A record with no batch still has the date FEFO ranked it by.

    The date travels through the plan into the movement, so aging and the
    consumption report can tell a dated pack from an undated one.
    """
    db = real_async_db_session
    expiry = date.today() + timedelta(days=10)
    await _stock(db, scene, scene.first, '2', expiry_date=expiry)

    plan = await plan_draw_async(
        db,
        scene.organization_id,
        scene.template.id,
        scene.first,
        Decimal('1'),
        strategy='FIFO',
    )

    assert plan.draws[0].expiry_date == expiry


@pytest.mark.asyncio
async def test_a_document_plan_does_not_count_its_own_hold(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """What a document already holds is free to the document that asks."""
    db = real_async_db_session
    await _stock(db, scene, scene.first, '2')
    document = Document(
        organization_id=scene.organization_id,
        type='OUT',
        number=f'TMP-{uuid4().hex[:8]}',
        created_by=scene.user_id,
    )
    db.add(document)
    await db.commit()
    await reserve_for_document_async(
        db,
        scene.organization_id,
        scene.template.id,
        scene.first,
        Decimal('2'),
        document_id=document.id,
    )
    await db.commit()

    plan = await plan_draw_async(
        db,
        scene.organization_id,
        scene.template.id,
        scene.first,
        Decimal('1'),
        strategy='FIFO',
        except_document_id=document.id,
    )

    assert [draw.quantity for draw in plan.draws] == [Decimal('1')]


@pytest.mark.asyncio
async def test_a_document_plan_still_counts_another_documents_hold(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """Leaving one document's hold out does not leave every hold out.

    The drawer's own promise is not held against it; another document's
    promise on the same shelf still is. Dropping the shelf from the hold
    query would drop them all and offer stock somebody else was promised.
    """
    db = real_async_db_session
    await _stock(db, scene, scene.first, '4')
    asking = Document(
        organization_id=scene.organization_id,
        type='OUT',
        number=f'ASK-{uuid4().hex[:8]}',
        created_by=scene.user_id,
    )
    other = Document(
        organization_id=scene.organization_id,
        type='OUT',
        number=f'OTHER-{uuid4().hex[:8]}',
        created_by=scene.user_id,
    )
    db.add_all([asking, other])
    await db.commit()
    for document in (asking, other):
        await reserve_for_document_async(
            db,
            scene.organization_id,
            scene.template.id,
            scene.first,
            Decimal('2'),
            document_id=document.id,
        )
    await db.commit()

    plan = await plan_draw_async(
        db,
        scene.organization_id,
        scene.template.id,
        scene.first,
        Decimal('3'),
        strategy='FIFO',
        except_document_id=asking.id,
    )

    assert plan.free == Decimal('2')
    assert [draw.quantity for draw in plan.draws] == [Decimal('2')]


@pytest.mark.asyncio
async def test_a_draw_of_exactly_what_every_shelf_holds_takes_it_all(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """The every-shelf door is not "short" when the shelves hold exactly enough.

    Its own check is ``plan.free < quantity``; a draw that asks for the
    whole of what is there is written, not refused as short by nothing.
    """
    db = real_async_db_session
    await _stock(db, scene, scene.first, '2')
    await _stock(db, scene, scene.second, '1')

    taken = await _take(db, scene, None, '3')

    assert sum((entry.consumed for entry in taken), Decimal('0')) == Decimal('3')
    assert await _on_shelf(db, scene, scene.first) == Decimal('0')
    assert await _on_shelf(db, scene, scene.second) == Decimal('0')


@pytest.mark.asyncio
async def test_a_plan_names_the_shelf_every_record_stands_on(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """A draw's plan carries each record's own shelf, not the one asked for.

    The movement off the shelf is written from the plan, because by then the
    record has left that shelf; a plan that names no shelf posts the goods
    as leaving nowhere, and the shelf they really left keeps its number.
    """
    db = real_async_db_session
    await _stock(db, scene, scene.second, '2')

    plan = await plan_draw_async(
        db,
        scene.organization_id,
        scene.template.id,
        None,
        Decimal('1'),
        strategy='FIFO',
    )

    assert [draw.storage_location_id for draw in plan.draws] == [scene.second]


@pytest.mark.asyncio
async def test_a_plan_lifted_for_a_named_batch_needs_the_batch(
    real_async_db_session: AsyncSession, scene: DrawScene
) -> None:
    """Lifting the ACTIVE demand without naming a batch is a programming error.

    ``require_active_lot=False`` is for the door that names the one batch a
    recall is disposing of; a caller that lifts the guard for "anything"
    would hand back stock nobody confirmed, so the plan refuses itself.
    """
    db = real_async_db_session

    with pytest.raises(AssertionError) as refusal:
        await plan_draw_async(
            db,
            scene.organization_id,
            scene.template.id,
            scene.first,
            Decimal('1'),
            strategy='FIFO',
            require_active_lot=False,
        )

    assert str(refusal.value) == (
        'require_active_lot=False is for a draw that names its batch'
    )
