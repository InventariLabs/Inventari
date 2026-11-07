"""What was on the shelf on the 24th of December.

An auditor, an accountant closing a quarter and an insurer after a fire all
ask the same question, and the application could only answer "what is on the
shelf now". Everything needed to answer it was recorded — the ledger has
every movement, the layers have every cost — and nothing put the two
together.

The count runs *backwards* from today's shelves: the current quantity minus
everything that moved after the date. Counting forward from zero is the
obvious way and it lies for every organization that typed its opening stock
straight into the records, with no document behind it — which is most of
them on their first day.

And it refuses rather than guesses. A report that shows calm numbers for a
year the ledger knows nothing about is more dangerous than one that says "I
have nothing before 12 March".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper, ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token
from tests.integration._shelf import put_on_shelf

_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
_A_MONTH_AGO = _NOW - timedelta(days=30)
_A_WEEK_AGO = _NOW - timedelta(days=7)


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


class _Warehouse:
    def __init__(self) -> None:
        self.org: Organization
        self.user: User
        self.aisle_one: StorageLocation
        self.aisle_two: StorageLocation
        self.flour: ProductTemplate
        self.flour_on_shelf: Item


async def _dated(
    db: AsyncSession,
    template_id: UUID,
    day: datetime,
    *,
    booked: datetime | None = None,
) -> None:
    """Date what the ledger wrote today for *template_id* to *day*.

    Every record in this file goes in today, and the report is about June.
    A movement carries the day it is about in ``completed_at``. A cost layer
    is dated by its document's date, or by the moment it was written when no
    document stands behind it — *booked* names that moment for a layer
    entered after the day it is about, and gives it a document dated *day*.
    """
    for move in await db.scalars(
        select(StockMove).where(
            StockMove.product_template_id == template_id,
            func.coalesce(StockMove.completed_at, StockMove.created_at) > _NOW,
        )
    ):
        move.completed_at = day
    for layer in await db.scalars(
        select(StockValuationLayer).where(
            StockValuationLayer.product_template_id == template_id,
            StockValuationLayer.created_at > _NOW,
        )
    ):
        layer.created_at = booked or day
        layer.document_date = day.date() if booked else None
    await db.flush()


async def _arrives(
    db: AsyncSession,
    warehouse: _Warehouse,
    template: ProductTemplate,
    quantity: int,
    *,
    on: datetime,
    price: str | None = None,
    booked: datetime | None = None,
) -> Item:
    """*quantity* of *template* arrives in aisle one on the day *on*, as a record."""
    record = await put_on_shelf(
        db,
        warehouse.user,
        template,
        warehouse.aisle_one.id,
        quantity,
        purchase_price=price,
    )
    await _dated(db, template.id, on, booked=booked)
    return record


async def _goes_down_to(
    db: AsyncSession, warehouse: _Warehouse, record: Item, left: int, *, on: datetime
) -> None:
    """The record is used down to *left* on the day *on*."""
    await core_api.items.update_quantity_async(
        db, warehouse.org.id, record.id, Decimal(left), user_id=warehouse.user.id
    )
    await _dated(db, record.template_id, on)


@pytest.fixture
async def warehouse(real_async_db_session: AsyncSession) -> _Warehouse:
    """Twenty kilos land two months ago, six leave a week ago; nobody named a price."""
    return await _stock_a_warehouse(real_async_db_session, price=None)


@pytest.fixture
async def priced_warehouse(real_async_db_session: AsyncSession) -> _Warehouse:
    """The same twenty kilos and the same six, bought at 3.00 a kilo."""
    return await _stock_a_warehouse(real_async_db_session, price='3.00')


async def _stock_a_warehouse(db: AsyncSession, *, price: str | None) -> _Warehouse:
    fixture = _Warehouse()

    # A ledger exists only where a module records movements (ADR-004), so
    # the warehouse this report is about has one.
    fixture.org = Organization(
        name=f'As Of {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'warehouse'],
    )
    db.add(fixture.org)
    await db.commit()
    await db.refresh(fixture.org)

    fixture.user = await ModuleTestHelper.create_user_async(
        db, fixture.org, email=f'books_{uuid4().hex[:8]}@test.com'
    )
    await db.commit()

    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()

    def _location(name: str) -> StorageLocation:
        location = StorageLocation(
            name=name,
            organization_id=fixture.org.id,
            storage_type_id=storage_type.id,
            created_by=fixture.user.id,
        )
        db.add(location)
        return location

    fixture.aisle_one = _location('Aisle 1')
    fixture.aisle_two = _location('Aisle 2')
    await db.flush()

    fixture.flour = ProductTemplate(name='Rye flour', organization_id=fixture.org.id)
    db.add(fixture.flour)
    await db.flush()

    fixture.flour_on_shelf = await _arrives(
        db, fixture, fixture.flour, 20, on=_NOW - timedelta(days=60), price=price
    )
    await _goes_down_to(db, fixture, fixture.flour_on_shelf, 14, on=_A_WEEK_AGO)
    await db.commit()
    return fixture


async def _report(client: AsyncClient, warehouse: _Warehouse, **params: object):
    response = await client.get(
        '/api/v1/stock-as-of', params=params, headers=_auth(warehouse.user)
    )
    return response


async def _set_show_inventory_value(
    db: AsyncSession, warehouse: _Warehouse, value: bool
) -> None:
    """Throw the organization's switch, the way its settings screen does."""
    await core_api.settings.set_bulk_async(
        db, warehouse.org.id, 'stats', {'show_inventory_value': value}
    )
    await db.commit()


def _pdf_text(pdf: bytes) -> str:
    """Every word the printed sheet carries, as the reader's eyes find it."""
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf))
    return '\n'.join(page.extract_text() or '' for page in reader.pages)


