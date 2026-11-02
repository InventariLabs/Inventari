"""The person who needs the ledger most does not use the application.

An accountant reconciling a quarter, an auditor sampling movements, a
warehouse manager building a case for a supplier — none of them will page
through a screen. They want the rows they asked for, in a sheet, and they
want the filters they set on the screen to still apply.

So the export is the same question as the list, answered in one file: the
same filters, the same order, no pagination — and a refusal, with a reason,
when the answer is too big to build in one go.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pandas as pd
import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.services.token_service import create_access_token

_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


def _auth(user: User) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {create_access_token(data={"sub": str(user.id)})}'
    }


class _Sheet:
    def __init__(self) -> None:
        self.org: Organization
        self.user: User
        self.aisle: StorageLocation
        self.yard: StorageLocation
        self.flour: ProductTemplate


@pytest.fixture
async def sheet(real_async_db_session: AsyncSession) -> _Sheet:
    db = real_async_db_session
    fixture = _Sheet()

    fixture.org = Organization(
        name=f'Ledger Export {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations'],
    )
    db.add(fixture.org)
    await db.commit()
    await db.refresh(fixture.org)

    fixture.user = await ModuleTestHelper.create_user_async(
        db, fixture.org, email=f'books_{uuid4().hex[:8]}@test.com'
    )
    fixture.user.full_name = 'Hanna Kowal'
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

    fixture.aisle = _location('Aisle 1')
    fixture.yard = _location('Yard')
    await db.flush()

    # A product whose name a spreadsheet would run rather than print.
    fixture.flour = ProductTemplate(name='=cmd|/c calc', organization_id=fixture.org.id)
    db.add(fixture.flour)
    await db.flush()

    db.add_all(
        [
            StockMove(
                organization_id=fixture.org.id,
                product_template_id=fixture.flour.id,
                to_location_id=fixture.aisle.id,
                quantity=Decimal('10.000'),
                created_by=fixture.user.id,
                completed_at=_NOW - timedelta(days=3),
                reference_type='document',
                reference_id=uuid4(),
            ),
            StockMove(
                organization_id=fixture.org.id,
                product_template_id=fixture.flour.id,
                from_location_id=fixture.aisle.id,
                quantity=Decimal('4.000'),
                created_by=fixture.user.id,
                completed_at=_NOW - timedelta(days=1),
            ),
            StockMove(
                organization_id=fixture.org.id,
                product_template_id=fixture.flour.id,
                to_location_id=fixture.yard.id,
                quantity=Decimal('2.000'),
                created_by=fixture.user.id,
                completed_at=_NOW,
            ),
        ]
    )
    await db.commit()
    return fixture


def _read(response) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(response.content), engine='openpyxl')


class TestTheLedgerBecomesASheet:
    async def test_it_answers_with_a_spreadsheet(
        self, real_async_client: AsyncClient, sheet: _Sheet
    ) -> None:
        response = await real_async_client.get(
            '/api/v1/stock-moves/export/xlsx', headers=_auth(sheet.user)
        )

        assert response.status_code == status.HTTP_200_OK
        assert 'spreadsheetml' in response.headers['content-type']
        assert 'attachment' in response.headers['content-disposition']

    async def test_every_movement_is_a_row(
        self, real_async_client: AsyncClient, sheet: _Sheet
    ) -> None:
        response = await real_async_client.get(
            '/api/v1/stock-moves/export/xlsx', headers=_auth(sheet.user)
        )

        frame = _read(response)
        assert len(frame) == 3

    async def test_the_row_reads_in_names_not_keys(
        self, real_async_client: AsyncClient, sheet: _Sheet
    ) -> None:
        response = await real_async_client.get(
            '/api/v1/stock-moves/export/xlsx', headers=_auth(sheet.user)
        )

        frame = _read(response)
        # The sheet is read by somebody who has never seen the application.
        assert 'Product' in frame.columns
        assert 'From' in frame.columns
        assert 'To' in frame.columns
        assert set(frame['Who'].dropna()) == {'Hanna Kowal'}

    async def test_a_product_name_is_not_run_as_a_formula(
        self, real_async_client: AsyncClient, sheet: _Sheet
    ) -> None:
        response = await real_async_client.get(
            '/api/v1/stock-moves/export/xlsx', headers=_auth(sheet.user)
        )

        frame = _read(response)
        # Byte-identical, and typed as text so the spreadsheet prints it.
        assert set(frame['Product']) == {'=cmd|/c calc'}


class TestTheSheetAnswersTheSameQuestion:
    async def test_the_filters_from_the_screen_still_apply(
        self, real_async_client: AsyncClient, sheet: _Sheet
    ) -> None:
        response = await real_async_client.get(
            '/api/v1/stock-moves/export/xlsx',
            params={'location_id': str(sheet.yard.id)},
            headers=_auth(sheet.user),
        )

        frame = _read(response)
        assert len(frame) == 1
        assert frame.iloc[0]['To'] == 'Yard'

    async def test_direction_narrows_the_sheet_too(
        self, real_async_client: AsyncClient, sheet: _Sheet
    ) -> None:
        response = await real_async_client.get(
            '/api/v1/stock-moves/export/xlsx',
            params={'direction': 'out'},
            headers=_auth(sheet.user),
        )

        frame = _read(response)
        assert len(frame) == 1

    async def test_an_empty_answer_is_still_a_sheet(
        self, real_async_client: AsyncClient, sheet: _Sheet
    ) -> None:
        response = await real_async_client.get(
            '/api/v1/stock-moves/export/xlsx',
            params={'reference_type': 'nothing-writes-this'},
            headers=_auth(sheet.user),
        )

        assert response.status_code == status.HTTP_200_OK
        frame = _read(response)
        # A file with headers and no rows is an answer; a 404 would look
        # like the export is broken.
        assert len(frame) == 0
        assert 'Product' in frame.columns


class TestTheSheetSaysNoRatherThanLie:
    async def test_too_many_rows_is_refused_with_a_reason(
        self, real_async_client: AsyncClient, sheet: _Sheet, monkeypatch
    ) -> None:
        from app.api import stock_moves as stock_moves_api

        monkeypatch.setattr(stock_moves_api, 'EXPORT_ROW_LIMIT', 2)

        response = await real_async_client.get(
            '/api/v1/stock-moves/export/xlsx', headers=_auth(sheet.user)
        )

        # Silently exporting the first two of three rows is the one thing an
        # accountant must never be handed.
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        detail = response.json()['detail']
        assert detail['code'] == 'STOCK_MOVES_EXPORT_TOO_MANY'
        assert '3' in detail['message']
        assert '2' in detail['message']


class TestTheSheetKeepsTheReadersClock:
    async def test_it_uses_the_time_zone_the_reader_is_looking_at(
        self, real_async_client: AsyncClient, sheet: _Sheet
    ) -> None:
        utc = await real_async_client.get(
            '/api/v1/stock-moves/export/xlsx', headers=_auth(sheet.user)
        )
        warsaw = await real_async_client.get(
            '/api/v1/stock-moves/export/xlsx',
            params={'tz': 'Europe/Warsaw'},
            headers=_auth(sheet.user),
        )

        # Same rows, two clocks: a sheet built in UTC disagrees with every
        # screen the reader compares it against.
        offset = _read(warsaw)['When'].iloc[0] - _read(utc)['When'].iloc[0]
        assert offset == pd.Timedelta(hours=2)

    async def test_a_zone_nobody_has_heard_of_is_not_an_error(
        self, real_async_client: AsyncClient, sheet: _Sheet
    ) -> None:
        response = await real_async_client.get(
            '/api/v1/stock-moves/export/xlsx',
            params={'tz': 'Mars/Olympus_Mons'},
            headers=_auth(sheet.user),
        )

        # Falling back to the organization's clock beats refusing to export.
        assert response.status_code == status.HTTP_200_OK
        assert len(_read(response)) == 3
