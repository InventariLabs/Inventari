"""Random stock posting sequences keep the record and the ledger telling one story.

Stock correctness is the figure the product sells, so the posting path is
held to invariants rather than to examples: a generated sequence of
receipts, issues, transfers, counts, reservations and undos, applied
through the same doors a person uses, must leave

- every shelf holding exactly what the movement ledger says it received
  less what it gave up — per product and per location;
- no shelf, and no record, below zero (no organization setting allows a
  negative shelf today; a setting that ever does must teach this test);
- no grain promising out more than it holds (``reserved <= on hand``);
- a shelf whose undo ran exactly as it stood before the undone post.

The undo half is a property of its own: the state before the post is
captured, one more document is posted, undone, and the shelf and the
ledger must both read the captured numbers again. What the undo posts
stays in the ledger — the reversal is a movement too — so the *net* is
the number compared.

The budget is fixed (``MAX_EXAMPLES`` below): the suite pays for twenty
short sequences per property, not for an open-ended search. A found
counterexample is kept, shrunk, as an explicit ``@example`` beside the
strategy that would have found it again — Hypothesis' own database is
not committed, so the regression case has to live in the file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.modules.warehouse._document_workflow_transitions import post_new_document
from app.modules.warehouse.document_correction_service import undo_document
from app.modules.warehouse.document_profile_service import create_default_profile
from app.modules.warehouse.schemas import DocumentCreate, DocumentLineCreate
from app.services._stock_draw import _held_by_grain_async, records_by_grain_async
from app.services._stock_reservation import release_for_document_async

pytestmark = pytest.mark.integration

#: The fixed example budget. Twenty sequences of at most six operations keep
#: both properties under a few seconds each on the real database; raising it
#: widens the search, not the run time the suite may spend by accident.
#:
#: The mutation run (`make mutate-stock`) lowers this to three: there the
#: property is a smoke test for "does any test notice this mutant", and every
#: extra example multiplies the run by the number of mutants. The gate and CI
#: never set the variable, so they always pay for the full twenty.
MAX_EXAMPLES = int(os.environ.get('STOCK_PROPERTY_EXAMPLES', '20'))

#: Small whole numbers, so the shrinker can walk a failing sequence down to
#: one receipt, one issue and one undo without handing back fractions the
#: shelf's three places would have to round.
QUANTITY = st.integers(min_value=1, max_value=8)
COUNTED = st.integers(min_value=0, max_value=8)
SHELF = st.integers(min_value=0, max_value=1)
BATCH = st.sampled_from([None, 'L-1', 'L-2'])

#: The fixed budget is small enough that the shrinker must not be charged for
#: Hypothesis' own timing guesses: the database does the work, not the test.
PROPERTY_SETTINGS = {
    'max_examples': MAX_EXAMPLES,
    'deadline': None,
    'suppress_health_check': [
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
    ],
}


# ---------------------------------------------------------------------------
# The operations a sequence is made of
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Receive:
    """A one-step receipt: goods arrive on a shelf, in a batch or none."""

    shelf: int
    batch: str | None
    quantity: int


@dataclass(frozen=True)
class Issue:
    """A one-step issue: goods leave a shelf through a document."""

    shelf: int
    quantity: int


@dataclass(frozen=True)
class Move:
    """A one-step internal transfer: a record changes shelves."""

    source: int
    target: int
    quantity: int


@dataclass(frozen=True)
class Count:
    """A stock take's write: the shelf is stated at what was counted."""

    shelf: int
    counted: int


@dataclass(frozen=True)
class Reserve:
    """A document's promise against a shelf."""

    shelf: int
    quantity: int


@dataclass(frozen=True)
class Release:
    """The promise a document made is given back."""


@dataclass(frozen=True)
class Undo:
    """The last post is reversed, when nothing has moved its stock since."""


OPERATION = st.one_of(
    st.builds(Receive, shelf=SHELF, batch=BATCH, quantity=QUANTITY),
    st.builds(Issue, shelf=SHELF, quantity=QUANTITY),
    st.builds(Move, source=SHELF, target=SHELF, quantity=QUANTITY),
    st.builds(Count, shelf=SHELF, counted=COUNTED),
    st.builds(Reserve, shelf=SHELF, quantity=QUANTITY),
    st.builds(Release),
    st.builds(Undo),
)


