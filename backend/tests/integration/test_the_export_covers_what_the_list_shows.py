"""The export covers what the list shows, and says what comes back.

The Export button stands under "Showing 1–50 of 102" and used to produce a
sheet of the whole organization — module records the list hides on
purpose, consumed stock in a virtual location. It also left the serial
number out and said nothing about which of its columns the import reads.
"""

import io
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.models.item import Item
from app.services.items.export_service import export_items_to_xlsx


async def _workbook(response) -> dict[str, pd.DataFrame]:
    chunks = [chunk async for chunk in response.body_iterator]
    raw = b''.join(c if isinstance(c, bytes) else c.encode() for c in chunks)
    return pd.read_excel(io.BytesIO(raw), sheet_name=None)


def _ctx(user) -> UserContextDTO:
    return UserContextDTO(id=user.id, organization_id=user.organization_id)


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheExportSaysWhatComesBack:
    async def test_the_serial_number_travels(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ):
        db = real_async_db_session
        db.add(
            Item(
                organization_id=async_test_user.organization_id,
                storage_location_id=async_test_storage_location.id,
                name='Laptop',
                serial_number='SN-0042',
                quantity=Decimal('1'),
            )
        )
        await db.commit()

        sheets = await _workbook(
            await db.run_sync(lambda s: export_items_to_xlsx(s, _ctx(async_test_user)))
        )
        row = sheets['Inventory'].set_index('Name').loc['Laptop']
        assert row['Serial Number'] == 'SN-0042'

    async def test_the_second_sheet_names_the_columns_that_come_back(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_item
    ):
        sheets = await _workbook(
            await real_async_db_session.run_sync(
                lambda s: export_items_to_xlsx(s, _ctx(async_test_user))
            )
        )
        read_me = sheets['Read me'].set_index('Column')
        assert read_me.loc['Name', 'On import'] == 'read'
        assert read_me.loc['Serial Number', 'On import'] == 'read'
        # The one column the wizard reads only when asked: in update mode it
        # says which product the row is about.
        assert read_me.loc['Label Code', 'On import'] == 'read in update mode'
        assert 'in update mode' in read_me.loc['Label Code', 'Note']
        # Every data column is accounted for.
        assert set(sheets['Inventory'].columns) <= set(read_me.index)

    async def test_the_read_me_promises_only_what_the_import_does(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_item
    ):
        # The note used to promise that nothing is refused — measured in the
        # app, a row whose serial number matches is refused (the serial is
        # not a matching key; uniqueness refuses it), and so is a barcode
        # worn by a live record of a different product. A Read me that
        # overclaims is the defect this sheet exists to prevent, in the
        # other direction.
        sheets = await _workbook(
            await real_async_db_session.run_sync(
                lambda s: export_items_to_xlsx(s, _ctx(async_test_user))
            )
        )
        # The note row rides last, under the empty column name the sheet
        # format leaves as NaN once pandas reads it back.
        note = sheets['Read me'].iloc[-1]['Note']
        assert 'nothing is refused' not in note
        assert 'serial number is already on a record' in note
        assert 'worn by a live record of a different product' in note

    async def test_the_search_narrows_the_sheet_like_the_list(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ):
        db = real_async_db_session
        for name in ('Cocoa powder', 'Rice'):
            db.add(
                Item(
                    organization_id=async_test_user.organization_id,
                    storage_location_id=async_test_storage_location.id,
                    name=name,
                    quantity=Decimal('1'),
                )
            )
        await db.commit()

        sheets = await _workbook(
            await db.run_sync(
                lambda s: export_items_to_xlsx(
                    s, _ctx(async_test_user), {'search': 'cocoa'}
                )
            )
        )
        assert sheets['Inventory']['Name'].tolist() == ['Cocoa powder']


@pytest.mark.integration
@pytest.mark.asyncio
class TestAnEmptySchemaHidesNothing:
    """One rule for an empty context_schema: the form reads it as "no
    restriction" and shows every field; the export read it as "no fields" and
    dropped the columns — a home with expiry dates on the list got a sheet
    without them, and re-importing that sheet forgot the dates."""

    async def test_a_home_without_schemas_exports_the_dates_it_shows(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ):
        db = real_async_db_session
        db.add(
            Item(
                organization_id=async_test_user.organization_id,
                storage_location_id=async_test_storage_location.id,
                name='Soup',
                quantity=Decimal('2'),
                expiry_date=date(2026, 10, 10),
                meta_data={'food': {'freeze_date': '2026-09-30'}},
            )
        )
        await db.commit()

        sheets = await _workbook(
            await db.run_sync(lambda s: export_items_to_xlsx(s, _ctx(async_test_user)))
        )
        header = sheets['Inventory'].columns.tolist()
        assert 'Expiry Date' in header
        assert 'Freeze Date' in header
        row = sheets['Inventory'].set_index('Name').loc['Soup']
        assert pd.notna(row['Expiry Date'])
        assert pd.notna(row['Freeze Date'])
        read_me = sheets['Read me'].set_index('Column')
        assert read_me.loc['Freeze Date', 'On import'] == 'read'

    async def test_a_schema_that_restricts_still_hides_what_it_hides(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ):
        """The same rule from the other side: a non-empty schema is a
        restriction, and the export honours it — an empty one is not."""
        db = real_async_db_session
        async_test_storage_location.context_schema = ['weight']
        db.add(
            Item(
                organization_id=async_test_user.organization_id,
                storage_location_id=async_test_storage_location.id,
                name='Dumbbell',
                quantity=Decimal('1'),
                expiry_date=date(2026, 10, 10),
            )
        )
        await db.commit()

        sheets = await _workbook(
            await db.run_sync(lambda s: export_items_to_xlsx(s, _ctx(async_test_user)))
        )
        header = sheets['Inventory'].columns.tolist()
        assert 'Weight' in header
        assert 'Expiry Date' not in header


@pytest.mark.integration
class TestTheExportCoversWhatTheListShows:
    def test_the_sheet_has_as_many_rows_as_the_list_reports(
        self, client, auth_headers, test_items_batch
    ):
        """One filter, two endpoints, one count."""
        params = {'search': 'Product', 'exclude_module_contexts': 'true'}
        listed = client.get('/api/v1/items', headers=auth_headers, params=params)
        assert listed.status_code == status.HTTP_200_OK

        exported = client.get(
            '/api/v1/items/export/xlsx', headers=auth_headers, params=params
        )
        assert exported.status_code == status.HTTP_200_OK
        sheet = pd.read_excel(io.BytesIO(exported.content), sheet_name='Inventory')
        assert len(sheet) == listed.json()['total'] == 5
