"""One code in two rows is one product, not a duplicate.

The importer refused a second row carrying a code the file had already used
("Duplicate barcode"), which no other door does: a code names the product,
and each row is a state of it. The refusal made the app's own export a file
the app could not import back, and refused the typical first spreadsheet —
one product on two shelves — as a mistake.
"""

from datetime import date

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.services.items._import import import_items

CODE = '5905555000043'
MAPPING = {
    'name': 'Name',
    'quantity': 'Quantity',
    'location': 'Storage',
    'barcode': 'Barcode',
}


def _csv(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _ctx(user) -> UserContextDTO:
    return UserContextDTO(
        id=user.id, organization_id=user.organization_id, role='admin'
    )


async def _second_shelf(db: AsyncSession, user) -> StorageLocation:
    shelf = StorageLocation(
        organization_id=user.organization_id,
        created_by=user.id,
        name='Pantry shelf',
    )
    db.add(shelf)
    await db.flush()
    return shelf


async def _items_named(db: AsyncSession, name: str) -> list[Item]:
    rows = await db.execute(
        select(Item).where(Item.name == name).order_by(Item.created_at, Item.id)
    )
    return list(rows.scalars().all())


@pytest.mark.integration
@pytest.mark.asyncio
class TestOneCodeNamesTheProductNotTheRow:
    async def test_two_rows_with_one_code_are_two_states_of_one_product(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        second = await _second_shelf(db, async_test_user)

        result = await import_items(
            db,
            _csv(
                [
                    {
                        'Name': 'Frozen peas',
                        'Quantity': 1,
                        'Storage': 'Kitchen Freezer',
                        'Barcode': CODE,
                    },
                    {
                        'Name': 'Frozen peas',
                        'Quantity': 2,
                        'Storage': 'Pantry shelf',
                        'Barcode': CODE,
                    },
                ]
            ),
            'stock.csv',
            MAPPING,
            _ctx(async_test_user),
            create_missing_locations=False,
            create_missing_categories=False,
        )

        assert result['imported'] == 2, result
        assert result['failed'] == 0, result
        items = await _items_named(db, 'Frozen peas')
        assert len(items) == 2
        assert {item.storage_location_id for item in items} == {
            async_test_storage_location.id,
            second.id,
        }
        assert items[0].template_id == items[1].template_id
        template = await db.get(ProductTemplate, items[0].template_id)
        assert template is not None and template.barcode == CODE
        # The code stays the product's; neither record wears it.
        assert [item.barcode for item in items] == [None, None]

    async def test_the_same_code_in_the_same_shelf_is_two_states_too(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """Two states may share a shelf — two packs are two records.

        The row is not a unique slot for a code; the form accepts the same
        pair of requests, and the import answers exactly what the form does.
        """
        db = real_async_db_session

        result = await import_items(
            db,
            _csv(
                [
                    {
                        'Name': 'Frozen peas',
                        'Quantity': 1,
                        'Storage': 'Kitchen Freezer',
                        'Barcode': CODE,
                    },
                    {
                        'Name': 'Frozen peas',
                        'Quantity': 2,
                        'Storage': 'Kitchen Freezer',
                        'Barcode': CODE,
                    },
                ]
            ),
            'stock.csv',
            MAPPING,
            _ctx(async_test_user),
            create_missing_locations=False,
            create_missing_categories=False,
        )

        assert result['imported'] == 2, result
        items = await _items_named(db, 'Frozen peas')
        assert len(items) == 2
        assert [item.storage_location_id for item in items] == [
            async_test_storage_location.id,
            async_test_storage_location.id,
        ]

    async def test_a_code_worn_by_another_products_record_is_still_refused(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """A legacy record wearing the code keeps it; the collision is named.

        Records made before the code moved to the product keep it on the row,
        which is what most installations look like. A row of *another* product
        may not take that code over — the shared door refuses it by name, the
        same refusal the form gives.
        """
        db = real_async_db_session
        legacy = Item(
            organization_id=async_test_user.organization_id,
            storage_location_id=async_test_storage_location.id,
            name='Legacy product',
            quantity=1,
            barcode=CODE,
            added_date=date.today(),
        )
        db.add(legacy)
        await db.flush()

        result = await import_items(
            db,
            _csv(
                [
                    {
                        'Name': 'Something else',
                        'Quantity': 1,
                        'Storage': 'Kitchen Freezer',
                        'Barcode': CODE,
                    }
                ]
            ),
            'stock.csv',
            MAPPING,
            _ctx(async_test_user),
            create_missing_locations=False,
            create_missing_categories=False,
        )

        assert result['imported'] == 0, result
        assert result['failed'] == 1, result
        assert result['errors'][0]['error'] == f'Barcode already in use: {CODE}'