class TestTheCountRunsBackwards:
    async def test_today_is_what_is_on_the_shelf(
        self, real_async_client: AsyncClient, warehouse: _Warehouse
    ) -> None:
        response = await _report(real_async_client, warehouse, as_of=_NOW.isoformat())

        assert response.status_code == status.HTTP_200_OK
        rows = response.json()['items']
        assert Decimal(rows[0]['quantity']) == Decimal('14.000')

    async def test_a_month_ago_the_six_had_not_left_yet(
        self, real_async_client: AsyncClient, warehouse: _Warehouse
    ) -> None:
        response = await _report(
            real_async_client, warehouse, as_of=_A_MONTH_AGO.isoformat()
        )

        rows = response.json()['items']
        assert Decimal(rows[0]['quantity']) == Decimal('20.000')

    async def test_a_correction_entered_today_for_last_week_stays_in_last_week(
        self,
        real_async_client: AsyncClient,
        warehouse: _Warehouse,
        real_async_db_session: AsyncSession,
    ) -> None:
        # Written now, belongs to a week ago: `completed_at` is the date the
        # movement is *about*, and a report cuts on that (the same mistake
        # that the ageing report makes).
        await _goes_down_to(
            real_async_db_session,
            warehouse,
            warehouse.flour_on_shelf,
            12,
            on=_A_WEEK_AGO,
        )
        await real_async_db_session.commit()

        response = await _report(
            real_async_client, warehouse, as_of=_A_MONTH_AGO.isoformat()
        )

        # The month-old report must not move: the correction belongs to a
        # week ago, which is after the date being asked about.
        rows = response.json()['items']
        assert Decimal(rows[0]['quantity']) == Decimal('20.000')


class TestMovingStockAroundChangesNothingButThePlaces:
    async def test_an_internal_transfer_leaves_the_total_alone(
        self,
        real_async_client: AsyncClient,
        warehouse: _Warehouse,
        real_async_db_session: AsyncSession,
    ) -> None:
        # Yesterday the fourteen kilos left went over to aisle 2.
        db = real_async_db_session
        await core_api.items.transfer_async(
            db,
            warehouse.org.id,
            warehouse.flour_on_shelf.id,
            warehouse.aisle_two.id,
            user_id=warehouse.user.id,
        )
        await _dated(db, warehouse.flour.id, _NOW - timedelta(days=1))
        await db.commit()

        whole = await _report(
            real_async_client, warehouse, as_of=_A_MONTH_AGO.isoformat()
        )
        one_aisle = await _report(
            real_async_client,
            warehouse,
            as_of=_A_MONTH_AGO.isoformat(),
            location_id=str(warehouse.aisle_two.id),
        )

        # The organization held the same twenty kilos a month ago; aisle 2
        # held none of them.
        assert Decimal(whole.json()['items'][0]['quantity']) == Decimal('20.000')
        assert one_aisle.json()['items'] == []


class TestOnlyWhatActuallyHappenedCounts:
    """A movement that was cancelled never touched a shelf.

    The count runs backwards from today's quantities, so every row it undoes
    has to be a row that was once applied. Nothing writes a non-settled
    movement today, which is exactly why this is worth pinning: the first
    code that does would rewrite last month's report in silence.
    """

    async def test_a_cancelled_movement_is_not_undone(
        self,
        real_async_client: AsyncClient,
        warehouse: _Warehouse,
        real_async_db_session: AsyncSession,
    ) -> None:
        db = real_async_db_session
        db.add(
            StockMove(
                organization_id=warehouse.org.id,
                product_template_id=warehouse.flour.id,
                from_location_id=warehouse.aisle_one.id,
                quantity=Decimal('5.000'),
                completed_at=_A_WEEK_AGO,
                state='cancelled',  # a row the report must refuse to count
            )
        )
        await db.commit()

        # The shelf is untouched by it: a cancelled row never moved a kilo,
        # so the shelf still holds the fourteen the settled rows left.
        shelf = await db.scalar(
            select(ShelfRow).where(ShelfRow.organization_id == warehouse.org.id)
        )
        assert shelf is not None
        assert shelf.quantity == Decimal('14.000')

        response = await _report(
            real_async_client, warehouse, as_of=_A_MONTH_AGO.isoformat()
        )

        # Twenty, not twenty-five. Undoing the cancelled five would put back
        # a quantity that was never taken out.
        rows = response.json()['items']
        assert Decimal(rows[0]['quantity']) == Decimal('20.000')

    async def test_a_cancelled_movement_does_not_extend_the_coverage(
        self,
        real_async_client: AsyncClient,
        warehouse: _Warehouse,
        real_async_db_session: AsyncSession,
    ) -> None:
        db = real_async_db_session
        db.add(
            StockMove(
                organization_id=warehouse.org.id,
                product_template_id=warehouse.flour.id,
                to_location_id=warehouse.aisle_one.id,
                quantity=Decimal('1.000'),
                completed_at=_NOW - timedelta(days=400),
                state='cancelled',  # a row the report must refuse to count
            )
        )
        await db.commit()

        response = await _report(real_async_client, warehouse, as_of=_NOW.isoformat())

        # The ledger still begins where the first settled movement is. A row
        # nobody posted cannot be the evidence that a year is reconstructable.
        assert response.json()['complete_from'].startswith('2026-05-01')

        older = await _report(
            real_async_client,
            warehouse,
            as_of=(_NOW - timedelta(days=390)).isoformat(),
        )
        assert older.status_code == status.HTTP_400_BAD_REQUEST


