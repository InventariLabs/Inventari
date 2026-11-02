"""The numbers a warehouse actually works from had no screen.

The item list shows ``Item.quantity`` — a denormalised cache, one row per
record. What a picker needs is the other record: how much of a product is at
one place, out of which batch, and how much of it is already promised to
somebody else. That lived in the quant table from the day the warehouse
modules were written (the records' view sums it now), behind an endpoint the
warehouse module registered, which an organization running purchase orders
and stock takes without documents could not open at all.

So Core answers it, the same way it answers the ledger: names instead of
identifiers, the location tree instead of one node, and reservations as
their own column — never quietly subtracted, because "6 on the shelf, 4
promised" and "2 on the shelf" are different sentences.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import LotStatus, StockLot
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.uom import Uom, UomCategory
from app.models.user import User
from app.services.token_service import create_access_token
from tests.integration._shelf import put_on_shelf, reserve_for_an_order


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


class _Shelves:
    def __init__(self) -> None:
        self.org: Organization
        self.user: User
        self.warehouse: StorageLocation
        self.aisle_one: StorageLocation
        self.aisle_two: StorageLocation
        self.yard: StorageLocation
        self.flour: ProductTemplate
        self.sugar: ProductTemplate
        self.lot: StockLot


@pytest.fixture
async def shelves(real_async_db_session: AsyncSession) -> _Shelves:
    db = real_async_db_session
    fixture = _Shelves()

    fixture.org = Organization(
        name=f'Shelves {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations'],
    )
    db.add(fixture.org)
    await db.commit()
    await db.refresh(fixture.org)

    fixture.user = await ModuleTestHelper.create_user_async(
        db, fixture.org, email=f'picker_{uuid4().hex[:8]}@test.com'
    )
    await db.commit()

    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()

    def _location(name: str, parent: StorageLocation | None = None) -> StorageLocation:
        location = StorageLocation(
            name=name,
            organization_id=fixture.org.id,
            storage_type_id=storage_type.id,
            created_by=fixture.user.id,
            parent_id=parent.id if parent is not None else None,
        )
        db.add(location)
        return location

    fixture.warehouse = _location('Warehouse')
    await db.flush()
    fixture.aisle_one = _location('Aisle 1', fixture.warehouse)
    fixture.aisle_two = _location('Aisle 2', fixture.warehouse)
    fixture.yard = _location('Yard')
    await db.flush()

    category = UomCategory(
        name=f'Weight {uuid4().hex[:6]}', organization_id=fixture.org.id
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
    fixture.sugar = ProductTemplate(
        name='Sugar',
        organization_id=fixture.org.id,
        # The code a scan wrote: the other way a reader names a product.
        barcode='5901234123457',
    )
    db.add_all([fixture.flour, fixture.sugar])
    await db.flush()

    fixture.lot = StockLot(
        organization_id=fixture.org.id,
        product_template_id=fixture.flour.id,
        name='L-7',
    )
    db.add(fixture.lot)
    await db.flush()

    user = fixture.user
    await put_on_shelf(
        db, user, fixture.flour, fixture.aisle_one.id, 6, lot_id=fixture.lot.id
    )
    await reserve_for_an_order(db, fixture.flour, fixture.aisle_one.id, 4)
    # Recalled after the order took its four: the goods and the promise stay
    # where they are, and nobody may pick them now.
    fixture.lot.status = LotStatus.RECALLED
    await put_on_shelf(db, user, fixture.flour, fixture.aisle_two.id, 9)
    await put_on_shelf(db, user, fixture.sugar, fixture.yard.id, 2)
    await db.commit()
    return fixture


async def _drain_sugar_from_aisle_one(db: AsyncSession, shelves: _Shelves) -> None:
    """Sugar that stood in aisle one and was all used: the quant stays at zero."""
    record = await put_on_shelf(
        db, shelves.user, shelves.sugar, shelves.aisle_one.id, 2
    )
    await core_api.items.update_quantity_async(
        db, shelves.org.id, record.id, Decimal('0'), user_id=shelves.user.id
    )
    await db.commit()


async def _ask(client: AsyncClient, shelves: _Shelves, **params: object):
    response = await client.get(
        '/api/v1/stock-quants', params=params, headers=_auth(shelves.user)
    )
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    return body['items'], body['total']


class TestTheShelfReadsInWords:
    async def test_a_row_names_the_product_the_place_and_the_batch(
        self, real_async_client: AsyncClient, shelves: _Shelves
    ) -> None:
        rows, _ = await _ask(real_async_client, shelves, lot_id=str(shelves.lot.id))

        row = rows[0]
        assert row['product_name'] == 'Rye flour'
        assert row['uom_symbol'] == 'kg'
        assert row['location_name'] == 'Aisle 1'
        assert row['lot_name'] == 'L-7'

    async def test_a_held_batch_says_so_on_the_shelf(
        self, real_async_client: AsyncClient, shelves: _Shelves
    ) -> None:
        rows, _ = await _ask(real_async_client, shelves, lot_id=str(shelves.lot.id))

        # The picker must see the recall where the goods are, not only on the
        # batch's own page (the recall blocks the pick; nothing showed why).
        assert rows[0]['lot_status'] == LotStatus.RECALLED


class TestReservationsAreNotSubtractedQuietly:
    async def test_the_promise_is_its_own_column(
        self, real_async_client: AsyncClient, shelves: _Shelves
    ) -> None:
        rows, _ = await _ask(real_async_client, shelves, lot_id=str(shelves.lot.id))

        row = rows[0]
        # "6 on the shelf, 4 promised" and "2 on the shelf" are different
        # sentences, and only one of them lets a picker plan.
        assert Decimal(row['quantity']) == Decimal('6.000')
        assert Decimal(row['reserved_quantity']) == Decimal('4.000')
        # This batch is recalled, so none of the six may be taken — see
        # TestABatchNobodyMayTouchIsNotAvailable. The free-stock arithmetic
        # itself is asserted there on a batch that may be picked.
        assert Decimal(row['available_quantity']) == Decimal('0')


class TestABatchNobodyMayTouchIsNotAvailable:
    """The badge said quarantined and the column beside it said take twelve.

    The engine refuses: ``active_lot_predicate`` keeps a held batch out of
    the candidates and ``assert_lot_consumable_async`` says so in words. The
    column knew nothing about it — it was quantity minus reservations and
    nothing else — so a planner summing it, which is what the column is for,
    promised a customer goods the warehouse would not release. The refusal
    arrived at picking time, after the promise.
    """

    async def test_a_recalled_batch_offers_nothing(
        self, real_async_client: AsyncClient, shelves: _Shelves
    ) -> None:
        rows, _ = await _ask(real_async_client, shelves, lot_id=str(shelves.lot.id))

        row = rows[0]
        assert row['lot_status'] == LotStatus.RECALLED
        # The goods are still on the shelf and the row still says so; what
        # changes is the one number a planner adds up.
        assert Decimal(row['quantity']) == Decimal('6.000')
        assert Decimal(row['available_quantity']) == Decimal('0')

    async def test_a_batch_that_may_be_picked_still_counts(
        self,
        real_async_client: AsyncClient,
        shelves: _Shelves,
        real_async_db_session: AsyncSession,
    ) -> None:
        db = real_async_db_session
        good_lot = StockLot(
            organization_id=shelves.org.id,
            product_template_id=shelves.sugar.id,
            name='L-8',
            status=LotStatus.ACTIVE,
        )
        db.add(good_lot)
        await db.flush()
        await put_on_shelf(
            db, shelves.user, shelves.sugar, shelves.aisle_two.id, 6, lot_id=good_lot.id
        )
        await reserve_for_an_order(db, shelves.sugar, shelves.aisle_two.id, 4)
        await db.commit()

        rows, _ = await _ask(real_async_client, shelves, lot_id=str(good_lot.id))

        # Unchanged for everything the guard does not touch: free stock is
        # still what is there minus what is promised.
        assert Decimal(rows[0]['available_quantity']) == Decimal('2.000')

    async def test_stock_outside_any_batch_is_unaffected(
        self, real_async_client: AsyncClient, shelves: _Shelves
    ) -> None:
        rows, _ = await _ask(
            real_async_client, shelves, location_id=str(shelves.aisle_two.id)
        )

        # No batch means no batch status to obey.
        assert rows[0]['lot_status'] is None
        assert Decimal(rows[0]['available_quantity']) == Decimal('9.000')


class TestTheQuestionCanBeNarrowed:
    async def test_a_place_answers_for_everything_below_it(
        self, real_async_client: AsyncClient, shelves: _Shelves
    ) -> None:
        rows, total = await _ask(
            real_async_client, shelves, location_id=str(shelves.warehouse.id)
        )

        # The warehouse holds nothing itself; both aisles do.
        assert total == 2
        assert {row['location_name'] for row in rows} == {'Aisle 1', 'Aisle 2'}

    async def test_one_product_at_a_time(
        self, real_async_client: AsyncClient, shelves: _Shelves
    ) -> None:
        rows, total = await _ask(
            real_async_client,
            shelves,
            product_template_id=str(shelves.flour.id),
        )

        assert total == 2
        assert {row['product_name'] for row in rows} == {'Rye flour'}

    async def test_a_shelf_drained_to_zero_is_left_out_by_default(
        self,
        real_async_client: AsyncClient,
        shelves: _Shelves,
        real_async_db_session: AsyncSession,
    ) -> None:
        await _drain_sugar_from_aisle_one(real_async_db_session, shelves)

        rows, total = await _ask(real_async_client, shelves)

        # A quant drained to zero stays in the table forever; listing it
        # beside real stock buries the real stock.
        assert total == 3
        assert all(Decimal(row['quantity']) != 0 for row in rows)

    async def test_the_empty_ones_can_still_be_asked_for(
        self,
        real_async_client: AsyncClient,
        shelves: _Shelves,
        real_async_db_session: AsyncSession,
    ) -> None:
        await _drain_sugar_from_aisle_one(real_async_db_session, shelves)

        _, total = await _ask(real_async_client, shelves, include_empty=True)

        # "Where did this product used to be" is a real question, and the
        # zero rows are the only record of it.
        assert total == 4

    async def test_stock_promised_down_to_nothing_is_still_listed(
        self,
        real_async_client: AsyncClient,
        shelves: _Shelves,
        real_async_db_session: AsyncSession,
    ) -> None:
        db = real_async_db_session
        await put_on_shelf(db, shelves.user, shelves.sugar, shelves.aisle_two.id, 3)
        await reserve_for_an_order(db, shelves.sugar, shelves.aisle_two.id, 3)
        await db.commit()

        rows, _ = await _ask(
            real_async_client, shelves, product_template_id=str(shelves.sugar.id)
        )

        # Three on the shelf and all three promised is nothing to pick and a
        # row somebody has to act on — the opposite of an empty shelf.
        spoken_for = [row for row in rows if Decimal(row['available_quantity']) == 0]
        assert len(spoken_for) == 1
        assert Decimal(spoken_for[0]['quantity']) == Decimal('3.000')


class TestTheShelfCanBeNamedInsteadOfScrolled:
    """The screen exists to answer "how much of this lies here", and a test
    organization had 143 rows of it on three pages with nothing to name a
    product with. What a reader types is matched the way the product list of
    this module matches it — on the product, its code, and the batch this list
    prints as its own column — and the count describes the narrowed list, so a
    one-row answer is not paged over three pages.
    """

    async def test_a_typed_name_leaves_only_that_product(
        self, real_async_client: AsyncClient, shelves: _Shelves
    ) -> None:
        rows, total = await _ask(real_async_client, shelves, search='flour')

        assert total == len(rows) == 2
        assert {row['product_name'] for row in rows} == {'Rye flour'}

    async def test_the_code_a_scan_wrote_is_a_way_in(
        self, real_async_client: AsyncClient, shelves: _Shelves
    ) -> None:
        rows, total = await _ask(real_async_client, shelves, search='5901234123457')

        assert total == 1
        assert rows[0]['product_name'] == 'Sugar'

    async def test_the_batch_on_the_row_is_a_way_in_too(
        self, real_async_client: AsyncClient, shelves: _Shelves
    ) -> None:
        # PARTIA is a column of this very list: a recall notice names the
        # batch, not the product.
        rows, total = await _ask(real_async_client, shelves, search='l-7')

        assert total == 1
        assert rows[0]['lot_name'] == 'L-7'

    async def test_a_name_nobody_has_answers_empty_rather_than_everything(
        self, real_async_client: AsyncClient, shelves: _Shelves
    ) -> None:
        rows, total = await _ask(real_async_client, shelves, search='makaron')

        assert (rows, total) == ([], 0)

    async def test_the_name_narrows_together_with_the_place(
        self, real_async_client: AsyncClient, shelves: _Shelves
    ) -> None:
        # Two filters, one answer: the product at that place, not the product
        # and the place as two separate lists.
        rows, total = await _ask(
            real_async_client,
            shelves,
            search='flour',
            location_id=str(shelves.aisle_two.id),
        )

        assert total == 1
        assert rows[0]['location_name'] == 'Aisle 2'


class TestTheShelfBelongsToOneOrganization:
    async def test_another_organization_sees_none_of_it(
        self,
        real_async_client: AsyncClient,
        shelves: _Shelves,
        real_async_db_session: AsyncSession,
    ) -> None:
        db = real_async_db_session
        stranger_org = Organization(
            name=f'Stranger {uuid4().hex[:6]}', enabled_modules=['core', 'items']
        )
        db.add(stranger_org)
        await db.commit()
        stranger = await ModuleTestHelper.create_user_async(
            db, stranger_org, email=f'stranger_{uuid4().hex[:8]}@test.com'
        )
        await db.commit()

        response = await real_async_client.get(
            '/api/v1/stock-quants', headers=_auth(stranger)
        )

        assert response.json()['total'] == 0


class TestTheRowCarriesTheDateThatDecidesWhenToUseIt:
    """A shelf answers "how much" and, for goods that spoil, "until when"."""

    async def test_a_group_reports_the_earliest_date_among_its_records(
        self,
        real_async_client: AsyncClient,
        shelves: _Shelves,
        real_async_db_session: AsyncSession,
    ) -> None:
        db = real_async_db_session
        await put_on_shelf(
            db,
            shelves.user,
            shelves.sugar,
            shelves.aisle_two.id,
            1,
            expiry_date=date(2031, 5, 1),
        )
        await put_on_shelf(
            db,
            shelves.user,
            shelves.sugar,
            shelves.aisle_two.id,
            1,
            expiry_date=date(2030, 3, 1),
        )
        await db.commit()

        rows, _ = await _ask(
            real_async_client,
            shelves,
            location_id=str(shelves.aisle_two.id),
            product_template_id=str(shelves.sugar.id),
        )

        assert [row['expiry_date'] for row in rows] == ['2030-03-01']

    async def test_a_batch_without_dated_records_lends_its_own_date(
        self,
        real_async_client: AsyncClient,
        shelves: _Shelves,
        real_async_db_session: AsyncSession,
    ) -> None:
        shelves.lot.expiry_date = date(2032, 1, 1)
        await real_async_db_session.commit()

        rows, _ = await _ask(real_async_client, shelves, lot_id=str(shelves.lot.id))

        assert rows[0]['expiry_date'] == '2032-01-01'

    async def test_undated_stock_has_no_date(
        self, real_async_client: AsyncClient, shelves: _Shelves
    ) -> None:
        rows, _ = await _ask(
            real_async_client, shelves, location_id=str(shelves.yard.id)
        )

        assert rows[0]['expiry_date'] is None
