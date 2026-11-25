"""What the stock was worth when a period opened, what moved it, and what it was worth when it closed.

The question an accountant puts to a warehouse: how much was it worth on
the first day, what happened to it, how much was it worth on the last.
The first and last halves are the stock-on-a-date report; this one adds the
movement between them, read from the cost layers' direction and reason.

Two promises are pinned here rather than left to the eye:

* the opening plus every movement is the closing, to the cent — the
  statement adds up;
* the closing is the *same figure* the stock-on-a-date report gives for the
  last day, because it is that report, not a second implementation of it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.public_api import core_api
from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.warehouse.models import Document, DocumentLine
from app.schemas.item import ItemConsumeRequest, ItemDiscardRequest
from app.services.items import consume_item, discard_item
from app.services.token_service import create_access_token
from tests.integration._shelf import put_on_shelf

pytestmark = pytest.mark.integration


def _today() -> datetime:
    """Today, read when the test runs, so a run that crosses midnight stays consistent."""
    return datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)


def _days_ago(days: int) -> datetime:
    return _today() - timedelta(days=days)


#: The period under test, and the dates around it.
_BEFORE = 20
_FROM = 10
_INSIDE = 5
_TO = 2


class _Books:
    org: Organization
    user: User
    location: StorageLocation
    flour: ProductTemplate
    sugar: ProductTemplate
    flour_record: Item
    sugar_record: Item


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


async def _dated(db: AsyncSession, since: datetime, day: datetime) -> None:
    """Date everything the ledger wrote after *since* to *day*.

    The fixture writes through the application's own doors, which stamp
    today; a movement is about ``completed_at`` and a cost layer about its
    write date when no document stands behind it.
    """
    for move in await db.scalars(
        select(StockMove).where(
            func.coalesce(StockMove.completed_at, StockMove.created_at) > since
        )
    ):
        move.completed_at = day
    for layer in await db.scalars(
        select(StockValuationLayer).where(StockValuationLayer.created_at > since)
    ):
        layer.created_at = day
    await db.flush()


async def _stocked(db: AsyncSession, *, price: bool = True) -> _Books:
    """Ten flour at 2.00 come in before the period.

    Inside it five sugar come in at 4.00, four flour are used and two are
    thrown away; after it one sugar is used.
    """
    books = _Books()
    books.org = Organization(
        name=f'Period {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'warehouse'],
    )
    db.add(books.org)
    await db.commit()
    await db.refresh(books.org)
    books.user = await ModuleTestHelper.create_user_async(
        db, books.org, email=f'period_{uuid4().hex[:8]}@test.com'
    )
    await db.commit()

    shelf = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(shelf)
    await db.flush()
    books.location = StorageLocation(
        name='Aisle 1',
        organization_id=books.org.id,
        storage_type_id=shelf.id,
        created_by=books.user.id,
    )
    books.flour = ProductTemplate(name='Rye flour', organization_id=books.org.id)
    books.sugar = ProductTemplate(name='Cane sugar', organization_id=books.org.id)
    db.add_all([books.location, books.flour, books.sugar])
    await db.flush()

    keeper = UserContextDTO(id=books.user.id, organization_id=books.org.id)

    mark = datetime.now(UTC) - timedelta(minutes=1)
    books.flour_record = await put_on_shelf(
        db,
        books.user,
        books.flour,
        books.location.id,
        10,
        purchase_price='2.00' if price else None,
    )
    await _dated(db, mark, _days_ago(_BEFORE))

    mark = datetime.now(UTC) - timedelta(minutes=1)
    books.sugar_record = await put_on_shelf(
        db,
        books.user,
        books.sugar,
        books.location.id,
        5,
        purchase_price='4.00' if price else None,
    )
    await consume_item(
        db, books.flour_record, ItemConsumeRequest(quantity=Decimal('4')), keeper
    )
    await discard_item(
        db,
        books.flour_record,
        ItemDiscardRequest(quantity=Decimal('2'), reason='DAMAGED'),
        keeper,
    )
    await _dated(db, mark, _days_ago(_INSIDE))

    await consume_item(
        db, books.sugar_record, ItemConsumeRequest(quantity=Decimal('1')), keeper
    )
    await db.commit()
    return books


@pytest.fixture
async def books(real_async_db_session: AsyncSession) -> _Books:
    return await _stocked(real_async_db_session)


async def _period(
    client: AsyncClient,
    books: _Books,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    path: str = '/api/v1/stock-value-movement',
):
    return await client.get(
        path,
        params={
            'date_from': (date_from or _days_ago(_FROM).date()).isoformat(),
            'date_to': (date_to or _days_ago(_TO).date()).isoformat(),
        },
        headers=_auth(books.user),
    )


async def _dispatch_against_a_document(db: AsyncSession, books: _Books) -> None:
    """Ship three sugar at 4.00 against a document line, inside the period.

    The layer is written the way a delivery writes it: no reason, but the
    line it was posted for.
    """
    document = Document(
        organization_id=books.org.id,
        type='OUT',
        number=f'OUT/{uuid4().hex[:6]}',
        created_by=books.user.id,
    )
    line = DocumentLine(
        product_template_id=books.sugar.id,
        quantity=Decimal('3'),
        expected_quantity=Decimal('3'),
        done_quantity=Decimal('3'),
        line_number=1,
    )
    document.lines.append(line)
    db.add(document)
    await db.flush()
    db.add(
        StockValuationLayer(
            organization_id=books.org.id,
            product_template_id=books.sugar.id,
            document_line_id=line.id,
            direction='OUT',
            quantity=Decimal('3'),
            remaining_qty=Decimal('0'),
            unit_cost=Decimal('4.00'),
            total_value=Decimal('12.00'),
            created_at=_days_ago(_INSIDE),
        )
    )
    await db.commit()


class TestThePeriodStatement:
    async def test_a_dispatch_against_a_document_is_a_line_of_its_own(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        books: _Books,
    ) -> None:
        await _dispatch_against_a_document(real_async_db_session, books)

        body = (await _period(real_async_client, books)).json()

        assert Decimal(body['dispatched']) == Decimal('-12.00')
        # It is not hidden among the issues nobody can tell apart.
        assert Decimal(body['other_issues']) == Decimal('0.00')
        assert Decimal(body['used']) == Decimal('-8.00')

    async def test_it_says_what_opened_moved_and_closed(
        self, real_async_client: AsyncClient, books: _Books
    ) -> None:
        response = await _period(real_async_client, books)

        assert response.status_code == status.HTTP_200_OK, response.text
        body = response.json()
        assert body['value_source'] == 'valuation_layers'
        # Ten flour at 2.00 stood there when the period opened.
        assert Decimal(body['opening_value']) == Decimal('20.00')
        # Five sugar at 4.00 came in.
        assert Decimal(body['receipts']) == Decimal('20.00')
        # Four flour were used and two thrown away, each at what it cost.
        assert Decimal(body['used']) == Decimal('-8.00')
        assert Decimal(body['disposed']) == Decimal('-4.00')
        # The sugar used after the period belongs to no line of it.
        assert Decimal(body['closing_value']) == Decimal('28.00')
        assert Decimal(body['other_changes']) == Decimal('0.00')

    async def test_the_opening_plus_the_movements_is_the_closing_to_the_cent(
        self, real_async_client: AsyncClient, books: _Books
    ) -> None:
        body = (await _period(real_async_client, books)).json()

        movements = sum(
            Decimal(body[key])
            for key in (
                'receipts',
                'internal_receipts',
                'used',
                'disposed',
                'dispatched',
                'other_issues',
                'work_in_progress_change',
                'other_changes',
            )
        )
        assert Decimal(body['opening_value']) + movements == Decimal(
            body['closing_value']
        )

    async def test_the_closing_is_the_figure_of_the_stock_on_that_day(
        self, real_async_client: AsyncClient, books: _Books
    ) -> None:
        last_day = _days_ago(_TO).date()
        statement = (await _period(real_async_client, books, date_to=last_day)).json()
        on_the_day = await real_async_client.get(
            '/api/v1/stock-as-of',
            params={'as_of': last_day.isoformat()},
            headers=_auth(books.user),
        )

        assert on_the_day.status_code == status.HTTP_200_OK
        assert Decimal(statement['closing_value']) == Decimal(
            on_the_day.json()['total_value']
        )

    async def test_the_opening_is_the_figure_of_the_stock_the_day_before(
        self, real_async_client: AsyncClient, books: _Books
    ) -> None:
        first_day = _days_ago(_FROM).date()
        statement = (
            await _period(real_async_client, books, date_from=first_day)
        ).json()
        evening_before = await real_async_client.get(
            '/api/v1/stock-as-of',
            params={'as_of': (first_day - timedelta(days=1)).isoformat()},
            headers=_auth(books.user),
        )

        assert Decimal(statement['opening_value']) == Decimal(
            evening_before.json()['total_value']
        )

    async def test_a_later_movement_stays_out_of_the_period(
        self, real_async_client: AsyncClient, books: _Books
    ) -> None:
        # Today one sugar was used; a period ending today takes it in.
        body = (await _period(real_async_client, books, date_to=_today().date())).json()

        assert Decimal(body['used']) == Decimal('-12.00')
        assert Decimal(body['closing_value']) == Decimal('24.00')


class TestTheStatementRefusesWhatItCannotSay:
    async def test_a_period_that_opens_before_the_ledger_names_its_boundary(
        self, real_async_client: AsyncClient, books: _Books
    ) -> None:
        response = await _period(
            real_async_client, books, date_from=_days_ago(_BEFORE + 30).date()
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()['detail']['code'] == 'STOCK_AS_OF_BEFORE_LEDGER'

    async def test_a_period_cannot_end_before_it_starts(
        self, real_async_client: AsyncClient, books: _Books
    ) -> None:
        response = await _period(
            real_async_client,
            books,
            date_from=_days_ago(_TO).date(),
            date_to=_days_ago(_FROM).date(),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_an_organization_with_no_cost_history_gets_no_figures(
        self, real_async_client: AsyncClient, real_async_db_session: AsyncSession
    ) -> None:
        unpriced = await _stocked(real_async_db_session, price=False)

        response = await _period(real_async_client, unpriced)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body['value_source'] is None
        for key in ('opening_value', 'receipts', 'used', 'closing_value'):
            assert body[key] is None


class TestTheStatementAsASheet:
    async def test_it_exports_to_a_spreadsheet_that_adds_up(
        self, real_async_client: AsyncClient, books: _Books
    ) -> None:
        response = await _period(
            real_async_client, books, path='/api/v1/stock-value-movement/export/xlsx'
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        sheet = load_workbook(BytesIO(response.content)).active
        rows = {row[0]: row[1] for row in sheet.iter_rows(min_row=2, values_only=True)}
        assert rows['Opening value'] == pytest.approx(20.0)
        assert rows['Closing value'] == pytest.approx(28.0)
        assert rows['Used'] == pytest.approx(-8.0)

    async def test_where_the_profile_hides_the_value_the_file_does_not_state_it(
        self,
        real_async_client: AsyncClient,
        real_async_db_session: AsyncSession,
        books: _Books,
    ) -> None:
        await core_api.settings.set_bulk_async(
            real_async_db_session,
            books.org.id,
            'stats',
            {'show_inventory_value': False},
        )
        await real_async_db_session.commit()

        response = await _period(
            real_async_client, books, path='/api/v1/stock-value-movement/export/xlsx'
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()['detail']['code'] == 'STOCK_VALUE_HIDDEN'

    async def test_nobody_signed_out_reads_the_statement(
        self, real_async_client: AsyncClient
    ) -> None:
        response = await real_async_client.get(
            '/api/v1/stock-value-movement',
            params={'date_from': '2026-01-01', 'date_to': '2026-01-31'},
        )

        assert response.status_code in {
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        }