class TestTwoBatchesOnTwoShelvesCountBackTogether:
    """One product in two batches, on two shelves, moved and used after the date.

    Today's quantity is what the records hold, summed per product over
    every batch and shelf asked about; each shelf's count then runs back
    through the movements that touched it. The batch is the grain the
    records are kept at, not a key of the report, so two batches of one
    product come back as one row.

    Oats: ten of batch A land in aisle 1 fifty days ago, six of batch B in
    aisle 2 forty days ago; a week ago batch A goes over to aisle 2, three
    days ago batch B is used down to two.
    """

    @pytest.fixture
    async def oats(
        self, real_async_db_session: AsyncSession, warehouse: _Warehouse
    ) -> ProductTemplate:
        db = real_async_db_session
        oats = ProductTemplate(name='Oats', organization_id=warehouse.org.id)
        db.add(oats)
        await db.flush()
        batch_a, batch_b = (
            StockLot(
                organization_id=warehouse.org.id,
                product_template_id=oats.id,
                name=name,
            )
            for name in ('A', 'B')
        )
        db.add_all([batch_a, batch_b])
        await db.flush()

        in_batch_a = await put_on_shelf(
            db, warehouse.user, oats, warehouse.aisle_one.id, 10, lot_id=batch_a.id
        )
        await _dated(db, oats.id, _NOW - timedelta(days=50))
        in_batch_b = await put_on_shelf(
            db, warehouse.user, oats, warehouse.aisle_two.id, 6, lot_id=batch_b.id
        )
        await _dated(db, oats.id, _NOW - timedelta(days=40))
        await core_api.items.transfer_async(
            db,
            warehouse.org.id,
            in_batch_a.id,
            warehouse.aisle_two.id,
            user_id=warehouse.user.id,
        )
        await _dated(db, oats.id, _A_WEEK_AGO)
        await core_api.items.update_quantity_async(
            db, warehouse.org.id, in_batch_b.id, Decimal(2), user_id=warehouse.user.id
        )
        await _dated(db, oats.id, _NOW - timedelta(days=3))
        await db.commit()
        return oats

    @staticmethod
    async def _oats_on(
        client: AsyncClient,
        warehouse: _Warehouse,
        oats: ProductTemplate,
        day: datetime,
        location: StorageLocation | None = None,
    ) -> Decimal | None:
        params: dict[str, object] = {'as_of': day.isoformat()}
        if location is not None:
            params['location_id'] = str(location.id)
        response = await _report(client, warehouse, **params)
        assert response.status_code == status.HTTP_200_OK
        quantities = [
            Decimal(row['quantity'])
            for row in response.json()['items']
            if row['product_template_id'] == str(oats.id)
        ]
        assert len(quantities) <= 1, quantities
        return quantities[0] if quantities else None

    @pytest.mark.parametrize(
        ('days_ago', 'whole', 'aisle_one', 'aisle_two'),
        [
            (0, '12', None, '12'),
            (5, '16', None, '16'),
            (30, '16', '10', '6'),
            (45, '10', '10', None),
        ],
        ids=['today', 'after-the-move', 'before-the-move', 'before-batch-b'],
    )
    async def test_the_count_on_each_shelf_and_in_the_whole_runs_back(
        self,
        real_async_client: AsyncClient,
        warehouse: _Warehouse,
        oats: ProductTemplate,
        days_ago: int,
        whole: str,
        aisle_one: str | None,
        aisle_two: str | None,
    ) -> None:
        day = _NOW - timedelta(days=days_ago)

        expected = {
            'whole': Decimal(whole),
            'aisle 1': Decimal(aisle_one) if aisle_one else None,
            'aisle 2': Decimal(aisle_two) if aisle_two else None,
        }
        assert {
            'whole': await self._oats_on(real_async_client, warehouse, oats, day),
            'aisle 1': await self._oats_on(
                real_async_client, warehouse, oats, day, warehouse.aisle_one
            ),
            'aisle 2': await self._oats_on(
                real_async_client, warehouse, oats, day, warehouse.aisle_two
            ),
        } == expected