def _sequence() -> Any:
    """A receipt first, then the operations a person might reach for.

    The first receipt is not a special case the shrinking keeps: without
    stock on the shelf every later step is a refusal, and a sequence of
    refusals finds nothing the posting path can get wrong.
    """
    return st.tuples(
        st.builds(Receive, shelf=SHELF, batch=BATCH, quantity=QUANTITY),
        st.lists(OPERATION, min_size=0, max_size=5),
    )


# ---------------------------------------------------------------------------
# The world one sequence runs in
# ---------------------------------------------------------------------------


@dataclass
class World:
    """The organization every example of this test posts into."""

    organization_id: UUID
    user_id: UUID
    storage_type_id: UUID


@dataclass
class Scene:
    """The product and the two shelves one generated sequence moves stock on."""

    world: World
    template_id: UUID
    shelves: tuple[UUID, UUID]
    #: The document posted and not yet undone, with the state it was posted
    #: against: the undo step reverses only the one no later stock write has
    #: touched.
    undoable: tuple[UUID, dict[Any, Decimal], dict[Any, Decimal]] | None = None
    #: Holds a document of this sequence made, so a release has something to
    #: release and the test does not leak rows into the next example.
    reservations: list[UUID] = field(default_factory=list)


@pytest.fixture
async def world(real_async_db_session: AsyncSession) -> World:
    db = real_async_db_session
    created = Organization(
        name=f'Posting invariants {uuid4().hex[:8]}',
        enabled_modules=['core', 'items', 'locations', 'categories', 'warehouse'],
    )
    db.add(created)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, created, email=f'posting-{uuid4().hex[:8]}@example.test'
    )
    storage_type = StorageType(
        name='Shelf',
        type_code=f'SHELF_{uuid4().hex[:6]}',
        behavior_mode='NONE',
        organization_id=created.id,
    )
    db.add(storage_type)
    await db.commit()
    # The warehouse module creates its profile on first use and commits while
    # doing it, which would close the savepoint every generated post runs in.
    # The profile is the organization's, not the post's: create it once here,
    # outside any example.
    await create_default_profile(db, created.id)
    return World(created.id, user.id, storage_type.id)


async def _new_scene(db: AsyncSession, world: World) -> Scene:
    """A fresh product and two fresh shelves, so examples cannot meet.

    One Hypothesis test runs its examples against one database (the fixture
    is set up once); a product and two shelves of their own per example keep
    the ledger invariant of one example blind to another's rows.
    """
    template = ProductTemplate(
        name=f'Invariant product {uuid4().hex[:8]}',
        organization_id=world.organization_id,
    )
    db.add(template)
    await db.flush()
    shelves = [
        StorageLocation(
            organization_id=world.organization_id,
            storage_type_id=world.storage_type_id,
            name=f'Invariant shelf {name} {uuid4().hex[:6]}',
            created_by=world.user_id,
        )
        for name in ('A', 'B')
    ]
    db.add_all(shelves)
    await db.commit()
    return Scene(
        world=world,
        template_id=template.id,
        shelves=(shelves[0].id, shelves[1].id),
    )


# ---------------------------------------------------------------------------
# Reading the two numbers the invariants compare
# ---------------------------------------------------------------------------


async def _record_ids(db: AsyncSession, scene: Scene, shelf: int) -> list[UUID]:
    return list(
        (
            await db.scalars(
                select(Item.id)
                .where(
                    Item.organization_id == scene.world.organization_id,
                    Item.template_id == scene.template_id,
                    Item.storage_location_id == scene.shelves[shelf],
                    Item.is_deleted.is_(False),
                    Item.quantity > 0,
                )
                .order_by(Item.id)
            )
        ).all()
    )


async def _shelf_total(db: AsyncSession, scene: Scene, shelf: UUID) -> Decimal:
    return Decimal(
        str(
            await db.scalar(
                select(func.coalesce(func.sum(Item.quantity), 0)).where(
                    Item.organization_id == scene.world.organization_id,
                    Item.template_id == scene.template_id,
                    Item.storage_location_id == shelf,
                    Item.is_deleted.is_(False),
                )
            )
        )
    )


