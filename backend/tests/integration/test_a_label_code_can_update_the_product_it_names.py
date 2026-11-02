"""A second import of the same sheet updates instead of duplicating.

The export carries a Label Code for every product; until now the import
ignored it, so a corrected sheet re-imported the whole file as new products.
The update mode reads that column: a row whose code names a product the
organization already has is skipped or overwritten, as the reader chose. A
row without a code, or with an unknown one, still becomes a new product.
"""

from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.testing import ShelfRow
from app.models.item import Item
from app.services.items._import import import_items


def _csv(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _ctx(user) -> UserContextDTO:
    return UserContextDTO(
        id=user.id, organization_id=user.organization_id, role='admin'
    )


_MAPPING = {
    'name': 'Name',
    'quantity': 'Quantity',
    'brand': 'Brand',
    'label_code': 'Label Code',
}


async def _seeded(db: AsyncSession, user, storage) -> Item:
    """One product carrying a label code, imported the ordinary way."""
    await import_items(
        db,
        _csv([{'Name': 'Cocoa', 'Quantity': 4, 'Brand': 'Old brand'}]),
        'stock.csv',
        {'name': 'Name', 'quantity': 'Quantity', 'brand': 'Brand'},
        _ctx(user),
        create_missing_locations=False,
        create_missing_categories=False,
    )
    item = (await db.execute(select(Item).where(Item.name == 'Cocoa'))).scalar_one()
    item.label_code = 'INV-0007'
    await db.commit()
    return item


async def _product_count(db: AsyncSession, org_id) -> int:
    return (
        await db.scalar(
            select(func.count(Item.id)).where(
                Item.organization_id == org_id, Item.is_deleted.is_(False)
            )
        )
    ) or 0


@pytest.mark.integration
@pytest.mark.asyncio
class TestALabelCodeCanUpdateTheProductItNames:
    async def test_overwrite_writes_the_row_onto_the_product_it_names(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        item = await _seeded(db, async_test_user, async_test_storage_location)
        before = await _product_count(db, async_test_user.organization_id)

        result = await import_items(
            db,
            _csv(
                [
                    {
                        'Name': 'Cocoa powder',
                        'Quantity': 99,
                        'Brand': 'New brand',
                        'Label Code': 'INV-0007',
                    }
                ]
            ),
            'stock.csv',
            _MAPPING,
            _ctx(async_test_user),
            create_missing_locations=False,
            create_missing_categories=False,
            on_label_match='overwrite',
        )

        assert result['updated'] == 1, result
        assert result['imported'] == 0
        assert await _product_count(db, async_test_user.organization_id) == before
        await db.refresh(item)
        assert item.name == 'Cocoa powder'
        assert item.brand == 'New brand'

    async def test_overwrite_leaves_the_stock_to_the_ledger(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        item = await _seeded(db, async_test_user, async_test_storage_location)

        await import_items(
            db,
            _csv([{'Name': 'Cocoa', 'Quantity': 99, 'Label Code': 'INV-0007'}]),
            'stock.csv',
            _MAPPING,
            _ctx(async_test_user),
            create_missing_locations=False,
            create_missing_categories=False,
            on_label_match='overwrite',
        )

        await db.refresh(item)
        assert item.quantity == Decimal('4')
        on_hand = await db.scalar(
            select(func.sum(ShelfRow.quantity)).where(
                ShelfRow.product_template_id == item.template_id
            )
        )
        assert on_hand == Decimal('4')

    async def test_skip_leaves_the_matched_product_alone(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        item = await _seeded(db, async_test_user, async_test_storage_location)
        before = await _product_count(db, async_test_user.organization_id)

        result = await import_items(
            db,
            _csv(
                [
                    {
                        'Name': 'Cocoa powder',
                        'Quantity': 99,
                        'Brand': 'New brand',
                        'Label Code': 'INV-0007',
                    }
                ]
            ),
            'stock.csv',
            _MAPPING,
            _ctx(async_test_user),
            create_missing_locations=False,
            create_missing_categories=False,
            on_label_match='skip',
        )

        assert result['skipped'] == 1, result
        assert result['imported'] == 0
        assert await _product_count(db, async_test_user.organization_id) == before
        await db.refresh(item)
        assert item.name == 'Cocoa'
        assert item.brand == 'Old brand'

    async def test_an_unknown_code_still_becomes_a_new_product(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        await _seeded(db, async_test_user, async_test_storage_location)

        result = await import_items(
            db,
            _csv(
                [
                    {'Name': 'Vanilla', 'Quantity': 1, 'Label Code': 'LBL-9999'},
                    {'Name': 'Cinnamon', 'Quantity': 1, 'Label Code': ''},
                ]
            ),
            'stock.csv',
            _MAPPING,
            _ctx(async_test_user),
            create_missing_locations=False,
            create_missing_categories=False,
            on_label_match='overwrite',
        )

        assert result['imported'] == 2, result
        assert result['updated'] == 0

    async def test_the_default_mode_still_only_adds(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        item = await _seeded(db, async_test_user, async_test_storage_location)

        result = await import_items(
            db,
            _csv([{'Name': 'Cocoa', 'Quantity': 1, 'Label Code': 'INV-0007'}]),
            'stock.csv',
            _MAPPING,
            _ctx(async_test_user),
            create_missing_locations=False,
            create_missing_categories=False,
        )

        assert result['imported'] == 1, result
        assert result['updated'] == 0 and result['skipped'] == 0
        await db.refresh(item)
        assert item.name == 'Cocoa'