class TestItRefusesRatherThanGuesses:
    async def test_a_date_older_than_the_ledger_is_refused_with_the_boundary(
        self, real_async_client: AsyncClient, warehouse: _Warehouse
    ) -> None:
        response = await _report(
            real_async_client,
            warehouse,
            as_of=(_NOW - timedelta(days=400)).isoformat(),
        )

        # Calm numbers for a year the ledger knows nothing about are more
        # dangerous than "I have nothing before that date".
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        detail = response.json()['detail']
        assert detail['code'] == 'STOCK_AS_OF_BEFORE_LEDGER'
        assert '2026' in detail['message']

    async def test_the_refusal_arrives_in_the_reader_s_language(
        self, real_async_client: AsyncClient, warehouse: _Warehouse
    ) -> None:
        """Accept-Language picks the wording, like every other answer.

        The screen renders the backend's detail verbatim, so an English-only
        refusal handed a Polish bookkeeper the one sentence this screen
        speaks in a language she never asked for."""
        response = await real_async_client.get(
            '/api/v1/stock-as-of',
            params={'as_of': (_NOW - timedelta(days=400)).isoformat()},
            headers={**_auth(warehouse.user), 'Accept-Language': 'pl'},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()['detail']['code'] == 'STOCK_AS_OF_BEFORE_LEDGER'
        detail = response.json()['detail']['message']
        # The screen prints this sentence two rows under its own footnote
        # about the same boundary, which says "Rejestr ruchów" and formats
        # the day the Polish way — so the refusal has to say both the same,
        # or one screen names one ledger twice.
        assert 'Rejestr ruchów zaczyna się 01.05.2026' in detail
        assert '26.05.2025' in detail
        assert '2026-05-01' not in detail
        assert '2025-05-26' not in detail

    async def test_the_report_says_from_when_it_is_complete(
        self, real_async_client: AsyncClient, warehouse: _Warehouse
    ) -> None:
        response = await _report(real_async_client, warehouse, as_of=_NOW.isoformat())

        body = response.json()
        assert body['complete_from'].startswith('2026-05-01')

    async def test_an_organization_with_no_ledger_gets_no_history(
        self,
        real_async_client: AsyncClient,
        warehouse: _Warehouse,
        real_async_db_session: AsyncSession,
    ) -> None:
        db = real_async_db_session
        quiet_org = Organization(
            name=f'Quiet {uuid4().hex[:6]}', enabled_modules=['core', 'items']
        )
        db.add(quiet_org)
        await db.commit()
        quiet_user = await ModuleTestHelper.create_user_async(
            db, quiet_org, email=f'quiet_{uuid4().hex[:8]}@test.com'
        )
        await db.commit()

        response = await real_async_client.get(
            '/api/v1/stock-as-of',
            params={'as_of': _A_MONTH_AGO.isoformat()},
            headers=_auth(quiet_user),
        )

        # A household records no movements at all (ADR-004). Handing it
        # today's shelves under last month's date would be a fabrication.
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestWhatItWasWorth:
    async def test_the_value_today_is_the_value_the_dashboard_shows(
        self,
        real_async_client: AsyncClient,
        priced_warehouse: _Warehouse,
        real_async_db_session: AsyncSession,
    ) -> None:
        from app.services.analytics._common import stock_value_async

        warehouse = priced_warehouse
        today = await _report(real_async_client, warehouse, as_of=_NOW.isoformat())
        dashboard_value, _source, _excluded, _scope = await stock_value_async(
            real_async_db_session,
            warehouse.org.id,
            [warehouse.aisle_one.id, warehouse.aisle_two.id],
        )

        assert float(today.json()['total_value']) == pytest.approx(dashboard_value)

    async def test_a_month_ago_it_was_worth_the_whole_delivery(
        self, real_async_client: AsyncClient, priced_warehouse: _Warehouse
    ) -> None:
        response = await _report(
            real_async_client, priced_warehouse, as_of=_A_MONTH_AGO.isoformat()
        )

        # Nothing had left yet: twenty kilos at three.
        assert Decimal(response.json()['total_value']) == Decimal('60.00')

    async def test_the_money_leaves_the_api_with_two_places(
        self, real_async_client: AsyncClient, priced_warehouse: _Warehouse
    ) -> None:
        # Twenty kilos at 3.0000 multiply into a figure carrying seven
        # decimals. The screen formats it away; the contract cannot — a
        # reader comparing exports has to be able to tell an exact value
        # from a rounded one, so the money leaves quantized, as a string
        # with exactly the two places money has here.
        response = await _report(
            real_async_client, priced_warehouse, as_of=_NOW.isoformat()
        )
        body = response.json()

        # Fourteen kilos are left, priced from the 3.0000 layer.
        assert body['items'][0]['value'] == '42.00'
        assert body['total_value'] == '42.00'

    async def test_a_product_that_was_never_priced_is_not_worth_zero(
        self,
        real_async_client: AsyncClient,
        priced_warehouse: _Warehouse,
        real_async_db_session: AsyncSession,
    ) -> None:
        # One product has a cost history, the other arrived with nobody
        # naming a price. Its layer holds 0.00 marked unknown: the quantity
        # on it is real, the figure is not a cost.
        db = real_async_db_session
        warehouse = priced_warehouse
        sugar = ProductTemplate(name='Sugar', organization_id=warehouse.org.id)
        db.add(sugar)
        await db.flush()
        await _arrives(db, warehouse, sugar, 3, on=_NOW - timedelta(days=50))
        await db.commit()

        response = await _report(real_async_client, warehouse, as_of=_NOW.isoformat())

        rows = {row['product_name']: row for row in response.json()['items']}
        # 0.00 in that cell is a valuation nobody performed, and it would add
        # up into a total that looks complete.
        assert rows['Sugar']['value'] is None
        assert rows['Rye flour']['value'] is not None

    async def test_an_organization_with_no_cost_history_gets_no_number(
        self, real_async_client: AsyncClient, warehouse: _Warehouse
    ) -> None:
        response = await _report(real_async_client, warehouse, as_of=_NOW.isoformat())

        body = response.json()
        # Two sources of value, named.
        # `purchase_price` is a field on a form today — it cannot say what a
        # shelf was worth last month — and the ledger holds no cost for these
        # twenty kilos, only the quantity nobody priced. So the report says
        # nothing rather than a zero dressed as a valuation.
        assert body['value_source'] is None
        assert body['total_value'] is None
        assert body['items'][0]['value'] is None


class TestPricedAndUnpricedStockOfOneProduct:
    """Goods of one product, some bought at a known price and some not.

    The answer the rest of the valuation gives since unpriced stock stopped
    lending its 0.00 to the average: a product is worth what its priced
    layers still hold. The unpriced remainder takes its turn in the FIFO
    draw — goods leave it like they leave any other receipt — but adds
    nothing to the value, and a product whose shelf holds nothing a cost is
    known for is worth nothing anybody can state. The list footer and the
    dashboard read the same layers the same way.
    """

    async def test_it_is_worth_what_its_priced_part_is_worth(
        self,
        real_async_client: AsyncClient,
        warehouse: _Warehouse,
        real_async_db_session: AsyncSession,
    ) -> None:
        from app.services.analytics._common import stock_value_async

        # The twenty unpriced kilos came first and the six that left a week
        # ago were drawn from them; ten more arrived in between at 4.00.
        db = real_async_db_session
        await _arrives(
            db,
            warehouse,
            warehouse.flour,
            10,
            on=_NOW - timedelta(days=40),
            price='4.00',
        )
        await db.commit()

        response = await _report(real_async_client, warehouse, as_of=_NOW.isoformat())
        dashboard_value, _source, _excluded, _scope = await stock_value_async(
            db, warehouse.org.id, [warehouse.aisle_one.id, warehouse.aisle_two.id]
        )

        body = response.json()
        # Twenty-four kilos on the shelf, ten of them priced.
        assert Decimal(body['items'][0]['quantity']) == Decimal('24.000')
        assert body['items'][0]['value'] == '40.00'
        assert body['total_value'] == '40.00'
        assert float(body['total_value']) == pytest.approx(dashboard_value)

    async def test_once_the_priced_goods_are_gone_the_rest_has_no_value(
        self,
        real_async_client: AsyncClient,
        warehouse: _Warehouse,
        real_async_db_session: AsyncSession,
    ) -> None:
        # Five kilos of salt bought at 3.00 and used up; twenty more arrived
        # afterwards with nobody naming a price, and nothing priced was on the
        # shelf to lend them a rate.
        db = real_async_db_session
        salt = ProductTemplate(name='Salt', organization_id=warehouse.org.id)
        db.add(salt)
        await db.flush()
        bought = await _arrives(
            db, warehouse, salt, 5, on=_NOW - timedelta(days=60), price='3.00'
        )
        await _goes_down_to(db, warehouse, bought, 0, on=_NOW - timedelta(days=55))
        await _arrives(db, warehouse, salt, 20, on=_NOW - timedelta(days=50))
        await db.commit()

        response = await _report(real_async_client, warehouse, as_of=_NOW.isoformat())

        body = response.json()
        rows = {row['product_name']: row for row in body['items']}
        # The salt has a cost history, and none of it is on the shelf: the
        # twenty kilos there are not worth 0.00, they are worth nothing
        # anybody can state.
        assert Decimal(rows['Salt']['quantity']) == Decimal('20.000')
        assert rows['Salt']['value'] is None
        # The organization does keep costs, so the total stands: it adds what
        # is known — nothing, on this day — and the rows say what is not.
        assert body['value_source'] == 'valuation_layers'
        assert body['total_value'] == '0.00'


class TestALayerBookedLateIsDatedEarly:
    """The value side cuts on the date a layer is about, like the count does.

    The quantity already read the date a movement was *about*
    (``coalesce(completed_at, created_at)``); the layers were still filtered
    and ordered by the moment their row was written. So a delivery typed up a
    week after it arrived was invisible to a report on the day it arrived —
    and the same layers, drawn live by the valuation service, were already
    being ordered by their document date. Two readings of one ledger.
    """

    async def test_a_delivery_booked_today_for_last_month_counts_last_month(
        self,
        real_async_client: AsyncClient,
        priced_warehouse: _Warehouse,
        real_async_db_session: AsyncSession,
    ) -> None:
        # Entered long after the goods arrived, and dated to the day they did.
        receipt = await real_async_db_session.scalar(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == priced_warehouse.flour.id,
                StockValuationLayer.direction == 'IN',
            )
        )
        assert receipt is not None
        receipt.created_at = _NOW
        receipt.document_date = (_NOW - timedelta(days=60)).date()
        await real_async_db_session.commit()

        response = await _report(
            real_async_client, priced_warehouse, as_of=_A_MONTH_AGO.isoformat()
        )

        # On the write date this layer does not exist yet a month ago, and
        # the report said the flour was worth nothing anybody could state.
        assert Decimal(response.json()['total_value']) == Decimal('60.00')

    async def test_the_draw_follows_the_document_dates_not_the_entry_order(
        self,
        real_async_client: AsyncClient,
        warehouse: _Warehouse,
        real_async_db_session: AsyncSession,
    ) -> None:
        db = real_async_db_session
        oats = ProductTemplate(name='Oats', organization_id=warehouse.org.id)
        db.add(oats)
        await db.flush()
        # Typed first, about the more recent delivery.
        await _arrives(
            db,
            warehouse,
            oats,
            10,
            on=_NOW - timedelta(days=5),
            price='2.00',
            booked=_NOW - timedelta(days=60),
        )
        # Typed later, about the older one — so it is drained first.
        older = await _arrives(
            db,
            warehouse,
            oats,
            10,
            on=_NOW - timedelta(days=50),
            price='5.00',
            booked=_NOW - timedelta(days=10),
        )
        await _goes_down_to(db, warehouse, older, 0, on=_NOW - timedelta(days=1))
        await db.commit()

        response = await _report(real_async_client, warehouse, as_of=_NOW.isoformat())

        # Ten kilos left, and they were the ones the older document brought
        # in at five. What is left is the cheaper, later delivery: 10 x 2.00.
        # Ordered by entry time the draw takes the wrong layer and the shelf
        # is left worth 50.00.
        rows = {row['product_name']: row for row in response.json()['items']}
        assert rows['Oats']['value'] == '20.00'
        assert Decimal(response.json()['total_value']) == Decimal('20.00')