async def _ledger_net(db: AsyncSession, scene: Scene, shelf: UUID) -> Decimal:
    async def total(*where: Any) -> Decimal:
        return Decimal(
            str(
                await db.scalar(
                    select(func.coalesce(func.sum(StockMove.quantity), 0)).where(
                        StockMove.organization_id == scene.world.organization_id,
                        StockMove.product_template_id == scene.template_id,
                        StockMove.state == 'done',
                        *where,
                    )
                )
            )
        )

    arrived = await total(StockMove.to_location_id == shelf)
    left = await total(StockMove.from_location_id == shelf)
    return arrived - left


async def _snapshot(
    db: AsyncSession, scene: Scene
) -> tuple[dict[Any, Decimal], dict[Any, Decimal]]:
    """What the records hold per shelf, and what the ledger says per shelf.

    The compared state is the one the criterion names: stock per product and
    location. It is deliberately not the grain split: the shelf and the
    ledger are what must agree here, and the batch split an undo restores
    is pinned by a test of its own
    (``test_undoing_an_issue_returns_each_batch``).

    Zero-valued entries are dropped, so a shelf a completed post left at
    zero reads the same as one it never touched.
    """
    held = {shelf: await _shelf_total(db, scene, shelf) for shelf in scene.shelves}
    ledger = {shelf: await _ledger_net(db, scene, shelf) for shelf in scene.shelves}
    return (
        {shelf: quantity for shelf, quantity in held.items() if quantity != 0},
        {shelf: quantity for shelf, quantity in ledger.items() if quantity != 0},
    )


async def _assert_invariants(db: AsyncSession, scene: Scene) -> None:
    """The four promises the posting path makes, checked on the state it wrote.

    Every check is scoped to the product and the two shelves of this
    example, so another example's rows in the same organization cannot move
    a number this one compares.
    """
    grains = await records_by_grain_async(
        db, scene.world.organization_id, scene.template_id, None
    )

    # No shelf and no record below zero. There is no organization setting
    # that permits negative stock today; if one is ever introduced, its
    # exception belongs here, named, and not as a blanket allowance.
    for grain, quantity in grains.items():
        assert quantity >= 0, f'{grain} holds {quantity}'

    # What a shelf holds is what the ledger says it received less what it
    # gave up — per product and per location.
    for shelf in scene.shelves:
        on_hand = await _shelf_total(db, scene, shelf)
        moved = await _ledger_net(db, scene, shelf)
        assert on_hand == moved, (
            f'the ledger does not explain shelf {shelf}: '
            f'on hand={on_hand}, moved={moved}'
        )

    # A grain never promises more than it holds.
    held = await _held_by_grain_async(
        db, scene.world.organization_id, scene.template_id, None
    )
    for grain, promised in held.items():
        assert promised <= grains.get(grain, Decimal('0')), (
            f'{grain} promises {promised} out of {grains.get(grain, 0)}'
        )


# ---------------------------------------------------------------------------
# Running one operation
# ---------------------------------------------------------------------------


async def _attempt(db: AsyncSession, work: Any) -> Any:
    """Run a door that may refuse, and leave the session as it found it.

    A refusal is a normal answer here — an issue of more than the shelf
    holds is exactly the case the non-negative invariant is about — but a
    service that wrote half its work before raising would poison the next
    operation, so every attempt is its own savepoint.
    """
    savepoint = await db.begin_nested()
    try:
        result = await work()
        await savepoint.commit()
        return result
    except ValueError:
        await savepoint.rollback()
        return None


async def _post(db: AsyncSession, scene: Scene, data: DocumentCreate) -> Any:
    return await post_new_document(
        db, scene.world.organization_id, data, scene.world.user_id
    )


async def _receive(
    db: AsyncSession,
    scene: Scene,
    op: Receive,
    before: tuple[dict[Any, Decimal], dict[Any, Decimal]],
) -> bool:
    doc = await _attempt(
        db,
        lambda: _post(
            db,
            scene,
            DocumentCreate(
                type='IN',
                target_location_id=scene.shelves[op.shelf],
                lines=[
                    DocumentLineCreate(
                        product_template_id=scene.template_id,
                        expected_quantity=Decimal(op.quantity),
                        unit_price=Decimal('1.00'),
                        batch_number=op.batch,
                    )
                ],
            ),
        ),
    )
    if doc is None:
        return False
    scene.undoable = (doc.id, *before)
    return True


