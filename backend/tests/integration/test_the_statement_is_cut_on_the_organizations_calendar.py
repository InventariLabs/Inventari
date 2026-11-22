"""A bare date is a day on the organization's calendar, not on the server's.

An organization at UTC+1 books a receipt at 00:30 on the 11th local — 23:30
UTC on the 10th. Cut at midnight UTC, that receipt fell into the opening of
the 11th and into the closing of the 10th, and the ledger was said to start
a day before anything had happened. The stock-on-a-date report and the value
statement share one resolver, so one test fixture covers both.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token
from tests.integration._shelf import put_on_shelf

pytestmark = pytest.mark.integration

#: Warsaw stands at UTC+1 in January.
_ZONE = 'Europe/Warsaw'
_EARLIER = datetime(2026, 1, 9, 12, 0, tzinfo=UTC)
#: 00:30 on the 11th in Warsaw.
_LOCAL_HALF_PAST_MIDNIGHT = datetime(2026, 1, 10, 23, 30, tzinfo=UTC)


async def _dated(db: AsyncSession, since: datetime, day: datetime) -> None:
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


async def _books(db: AsyncSession, *, earlier: bool) -> tuple[User, dict[str, str]]:
    """Ten flour at 2.00 on the 9th (when *earlier*), five sugar at 4.00 at
    00:30 on the 11th local."""
    org = Organization(
        name=f'Calendar {uuid4().hex[:6]}',
        timezone=_ZONE,
        enabled_modules=['core', 'items', 'locations', 'warehouse'],
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'calendar_{uuid4().hex[:8]}@test.com'
    )
    await db.commit()
    shelf = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(shelf)
    await db.flush()
    location = StorageLocation(
        name='Aisle 1',
        organization_id=org.id,
        storage_type_id=shelf.id,
        created_by=user.id,
    )
    flour = ProductTemplate(name='Rye flour', organization_id=org.id)
    sugar = ProductTemplate(name='Cane sugar', organization_id=org.id)
    db.add_all([location, flour, sugar])
    await db.flush()

    if earlier:
        mark = datetime.now(UTC) - timedelta(minutes=1)
        await put_on_shelf(db, user, flour, location.id, 10, purchase_price='2.00')
        await _dated(db, mark, _EARLIER)
    mark = datetime.now(UTC) - timedelta(minutes=1)
    await put_on_shelf(db, user, sugar, location.id, 5, purchase_price='4.00')
    await _dated(db, mark, _LOCAL_HALF_PAST_MIDNIGHT)
    await db.commit()
    headers = {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }
    return user, headers


class TestTheDayIsTheOrganizationsDay:
    async def test_a_receipt_after_local_midnight_is_that_days_not_the_openings(
        self, real_async_client: AsyncClient, real_async_db_session: AsyncSession
    ) -> None:
        _, headers = await _books(real_async_db_session, earlier=True)

        response = await real_async_client.get(
            '/api/v1/stock-value-movement',
            params={'date_from': '2026-01-11', 'date_to': '2026-01-11'},
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        body = response.json()
        assert Decimal(body['opening_value']) == Decimal('20.00')
        assert Decimal(body['receipts']) == Decimal('20.00')
        assert Decimal(body['closing_value']) == Decimal('40.00')

    async def test_the_stock_on_a_date_ends_at_the_organizations_midnight(
        self, real_async_client: AsyncClient, real_async_db_session: AsyncSession
    ) -> None:
        _, headers = await _books(real_async_db_session, earlier=True)

        response = await real_async_client.get(
            '/api/v1/stock-as-of',
            params={'as_of': '2026-01-10'},
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        # The sugar came in on the 11th where the organization lives.
        assert Decimal(response.json()['total_value']) == Decimal('20.00')

    async def test_the_refusal_names_the_ledgers_first_day_on_that_calendar(
        self, real_async_client: AsyncClient, real_async_db_session: AsyncSession
    ) -> None:
        _, headers = await _books(real_async_db_session, earlier=False)

        response = await real_async_client.get(
            '/api/v1/stock-as-of',
            params={'as_of': '2026-01-10', 'lang': 'en'},
            headers=headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        message = str(response.json()['detail'])
        assert 'starts on Jan 11, 2026' in message
        assert 'report for Jan 10, 2026' in message


class TestThePeriodOpensOnADayItCanReport:
    async def test_without_a_first_day_it_opens_the_day_after_the_ledger_began(
        self, real_async_client: AsyncClient, real_async_db_session: AsyncSession
    ) -> None:
        _, headers = await _books(real_async_db_session, earlier=True)

        # The month of the 11th starts on the 1st, before anything was known.
        response = await real_async_client.get(
            '/api/v1/stock-value-movement',
            params={'date_to': '2026-01-11'},
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        body = response.json()
        assert body['date_from'] == '2026-01-10'
        assert Decimal(body['opening_value']) == Decimal('20.00')
        assert Decimal(body['closing_value']) == Decimal('40.00')

    async def test_the_file_is_named_for_the_period_it_opened_on(
        self, real_async_client: AsyncClient, real_async_db_session: AsyncSession
    ) -> None:
        _, headers = await _books(real_async_db_session, earlier=True)

        response = await real_async_client.get(
            '/api/v1/stock-value-movement/export/xlsx',
            params={'date_to': '2026-01-11'},
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert (
            'value_movement_2026-01-10_2026-01-11'
            in response.headers['content-disposition']
        )

    async def test_on_the_ledgers_first_day_the_refusal_names_when_a_statement_can_open(
        self, real_async_client: AsyncClient, real_async_db_session: AsyncSession
    ) -> None:
        _, headers = await _books(real_async_db_session, earlier=False)

        response = await real_async_client.get(
            '/api/v1/stock-value-movement',
            params={'date_to': '2026-01-11', 'lang': 'en'},
            headers=headers,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
        message = str(response.json()['detail'])
        # The ledger began on the 11th, so the first statement can open on
        # the 12th; the evening before the 11th, which nobody asked for, is
        # not mentioned.
        assert 'starts on Jan 11, 2026' in message
        assert 'start on Jan 12, 2026' in message
        assert 'Jan 10' not in message
