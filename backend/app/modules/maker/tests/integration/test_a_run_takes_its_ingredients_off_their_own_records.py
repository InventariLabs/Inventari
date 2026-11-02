"""A production run takes its ingredients off the records the draw named.

The draw is planned from the records and names them: which record gives how
much, in the removal order, each with the batch and owner its stock is in
(``plan_draw_async``). What comes off is therefore decided before anything is
written, and the records that go down are the records the draw named — the
draw is what the run ate.

Two earlier shapes of this file held that claim loosely. A mirror summed the
draw per shelf and took the sum off the shelf's records newest first, which
moved the wrong record whenever a batch stood twice on one shelf: the run ate
the older, the newer went down. Replacing the mirror with a per-batch and
per-owner claim fixed the batch-by-batch story and left the tie — two records
of one batch and one owner still handed the newer to the run — because the
result named the grain and not the record.

Naming the record closes that. So does locking the run from the top:
every card the run touches, its ingredients and its output, sorted, before
the first plan is read. Locking each card when its own draw got there was the
discipline that, under concurrent runs, ended in a few hundred deadlocks.

The output takes no batch: the record names none, and the records' view files
the goods on the batch-less grain.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.maker.models import BoMLine, MakerRecipe
from tests.integration._holds import hold
from tests.integration._shelf import put_on_shelf, run_in_async_session

pytestmark = pytest.mark.integration

#: One run of the recipe eats three units of the ingredient.
_EATEN = Decimal('3')


def _template(db: Session, org: Organization, name: str) -> ProductTemplate:
    template = ProductTemplate(
        organization_id=org.id, name=name, sku=f'SKU-{uuid.uuid4().hex[:8]}'
    )
    db.add(template)
    db.flush()
    return template


def _recipe(db: Session, org: Organization, *, output_id: UUID, child_id: UUID) -> None:
    recipe = MakerRecipe(
        organization_id=org.id,
        output_template_id=output_id,
        name='One line',
        batch_yield_qty=Decimal('1'),
        is_default=True,
    )
    db.add(recipe)
    db.flush()
    db.add(
        BoMLine(
            organization_id=org.id,
            recipe_id=recipe.id,
            parent_template_id=output_id,
            child_template_id=child_id,
            qty_per_batch=_EATEN,
            unit='pcs',
        )
    )
    db.flush()


class _Shelf:
    """One ingredient on one shelf, its stock put there record by record.

    Every stock arrives as a record through the items service, the way the
    application puts it there, so whatever the run leaves out of step is the
    run's own doing. Each one is put in a transaction of its own, so the
    order of the calls is the order FIFO hands the records out — the oldest
    first — and the shelf lists the records the other way round, the newest
    first.
    """

    def __init__(
        self,
        db: Session,
        org: Organization,
        loc: StorageLocation,
        keeper: User,
        engine: AsyncEngine,
    ) -> None:
        self.db = db
        self.org = org
        self.loc = loc
        self.keeper = keeper
        self.engine = engine
        self.ingredient = _template(db, org, 'Ingredient')
        self.output = _template(db, org, 'Output')
        _recipe(db, org, output_id=self.output.id, child_id=self.ingredient.id)

    def batch(self, name: str) -> StockLot:
        lot = StockLot(
            organization_id=self.org.id,
            product_template_id=self.ingredient.id,
            name=name,
        )
        self.db.add(lot)
        self.db.flush()
        return lot

    def stock(
        self,
        qty: str,
        *,
        lot: StockLot | None = None,
        owner: Partner | None = None,
        ingredient: ProductTemplate | None = None,
    ) -> Item:
        template = ingredient or self.ingredient
        lot_id = lot.id if lot else None
        owner_id = owner.id if owner else None
        self.db.commit()

        async def _put(session: AsyncSession) -> UUID:
            record = await put_on_shelf(
                session,
                self.keeper,
                template,
                self.loc.id,
                qty,
                lot_id=lot_id,
                owner_id=owner_id,
            )
            return record.id

        record_id = run_in_async_session(self.engine, _put)
        self.db.expire_all()
        record = self.db.get(Item, record_id)
        assert record is not None
        return record

    def quantity_of(self, record: Item) -> Decimal:
        self.db.expire_all()
        return self.db.execute(
            select(Item.quantity).where(Item.id == record.id)
        ).scalar_one()


def _run(
    client: TestClient,
    headers: dict[str, str],
    shelf: _Shelf,
    output_loc: StorageLocation,
) -> UUID:
    created = client.post(
        '/api/v1/maker/production/orders',
        headers=headers,
        json={
            'output_template_id': str(shelf.output.id),
            'planned_qty': '1',
            'input_storage_location_id': str(shelf.loc.id),
            'output_location_id': str(output_loc.id),
        },
    )
    assert created.status_code == 201, created.text
    completed = client.post(
        f'/api/v1/maker/production/orders/{created.json()["id"]}/complete',
        headers=headers,
    )
    assert completed.status_code == 200, completed.text
    return UUID(created.json()['id'])


def test_the_batch_the_run_ate_is_the_batch_whose_record_goes_down(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    mk_user: User,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
) -> None:
    shelf = _Shelf(db_session, mk_org, mk_input_loc, mk_user, async_engine_fixture)
    # FIFO hands out the older batch; the shelf lists the newer record first,
    # which is the one a per-shelf mirror reached for.
    older = shelf.stock('5', lot=shelf.batch('LOT-OLD'))
    newer = shelf.stock('5', lot=shelf.batch('LOT-NEW'))
    db_session.commit()

    _run(client, mk_auth_headers, shelf, mk_output_loc)

    assert (shelf.quantity_of(older), shelf.quantity_of(newer)) == (
        Decimal('2'),
        Decimal('5'),
    )


def test_a_batch_its_reservation_rows_hold_is_passed_by(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    mk_user: User,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
) -> None:
    """The run plans its draw from the records and the reservation rows.

    The older batch is first in line and promised whole by a reservation
    row: the rows call it held, so the run takes the newer batch.
    """
    shelf = _Shelf(db_session, mk_org, mk_input_loc, mk_user, async_engine_fixture)
    older = shelf.stock('5', lot=shelf.batch('LOT-OLD'))
    newer = shelf.stock('5', lot=shelf.batch('LOT-NEW'))
    promised = db_session.execute(
        select(ShelfRow).where(ShelfRow.lot_id == older.lot_id)
    ).scalar_one()
    hold(db_session, promised, Decimal('5'))
    db_session.commit()

    _run(client, mk_auth_headers, shelf, mk_output_loc)

    assert (shelf.quantity_of(older), shelf.quantity_of(newer)) == (
        Decimal('5'),
        Decimal('2'),
    )


def test_a_consignors_goods_come_off_the_consignors_record(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    mk_user: User,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
) -> None:
    shelf = _Shelf(db_session, mk_org, mk_input_loc, mk_user, async_engine_fixture)
    consignor = Partner(organization_id=mk_org.id, name='Consignor', type='SUPPLIER')
    db_session.add(consignor)
    db_session.flush()
    # A run consumes consignment stock like its own; the older record here is
    # the consignor's, so that is what the draw takes.
    consigned = shelf.stock('5', owner=consignor)
    own = shelf.stock('5')
    db_session.commit()

    _run(client, mk_auth_headers, shelf, mk_output_loc)

    assert (shelf.quantity_of(consigned), shelf.quantity_of(own)) == (
        Decimal('2'),
        Decimal('5'),
    )


def test_the_output_record_and_its_group_stand_on_the_same_grain(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    mk_user: User,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
) -> None:
    """Pins the output as it is: no batch on the record, none on its group."""
    shelf = _Shelf(db_session, mk_org, mk_input_loc, mk_user, async_engine_fixture)
    shelf.stock('5')
    db_session.commit()

    _run(client, mk_auth_headers, shelf, mk_output_loc)

    db_session.expire_all()
    records = db_session.execute(
        select(Item.lot_id, Item.owner_id, Item.quantity).where(
            Item.template_id == shelf.output.id
        )
    ).all()
    groups = db_session.execute(
        select(ShelfRow.lot_id, ShelfRow.owner_id, ShelfRow.quantity).where(
            ShelfRow.product_template_id == shelf.output.id
        )
    ).all()
    assert [tuple(row) for row in records] == [tuple(row) for row in groups]
    assert len(records) == 1
    assert records[0].lot_id is None


def _also_eats(
    db: Session,
    org: Organization,
    output: ProductTemplate,
    child: ProductTemplate,
    qty: Decimal,
) -> None:
    """Give the shelf's recipe a second line, so a run touches two cards."""
    recipe = db.execute(
        select(MakerRecipe).where(MakerRecipe.output_template_id == output.id)
    ).scalar_one()
    db.add(
        BoMLine(
            organization_id=org.id,
            recipe_id=recipe.id,
            parent_template_id=output.id,
            child_template_id=child.id,
            qty_per_batch=qty,
            unit='pcs',
        )
    )
    db.flush()