async def _issue(
    db: AsyncSession,
    scene: Scene,
    op: Issue,
    before: tuple[dict[Any, Decimal], dict[Any, Decimal]],
) -> bool:
    records = await _record_ids(db, scene, op.shelf)
    if not records:
        return False
    doc = await _attempt(
        db,
        lambda: _post(
            db,
            scene,
            DocumentCreate(
                type='OUT',
                source_location_id=scene.shelves[op.shelf],
                lines=[
                    DocumentLineCreate(
                        item_id=records[0],
                        product_template_id=scene.template_id,
                        expected_quantity=Decimal(op.quantity),
                        unit_price=Decimal('1.00'),
                    )
                ],
            ),
        ),
    )
    if doc is None:
        return False
    scene.undoable = (doc.id, *before)
    return True


async def _move(
    db: AsyncSession,
    scene: Scene,
    op: Move,
    before: tuple[dict[Any, Decimal], dict[Any, Decimal]],
) -> bool:
    if op.source == op.target:
        return False
    records = await _record_ids(db, scene, op.source)
    if not records:
        return False
    doc = await _attempt(
        db,
        lambda: _post(
            db,
            scene,
            DocumentCreate(
                type='INT',
                source_location_id=scene.shelves[op.source],
                target_location_id=scene.shelves[op.target],
                lines=[
                    DocumentLineCreate(
                        item_id=records[0],
                        product_template_id=scene.template_id,
                        expected_quantity=Decimal(op.quantity),
                    )
                ],
            ),
        ),
    )
    if doc is None:
        return False
    scene.undoable = (doc.id, *before)
    return True


async def _count(db: AsyncSession, scene: Scene, op: Count) -> None:
    records = await _record_ids(db, scene, op.shelf)
    if not records:
        return
    await _attempt(
        db,
        lambda: core_api.items.update_quantity_async(
            db,
            scene.world.organization_id,
            records[0],
            Decimal(op.counted),
            user_id=scene.world.user_id,
            move_reference_type='adjustment',
            move_reference_id=uuid4(),
        ),
    )
    # A count states the shelf, so it invalidates the undo of a post whose
    # stock it has just restated.
    scene.undoable = None


async def _reserve(db: AsyncSession, scene: Scene, op: Reserve) -> None:
    document_id = uuid4()
    result = await _attempt(
        db,
        lambda: core_api.stock.reserve_for_document_async(
            db,
            scene.world.organization_id,
            scene.template_id,
            scene.shelves[op.shelf],
            Decimal(op.quantity),
            'FIFO',
            document_id=document_id,
        ),
    )
    if result is not None and result.success:
        scene.reservations.append(document_id)


async def _release(db: AsyncSession, scene: Scene) -> None:
    if not scene.reservations:
        return
    document_id = scene.reservations.pop()
    await release_for_document_async(db, scene.world.organization_id, document_id)


async def _undo(db: AsyncSession, scene: Scene) -> None:
    if scene.undoable is None:
        return
    document_id, before_grains, before_ledger = scene.undoable
    scene.undoable = None
    reversal = await _attempt(
        db,
        lambda: undo_document(
            db, scene.world.organization_id, document_id, scene.world.user_id
        ),
    )
    if reversal is None:
        # The undo is allowed to refuse: a hold or a movement since the post
        # is the refusal its own tests pin. What it must never do is half
        # restore the books, which the invariant check below still measures.
        return
    grains, ledger = await _snapshot(db, scene)
    assert grains == before_grains, (
        f'undo of {document_id} left the records at {grains}, not {before_grains}'
    )
    assert ledger == before_ledger, (
        f'undo of {document_id} left the ledger at {ledger}, not {before_ledger}'
    )


