"""The export carries what the list and the product page show.

A sheet exported to hand the catalogue to an accountant, or to keep a copy,
lost the SKU every row shows, the description, the values of the category's
custom fields and the stock alert — and named a location by its last segment,
so two shelves called "Server Room" were one in the file.
"""

import io
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.models.category import Category
from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.schemas.item import ItemCreate
from app.services.items._create import create_item_async
from app.services.items.export_service import export_items_to_xlsx


async def _workbook(response) -> dict[str, pd.DataFrame]:
    chunks = [chunk async for chunk in response.body_iterator]
    raw = b''.join(c if isinstance(c, bytes) else c.encode() for c in chunks)
    return pd.read_excel(io.BytesIO(raw), sheet_name=None)


def _ctx(user) -> UserContextDTO:
    return UserContextDTO(id=user.id, organization_id=user.organization_id)


async def _export(db: AsyncSession, user) -> dict[str, pd.DataFrame]:
    return await _workbook(
        await db.run_sync(lambda s: export_items_to_xlsx(s, _ctx(user)))
    )


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheExportKeepsWhatTheScreenShows:
    async def test_sku_description_alert_and_custom_fields_travel(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ):
        db = real_async_db_session
        org_id = async_test_user.organization_id
        category = Category(
            name='Fasteners',
            organization_id=org_id,
            field_definitions=[
                {'key': 'thread_size', 'label': 'Thread size', 'type': 'text'}
            ],
        )
        db.add(category)
        await db.flush()
        await create_item_async(
            db,
            ItemCreate(
                name='Hex bolt',
                description='Zinc plated',
                quantity=Decimal('5'),
                location_id=async_test_storage_location.id,
                category_id=category.id,
                metadata={'thread_size': 'M8'},
                sku='BOLT-M8',
                min_quantity=20,
            ),
            _ctx(async_test_user),
        )
        await db.commit()

        sheets = await _export(db, async_test_user)

        row = sheets['Inventory'].set_index('Name').loc['Hex bolt']
        assert row['SKU'] == 'BOLT-M8'
        assert row['Description'] == 'Zinc plated'
        assert row['Stock alert'] == 20
        assert row['Custom: Thread size'] == 'M8'
        read_me = sheets['Read me'].set_index('Column')
        for column in ('SKU', 'Description', 'Stock alert', 'Custom: Thread size'):
            assert read_me.loc[column, 'On import'] == 'not read'

    async def test_the_location_column_names_one_place(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        db = real_async_db_session
        org_id = async_test_user.organization_id
        first_building = StorageLocation(
            organization_id=org_id, created_by=async_test_user.id, name='Building A'
        )
        second_building = StorageLocation(
            organization_id=org_id, created_by=async_test_user.id, name='Building B'
        )
        db.add_all([first_building, second_building])
        await db.flush()
        rooms = [
            StorageLocation(
                organization_id=org_id,
                created_by=async_test_user.id,
                name='Server Room',
                parent_id=building.id,
            )
            for building in (first_building, second_building)
        ]
        db.add_all(rooms)
        await db.flush()
        for index, room in enumerate(rooms):
            db.add(
                Item(
                    organization_id=org_id,
                    storage_location_id=room.id,
                    name=f'Switch {index}',
                    quantity=Decimal('1'),
                )
            )
        await db.commit()

        sheets = await _export(db, async_test_user)

        locations = sheets['Inventory'].set_index('Name')['Location']
        assert locations['Switch 0'] == 'Building A › Server Room'
        assert locations['Switch 1'] == 'Building B › Server Room'

    async def test_the_barcode_column_carries_the_code_on_the_product_card(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ):
        """A product's code lives on its card; the record's own column is empty."""
        db = real_async_db_session
        await create_item_async(
            db,
            ItemCreate(
                name='Plum butter',
                quantity=Decimal('3'),
                location_id=async_test_storage_location.id,
                barcode='2000000009018',
            ),
            _ctx(async_test_user),
        )
        await db.commit()
        record = (
            await db.execute(select(Item).where(Item.name == 'Plum butter'))
        ).scalar_one()
        assert record.barcode is None
        assert record.template is not None
        assert record.template.barcode == '2000000009018'

        sheets = await _export(db, async_test_user)

        row = sheets['Inventory'].set_index('Name').loc['Plum butter']
        assert str(row['Barcode']) == '2000000009018'