def test_two_records_of_one_batch_leave_the_one_the_draw_named(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    mk_user: User,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
) -> None:
    """The draw names the record it takes; nothing guesses afterwards.

    Two records of one batch and one owner stand on a shelf, five and five.
    FIFO's plan names the older — that is what the run eats. The per-shelf
    mirror that used to follow summed the draw for the grain and reached for
    the shelf's newest record of it: the two tie on claim and the shelf lists
    newest first, so the newer went down and the older, the one actually
    eaten, stood untouched.
    """
    shelf = _Shelf(db_session, mk_org, mk_input_loc, mk_user, async_engine_fixture)
    batch = shelf.batch('LOT-SPLIT')
    older = shelf.stock('5', lot=batch)
    newer = shelf.stock('5', lot=batch)
    db_session.commit()

    _run(client, mk_auth_headers, shelf, mk_output_loc)

    assert (shelf.quantity_of(older), shelf.quantity_of(newer)) == (
        Decimal('2'),
        Decimal('5'),
    )


def test_a_run_locks_every_card_it_will_touch_before_it_reads_a_plan(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    mk_user: User,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """From the top: every key of the run, sorted, before the first read.

    A run eats two ingredients and makes one output. Locking each card when
    its own draw got there is the discipline that, under concurrent runs,
    ended in a few hundred deadlocks; the whole key set up front held. The output
    card belongs to the set: a run that eats A to make B and one that eats B
    to make A are exactly the shape that deadlocks without it.
    """
    from app.services import _stock_quant_ops

    shelf = _Shelf(db_session, mk_org, mk_input_loc, mk_user, async_engine_fixture)
    second = _template(db_session, mk_org, 'Second')
    _also_eats(db_session, mk_org, shelf.output, second, Decimal('1'))
    shelf.stock('5')
    shelf.stock('5', ingredient=second)
    db_session.commit()

    calls: list[list[tuple[object, object]]] = []
    real_lock = _stock_quant_ops.lock_stock_async

    async def _recording_lock(
        db: AsyncSession,
        organization_id: UUID,
        *,
        keys: Any = (),
        **kwargs: Any,
    ) -> Any:
        calls.append(sorted(tuple(key) for key in keys))
        return await real_lock(db, organization_id, keys=keys, **kwargs)

    monkeypatch.setattr(_stock_quant_ops, 'lock_stock_async', _recording_lock)

    _run(client, mk_auth_headers, shelf, mk_output_loc)

    assert calls[0] == sorted(
        [
            (shelf.ingredient.id, None),
            (second.id, None),
            (shelf.output.id, None),
        ]
    )
    assert [(shelf.output.id, mk_output_loc.id)] in calls


def test_the_books_of_every_batch_stay_in_step_with_what_the_run_ate(
    client: TestClient,
    mk_auth_headers: dict[str, str],
    mk_org: Organization,
    mk_input_loc: StorageLocation,
    mk_output_loc: StorageLocation,
    mk_user: User,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
) -> None:
    """Per batch of the ingredient: before − the run's own consumption = after.

    The consumption each batch gave up is the run's journal rows for it, so
    this reads the answer back out of the books rather than out of the plan.
    Green before this change too — the mirror kept the totals even while it
    moved the wrong record — so it pins the invariant rather than the fix.
    """
    from app.models.stock_move import StockMove

    shelf = _Shelf(db_session, mk_org, mk_input_loc, mk_user, async_engine_fixture)
    lots = [shelf.batch('LOT-A'), shelf.batch('LOT-B')]
    for lot in lots:
        shelf.stock('5', lot=lot)
    shelf.stock('4')
    db_session.commit()

    def totals() -> dict[int | None, Decimal]:
        db_session.expire_all()
        rows = db_session.execute(
            select(Item.lot_id, Item.quantity).where(
                Item.template_id == shelf.ingredient.id
            )
        ).all()
        sums: dict[int | None, Decimal] = {}
        for lot_id, quantity in rows:
            key = lot_id
            sums[key] = sums.get(key, Decimal('0')) + (quantity or Decimal('0'))
        return sums

    before = totals()
    order_id = _run(client, mk_auth_headers, shelf, mk_output_loc)
    after = totals()

    db_session.expire_all()
    rows = db_session.execute(
        select(StockMove.lot_id, StockMove.quantity).where(
            StockMove.reference_id == order_id,
            StockMove.product_template_id == shelf.ingredient.id,
        )
    ).all()
    eaten: dict[int | None, Decimal] = {}
    for lot_id, quantity in rows:
        eaten[lot_id] = eaten.get(lot_id, Decimal('0')) + quantity

    assert set(before) == set(after)
    for lot_id, held in before.items():
        assert held - eaten.get(lot_id, Decimal('0')) == after[lot_id]