async def _apply(db: AsyncSession, scene: Scene, op: Any) -> None:
    """Apply one generated operation, capturing the state before a post."""
    if isinstance(op, Receive):
        await _receive(db, scene, op, await _snapshot(db, scene))
    elif isinstance(op, Issue):
        await _issue(db, scene, op, await _snapshot(db, scene))
    elif isinstance(op, Move):
        await _move(db, scene, op, await _snapshot(db, scene))
    elif isinstance(op, Count):
        await _count(db, scene, op)
    elif isinstance(op, Reserve):
        await _reserve(db, scene, op)
    elif isinstance(op, Release):
        await _release(db, scene)
    elif isinstance(op, Undo):
        await _undo(db, scene)
    else:  # pragma: no cover — the strategy above is the only source
        raise AssertionError(f'unknown operation {op!r}')


async def _run_sequence(db: AsyncSession, scene: Scene, sequence: Any) -> None:
    first, rest = sequence
    for op in (first, *rest):
        await _apply(db, scene, op)
        await _assert_invariants(db, scene)


# ---------------------------------------------------------------------------
# The properties
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@given(sequence=_sequence())
@settings(**PROPERTY_SETTINGS)
@example(
    sequence=(
        Receive(shelf=0, batch=None, quantity=1),
        [Issue(shelf=0, quantity=1), Undo()],
    )
)
@example(
    sequence=(
        Receive(shelf=0, batch='L-1', quantity=2),
        [
            Move(source=0, target=1, quantity=1),
            Reserve(shelf=1, quantity=1),
            Release(),
            Undo(),
        ],
    )
)
async def test_random_posting_sequences_keep_the_books(
    real_async_db_session: AsyncSession, world: World, sequence: Any
) -> None:
    """Any order of the stock doors leaves the records and the ledger agreed."""
    db = real_async_db_session
    scene = await _new_scene(db, world)
    await _run_sequence(db, scene, sequence)


@pytest.mark.asyncio
@given(
    setup=st.lists(OPERATION, min_size=1, max_size=3),
    final=st.one_of(
        st.builds(Receive, shelf=SHELF, batch=BATCH, quantity=QUANTITY),
        st.builds(Issue, shelf=SHELF, quantity=QUANTITY),
        st.builds(Move, source=SHELF, target=SHELF, quantity=QUANTITY),
    ),
)
@settings(**PROPERTY_SETTINGS)
@example(
    setup=[Receive(shelf=0, batch=None, quantity=3)],
    final=Issue(shelf=0, quantity=2),
)
@example(
    # Found by the mutation run's clean-test pass: an issue of two draws one
    # from each batch on the shelf. The shelf and the ledger must read
    # exactly as they did before once it is undone.
    setup=[
        Receive(shelf=1, batch=None, quantity=1),
        Receive(shelf=1, batch='L-1', quantity=1),
        Receive(shelf=0, batch=None, quantity=1),
    ],
    final=Issue(shelf=1, quantity=2),
)
async def test_undo_restores_the_state_before_the_undone_post(
    real_async_db_session: AsyncSession,
    world: World,
    setup: list[Any],
    final: Any,
) -> None:
    """The post is undone back to the numbers the shelf and the ledger held.

    The final post is the last stock write of the example, so the undo has
    nothing standing between it and the state it reverses. A transfer is
    undone through the return door, a receipt and an issue through a
    reversing correction; all three must put the same numbers back.
    """
    db = real_async_db_session
    scene = await _new_scene(db, world)
    # The setup may refuse (an issue more than the shelf holds); that is the
    # sequence finding its own edge, and the final post is what is measured.
    for op in setup:
        await _apply(db, scene, op)
    before = await _snapshot(db, scene)
    # Only the final post is the one this property undoes: a setup post is
    # part of the state being restored to, not the post under test.
    scene.undoable = None
    if isinstance(final, Receive):
        await _receive(db, scene, final, before)
    elif isinstance(final, Issue):
        await _issue(db, scene, final, before)
    elif isinstance(final, Move):
        await _move(db, scene, final, before)
    else:  # pragma: no cover — the strategy above is the only source
        raise AssertionError(f'unknown final operation {final!r}')
    # A final issue or move can find no stock to take; that is the generated
    # sequence's own edge, not a failure of the property. The strategy is
    # small enough that discarding it costs little.
    assume(scene.undoable is not None)
    await _undo(db, scene)
    after = await _snapshot(db, scene)
    assert after == before, f'undo of {final!r} left the books at {after}, not {before}'
    await _assert_invariants(db, scene)