class TestTheReportLeavesTheScreen:
    async def test_it_prints_a_sheet_that_says_which_two_dates_it_carries(
        self, real_async_client: AsyncClient, warehouse: _Warehouse
    ) -> None:
        response = await real_async_client.get(
            '/api/v1/stock-as-of/export/pdf',
            params={'as_of': _NOW.isoformat()},
            headers=_auth(warehouse.user),
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.headers['content-type'] == 'application/pdf'
        # A printout with no barcode still draws the shared header — the
        # block that carries the codes stands or falls with them.
        assert response.content.startswith(b'%PDF')

    async def test_a_sheet_asked_for_one_place_names_that_place(
        self, real_async_client: AsyncClient, warehouse: _Warehouse
    ) -> None:
        # Asked for one aisle, the sheet read "Stock on hand" and not a word
        # of the aisle: a filed copy looked like the whole warehouse.
        one_aisle = await real_async_client.get(
            '/api/v1/stock-as-of/export/pdf',
            params={
                'as_of': _NOW.isoformat(),
                'location_id': str(warehouse.aisle_one.id),
            },
            headers=_auth(warehouse.user),
        )
        whole = await real_async_client.get(
            '/api/v1/stock-as-of/export/pdf',
            params={'as_of': _NOW.isoformat()},
            headers=_auth(warehouse.user),
        )

        assert one_aisle.status_code == status.HTTP_200_OK, one_aisle.text
        assert 'Location Aisle 1' in _pdf_text(one_aisle.content)
        assert 'Aisle 1' not in _pdf_text(whole.content)

    async def test_the_place_on_the_sheet_is_named_the_way_to_it(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        warehouse: _Warehouse,
    ) -> None:
        # Two shelves may share a name; the way to the shelf is what tells a
        # filed sheet which one it was.
        db = real_async_db_session
        shelf = StorageLocation(
            name='Top shelf',
            organization_id=warehouse.org.id,
            parent_id=warehouse.aisle_one.id,
            created_by=warehouse.user.id,
        )
        db.add(shelf)
        await db.commit()

        response = await real_async_client.get(
            '/api/v1/stock-as-of/export/pdf',
            params={'as_of': _NOW.isoformat(), 'location_id': str(shelf.id)},
            headers=_auth(warehouse.user),
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        text = _pdf_text(response.content)
        assert 'Aisle 1' in text and 'Top shelf' in text

    async def test_the_spreadsheet_writes_the_value_the_screen_shows(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        priced_warehouse: _Warehouse,
    ) -> None:
        # 5 at 19.07 is 95.35 on the screen and on the sheet; the spreadsheet
        # cell held 95.34999999999999.
        import io
        import zipfile

        db = real_async_db_session
        soup = ProductTemplate(
            name='Tomato soup', organization_id=priced_warehouse.org.id
        )
        db.add(soup)
        await db.flush()
        await _arrives(
            db, priced_warehouse, soup, 5, on=_NOW - timedelta(days=30), price='19.07'
        )
        await db.commit()

        screen = await _report(
            real_async_client, priced_warehouse, as_of=_NOW.isoformat()
        )
        sheet = await real_async_client.get(
            '/api/v1/stock-as-of/export/xlsx',
            params={'as_of': _NOW.isoformat()},
            headers=_auth(priced_warehouse.user),
        )

        values = {row['product_name']: row['value'] for row in screen.json()['items']}
        assert values['Tomato soup'] == '95.35'
        assert sheet.status_code == status.HTTP_200_OK, sheet.text
        cells = zipfile.ZipFile(io.BytesIO(sheet.content)).read(
            'xl/worksheets/sheet1.xml'
        )
        assert b'<v>95.35</v>' in cells
        assert b'95.34999' not in cells

    async def test_it_exports_the_same_report_as_a_sheet(
        self, real_async_client: AsyncClient, warehouse: _Warehouse
    ) -> None:
        import io

        import pandas as pd

        response = await real_async_client.get(
            '/api/v1/stock-as-of/export/xlsx',
            params={'as_of': _A_MONTH_AGO.isoformat()},
            headers=_auth(warehouse.user),
        )

        assert response.status_code == status.HTTP_200_OK
        frame = pd.read_excel(io.BytesIO(response.content), engine='openpyxl')
        assert list(frame.columns) == ['Product', 'Quantity', 'Unit', 'Value']
        assert frame.iloc[0]['Quantity'] == 20

    async def test_a_refused_date_is_refused_on_every_way_out(
        self, real_async_client: AsyncClient, warehouse: _Warehouse
    ) -> None:
        too_early = (_NOW - timedelta(days=400)).isoformat()

        for path in (
            '/api/v1/stock-as-of',
            '/api/v1/stock-as-of/export/xlsx',
            '/api/v1/stock-as-of/export/pdf',
        ):
            response = await real_async_client.get(
                path, params={'as_of': too_early}, headers=_auth(warehouse.user)
            )
            # A guess is a guess whichever door it walks out of.
            assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_a_report_too_long_to_print_is_sent_to_the_spreadsheet(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        warehouse: _Warehouse,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.api import stock_as_of as stock_as_of_api

        db = real_async_db_session
        oats = ProductTemplate(name='Oats', organization_id=warehouse.org.id)
        db.add(oats)
        await db.flush()
        await _arrives(db, warehouse, oats, 5, on=_NOW - timedelta(days=30))
        await db.commit()
        monkeypatch.setattr(stock_as_of_api, 'PDF_ROW_LIMIT', 1)

        response = await real_async_client.get(
            '/api/v1/stock-as-of/export/pdf',
            params={'as_of': _NOW.isoformat()},
            headers=_auth(warehouse.user),
        )

        # Two thousand pages took ten minutes and outlived the worker's
        # timeout: the reader got a 502 and no word about why.
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        detail = response.json()['detail']
        assert detail['code'] == 'STOCK_AS_OF_PDF_TOO_MANY'
        assert '2' in detail['message']
        assert 'spreadsheet' in detail['message']

        sheet = await real_async_client.get(
            '/api/v1/stock-as-of/export/xlsx',
            params={'as_of': _NOW.isoformat()},
            headers=_auth(warehouse.user),
        )
        assert sheet.status_code == status.HTTP_200_OK

        monkeypatch.setattr(stock_as_of_api, 'PDF_ROW_LIMIT', 2)
        at_the_limit = await real_async_client.get(
            '/api/v1/stock-as-of/export/pdf',
            params={'as_of': _NOW.isoformat()},
            headers=_auth(warehouse.user),
        )
        assert at_the_limit.status_code == status.HTTP_200_OK
        assert 'Oats' in _pdf_text(at_the_limit.content)


class TestTheValueTheProfileHidesDoesNotLeaveInAFile:
    """A file is a screen the reader forwards.

    The organization's profile hides its stock value — a home inventory
    keeps no cost ledger for the figure to stand on — and the report as a
    file used to state the Value column anyway. What the profile withholds
    on the screen it withholds in the spreadsheet and on the printed sheet.
    """

    async def test_hidden_value_means_no_value_column_in_the_spreadsheet(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        priced_warehouse: _Warehouse,
    ) -> None:
        import io

        import pandas as pd

        await _set_show_inventory_value(real_async_db_session, priced_warehouse, False)

        response = await real_async_client.get(
            '/api/v1/stock-as-of/export/xlsx',
            params={'as_of': _NOW.isoformat()},
            headers=_auth(priced_warehouse.user),
        )

        assert response.status_code == status.HTTP_200_OK
        frame = pd.read_excel(io.BytesIO(response.content), engine='openpyxl')
        # The goods are still there to count; their worth is not stated.
        assert list(frame.columns) == ['Product', 'Quantity', 'Unit']

    async def test_hidden_value_means_no_value_column_nor_total_on_the_printed_sheet(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        priced_warehouse: _Warehouse,
    ) -> None:
        await _set_show_inventory_value(real_async_db_session, priced_warehouse, False)

        response = await real_async_client.get(
            '/api/v1/stock-as-of/export/pdf',
            params={'as_of': _NOW.isoformat()},
            headers=_auth(priced_warehouse.user),
        )

        assert response.status_code == status.HTTP_200_OK
        text = _pdf_text(response.content)
        assert 'Rye flour' in text
        # The column header is drawn uppercase by the stylesheet.
        assert 'value' not in text.lower()
        assert 'total' not in text.lower()

    async def test_hidden_value_means_the_no_cost_note_is_gone_too(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        warehouse: _Warehouse,
    ) -> None:
        unpriced = await real_async_client.get(
            '/api/v1/stock-as-of/export/pdf',
            params={'as_of': _NOW.isoformat()},
            headers=_auth(warehouse.user),
        )
        # The note is a statement about the value the sheet would have held;
        # it belongs to the figure, not to the count.
        assert 'no cost history' in _pdf_text(unpriced.content)

        await _set_show_inventory_value(real_async_db_session, warehouse, False)

        response = await real_async_client.get(
            '/api/v1/stock-as-of/export/pdf',
            params={'as_of': _NOW.isoformat()},
            headers=_auth(warehouse.user),
        )

        assert 'no cost history' not in _pdf_text(response.content)

    async def test_turning_the_switch_on_states_the_value_in_both_files(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        priced_warehouse: _Warehouse,
    ) -> None:
        import io

        import pandas as pd

        await _set_show_inventory_value(real_async_db_session, priced_warehouse, True)

        spread_sheet = await real_async_client.get(
            '/api/v1/stock-as-of/export/xlsx',
            params={'as_of': _NOW.isoformat()},
            headers=_auth(priced_warehouse.user),
        )
        frame = pd.read_excel(io.BytesIO(spread_sheet.content), engine='openpyxl')
        assert list(frame.columns) == ['Product', 'Quantity', 'Unit', 'Value']

        printed_sheet = await real_async_client.get(
            '/api/v1/stock-as-of/export/pdf',
            params={'as_of': _NOW.isoformat()},
            headers=_auth(priced_warehouse.user),
        )
        text = _pdf_text(printed_sheet.content)
        assert 'value' in text.lower()
        assert 'total' in text.lower()


class TestADateWithoutATime:
    """The name invites a bare date, so a bare date has to be an answer.

    The screen sends a full timestamp with an offset, which is why nobody
    noticed: every other caller — the auditor with a script, the accountant
    with a spreadsheet — types the day and gets back a comparison between a
    date with an offset and one without, which Python refuses with a 500.
    """

    async def test_a_bare_date_means_the_end_of_that_day(
        self, real_async_client: AsyncClient, warehouse: _Warehouse
    ) -> None:
        response = await _report(
            real_async_client, warehouse, as_of=_A_WEEK_AGO.date().isoformat()
        )

        assert response.status_code == status.HTTP_200_OK
        rows = response.json()['items']
        # The six left at noon that day. "Stock as of the 23rd" is the shelf
        # when the 23rd was over — the midnight reading would report goods
        # that were gone by the time anyone closed the books on that date.
        assert Decimal(rows[0]['quantity']) == Decimal('14.000')

    async def test_a_bare_date_is_answered_on_every_way_out(
        self, real_async_client: AsyncClient, warehouse: _Warehouse
    ) -> None:
        bare_date = _NOW.date().isoformat()

        for path in (
            '/api/v1/stock-as-of',
            '/api/v1/stock-as-of/export/xlsx',
            '/api/v1/stock-as-of/export/pdf',
        ):
            response = await real_async_client.get(
                path, params={'as_of': bare_date}, headers=_auth(warehouse.user)
            )
            assert response.status_code == status.HTTP_200_OK, path

    async def test_a_timestamp_without_an_offset_is_read_as_utc(
        self, real_async_client: AsyncClient, warehouse: _Warehouse
    ) -> None:
        response = await _report(
            real_async_client,
            warehouse,
            as_of=_NOW.replace(tzinfo=None).isoformat(),
        )

        assert response.status_code == status.HTTP_200_OK


class TestALargeWarehouseIsReadAPageAtATime:
    """A hundred thousand products do not travel to the screen in one answer.

    The screen reads one page of rows; what it prints under them — the value
    of the whole warehouse and how many products nobody priced — is about
    every row, so the page carries those figures for the whole report. The
    files are the report in the reader's hands and carry every row.
    """

    async def _three_products(self, db: AsyncSession, warehouse: _Warehouse) -> None:
        # Rye flour is priced by the fixture; barley at 2.00; sugar unpriced.
        barley = ProductTemplate(name='Barley', organization_id=warehouse.org.id)
        sugar = ProductTemplate(name='Sugar', organization_id=warehouse.org.id)
        db.add_all([barley, sugar])
        await db.flush()
        await _arrives(
            db, warehouse, barley, 5, on=_NOW - timedelta(days=50), price='2.00'
        )
        await _arrives(db, warehouse, sugar, 3, on=_NOW - timedelta(days=50))
        await db.commit()

    async def test_a_page_carries_the_figures_of_the_whole_report(
        self,
        real_async_client: AsyncClient,
        priced_warehouse: _Warehouse,
        real_async_db_session: AsyncSession,
    ) -> None:
        await self._three_products(real_async_db_session, priced_warehouse)

        first = await _report(
            real_async_client, priced_warehouse, as_of=_NOW.isoformat(), limit=1
        )
        second = await _report(
            real_async_client,
            priced_warehouse,
            as_of=_NOW.isoformat(),
            limit=1,
            offset=1,
        )

        assert first.status_code == status.HTTP_200_OK, first.text
        body = first.json()
        # The rows in name order, one per page.
        assert [row['product_name'] for row in body['items']] == ['Barley']
        assert [row['product_name'] for row in second.json()['items']] == ['Rye flour']
        assert body['total'] == 3
        assert body['limit'] == 1
        assert body['offset'] == 0
        assert body['has_more'] is True
        # 14 kg of flour at 3.00 and 5 of barley at 2.00, whichever page.
        assert body['total_value'] == '52.00'
        assert second.json()['total_value'] == '52.00'
        assert body['unpriced'] == 1

    async def test_the_files_carry_every_row(
        self,
        real_async_client: AsyncClient,
        priced_warehouse: _Warehouse,
        real_async_db_session: AsyncSession,
    ) -> None:
        import io

        import pandas as pd

        await self._three_products(real_async_db_session, priced_warehouse)

        response = await real_async_client.get(
            '/api/v1/stock-as-of/export/xlsx',
            params={'as_of': _NOW.isoformat(), 'limit': 1},
            headers=_auth(priced_warehouse.user),
        )

        assert response.status_code == status.HTTP_200_OK
        frame = pd.read_excel(io.BytesIO(response.content), engine='openpyxl')
        assert list(frame['Product']) == ['Barley', 'Rye flour', 'Sugar']


class TestModuleDataStaysOutAsInTheLists:
    """The report leaves out a module's records the way the products list does.

    A household with equipment switched on found its family laptop listed
    among the pantry on the stock-on-a-date sheet, while the organization's
    setting keeps module data out of general lists and the products list
    left the laptop out.
    """

    async def _laptop(
        self, db: AsyncSession, warehouse: _Warehouse, price: str | None = None
    ) -> None:
        from app.core.module_scope import get_claimed_context_tags
        from app.models.category import Category

        tag = sorted(get_claimed_context_tags())[0]
        category = Category(
            organization_id=warehouse.org.id, name='Laptop', context_tag=tag
        )
        db.add(category)
        laptop = ProductTemplate(name='Family laptop', organization_id=warehouse.org.id)
        db.add(laptop)
        await db.flush()
        record = await _arrives(db, warehouse, laptop, 1, on=_A_MONTH_AGO, price=price)
        record.category_id = category.id
        await db.commit()

    async def test_a_module_record_is_not_on_the_sheet(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        warehouse: _Warehouse,
    ) -> None:
        await self._laptop(real_async_db_session, warehouse)

        response = await _report(real_async_client, warehouse, as_of=_NOW.isoformat())

        assert response.status_code == status.HTTP_200_OK
        assert [r['product_name'] for r in response.json()['items']] == ['Rye flour']

    async def test_it_is_there_when_the_organization_shows_module_data(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        warehouse: _Warehouse,
    ) -> None:
        await self._laptop(real_async_db_session, warehouse)
        warehouse.org.settings = {
            **(warehouse.org.settings or {}),
            'show_module_data': True,
        }
        real_async_db_session.add(warehouse.org)
        await real_async_db_session.commit()

        response = await _report(real_async_client, warehouse, as_of=_NOW.isoformat())

        assert sorted(r['product_name'] for r in response.json()['items']) == [
            'Family laptop',
            'Rye flour',
        ]

    async def test_the_ledger_value_leaves_the_laptop_out_too(
        self, real_async_db_session: AsyncSession, warehouse: _Warehouse
    ) -> None:
        """The cost ledger knows products: the laptop's product goes as a whole.

        The pantry's flour was never priced; the laptop was, at 3000. The
        statistics' value read the ledger whole and showed the laptop's 3000
        as the household's stock. Without it nothing on hand carries a cost,
        so the value is unknown rather than 0.00 beside unpriced receipts.
        """
        from app.services.analytics.overview import get_overview_async

        await self._laptop(real_async_db_session, warehouse, price='3000')

        overview = await get_overview_async(real_async_db_session, warehouse.org.id)

        assert overview.value_source == 'valuation_layers'
        assert overview.total_value == 0
        assert overview.value_known is False
        assert overview.unvalued_stock_count == 1
