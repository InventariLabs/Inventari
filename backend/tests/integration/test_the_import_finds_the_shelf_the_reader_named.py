"""The import finds the shelf the reader named.

The app shows every location as a path ("Pantry → Dry Goods → Shelf A"), so
that is what a reader types into the sheet. The importer used to match the
bare leaf name only, and founded a root location named after the whole path
when it missed; an empty cell founded one named "nan".
"""

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.models.category import Category
from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.services.items._import import import_items


def _csv(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _ctx(user) -> UserContextDTO:
    return UserContextDTO(
        id=user.id, organization_id=user.organization_id, role='admin'
    )


MAPPING = {'name': 'Name', 'location': 'Storage', 'category': 'Category'}


async def _location_count(db: AsyncSession, org_id) -> int:
    return (
        await db.scalar(
            select(func.count(StorageLocation.id)).where(
                StorageLocation.organization_id == org_id
            )
        )
    ) or 0


async def _location_names(db: AsyncSession, org_id) -> set[str]:
    rows = await db.execute(
        select(StorageLocation.name).where(StorageLocation.organization_id == org_id)
    )
    return set(rows.scalars().all())


async def _item_named(db: AsyncSession, name: str) -> Item:
    return (await db.execute(select(Item).where(Item.name == name))).scalar_one()


async def _grow_a_tree(
    db: AsyncSession, user, storage_type
) -> tuple[StorageLocation, StorageLocation, StorageLocation]:
    """Pantry → Dry Goods → Shelf A, each under the one before."""
    pantry = StorageLocation(
        organization_id=user.organization_id,
        created_by=user.id,
        storage_type_id=storage_type.id,
        name='Pantry',
    )
    db.add(pantry)
    await db.flush()
    dry_goods = StorageLocation(
        organization_id=user.organization_id,
        created_by=user.id,
        storage_type_id=storage_type.id,
        name='Dry Goods',
        parent_id=pantry.id,
    )
    db.add(dry_goods)
    await db.flush()
    shelf = StorageLocation(
        organization_id=user.organization_id,
        created_by=user.id,
        storage_type_id=storage_type.id,
        name='Shelf A',
        parent_id=dry_goods.id,
    )
    db.add(shelf)
    await db.flush()
    return pantry, dry_goods, shelf


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheImportFindsTheShelfTheReaderNamed:
    async def test_an_empty_cell_founds_no_location(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        org_id = async_test_user.organization_id
        before = await _location_count(db, org_id)

        # One sheet where the column is wholly empty (pandas reads it as
        # float NaN) and one where it is empty on a single row (None).
        for rows in (
            [{'Name': 'Salt', 'Storage': None}],
            [
                {'Name': 'Pepper', 'Storage': None},
                {'Name': 'Cumin', 'Storage': 'Kitchen Freezer'},
            ],
        ):
            result = await import_items(
                db, _csv(rows), 'stock.csv', MAPPING, _ctx(async_test_user)
            )
            assert result['failed'] == 0, result

        assert await _location_count(db, org_id) == before
        assert 'nan' not in {n.lower() for n in await _location_names(db, org_id)}
        assert result['created_locations'] == []

    async def test_a_path_lands_on_the_shelf_it_names(
        self,
        real_async_db_session,
        async_test_user,
        async_test_storage_location,
        async_test_storage_type,
    ):
        db = real_async_db_session
        org_id = async_test_user.organization_id
        _, _, shelf = await _grow_a_tree(db, async_test_user, async_test_storage_type)
        before = await _location_count(db, org_id)

        result = await import_items(
            db,
            _csv(
                [
                    {'Name': 'Cocoa', 'Storage': 'Pantry → Dry Goods → Shelf A'},
                    {'Name': 'Rice', 'Storage': 'Pantry -> Dry Goods -> Shelf A'},
                    {'Name': 'Oats', 'Storage': 'shelf a'},
                ]
            ),
            'stock.csv',
            MAPPING,
            _ctx(async_test_user),
        )

        assert result['failed'] == 0, result
        for name in ('Cocoa', 'Rice', 'Oats'):
            assert (await _item_named(db, name)).storage_location_id == shelf.id
        assert await _location_count(db, org_id) == before
        assert result['created_locations'] == []

    async def test_a_missing_leaf_grows_under_the_parent_the_path_names(
        self,
        real_async_db_session,
        async_test_user,
        async_test_storage_location,
        async_test_storage_type,
    ):
        db = real_async_db_session
        _, dry_goods, _ = await _grow_a_tree(
            db, async_test_user, async_test_storage_type
        )

        result = await import_items(
            db,
            _csv(
                [
                    {'Name': 'Cocoa', 'Storage': 'Pantry → Dry Goods → Shelf B'},
                    {'Name': 'Rice', 'Storage': 'Pantry → Dry Goods → Shelf B'},
                    {'Name': 'Salt', 'Storage': 'Cellar', 'Category': 'Spices'},
                ]
            ),
            'stock.csv',
            MAPPING,
            _ctx(async_test_user),
        )

        assert result['failed'] == 0, result
        shelf_b = (
            await db.execute(
                select(StorageLocation).where(StorageLocation.name == 'Shelf B')
            )
        ).scalar_one()
        assert shelf_b.parent_id == dry_goods.id
        cellar = (
            await db.execute(
                select(StorageLocation).where(StorageLocation.name == 'Cellar')
            )
        ).scalar_one()
        assert cellar.parent_id is None
        assert result['created_locations'] == [
            'Pantry → Dry Goods → Shelf B',
            'Cellar',
        ]
        assert result['created_categories'] == ['Spices']
        assert (
            await db.scalar(
                select(func.count(Category.id)).where(Category.name == 'Spices')
            )
            == 1
        )

    async def test_an_unknown_location_refuses_the_row_when_it_may_not_be_founded(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        org_id = async_test_user.organization_id
        before = await _location_count(db, org_id)

        result = await import_items(
            db,
            _csv([{'Name': 'Cocoa', 'Storage': 'Attic → Box 3'}]),
            'stock.csv',
            MAPPING,
            _ctx(async_test_user),
            create_missing_locations=False,
        )

        assert result['imported'] == 0
        assert result['errors'] == [
            {'row': 2, 'error': 'Column "Storage": location "Attic → Box 3" not found'}
        ]
        assert await _location_count(db, org_id) == before
