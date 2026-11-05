"""An imported row is a product like any other.

The importer used to build ``Item(**data)`` by hand and skip
``create_item_async``, so an imported product had no template, no unit and
no stock entry: the products list counted it and the stock screen did not
know it. It also handed the reader the repr of whatever exception a bad cell
raised.
"""

from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.stock_valuation_layer import StockValuationLayer
from app.services.items._import import import_items


def _csv(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _ctx(user) -> UserContextDTO:
    return UserContextDTO(
        id=user.id, organization_id=user.organization_id, role='admin'
    )


async def _item_named(db: AsyncSession, name: str) -> Item:
    return (await db.execute(select(Item).where(Item.name == name))).scalar_one()


async def _templateless_count(db: AsyncSession, org_id) -> int:
    return (
        await db.scalar(
            select(func.count(Item.id)).where(
                Item.organization_id == org_id, Item.template_id.is_(None)
            )
        )
    ) or 0


@pytest.mark.integration
@pytest.mark.asyncio
class TestAnImportedRowIsAProductLikeAnyOther:
    async def test_an_imported_row_gets_a_template_a_unit_and_a_stock_entry(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        before = await _templateless_count(db, async_test_user.organization_id)

        result = await import_items(
            db,
            _csv([{'Name': 'Imported cocoa', 'Quantity': 5}]),
            'stock.csv',
            {'name': 'Name', 'quantity': 'Quantity'},
            _ctx(async_test_user),
            create_missing_locations=False,
            create_missing_categories=False,
        )

        assert result['imported'] == 1, result
        item = await _item_named(db, 'Imported cocoa')
        assert item.template_id is not None
        await db.refresh(item, ['uom'])
        assert item.uom is not None and item.uom.symbol == 'pcs'
        on_hand = await db.scalar(
            select(func.sum(ShelfRow.quantity)).where(
                ShelfRow.product_template_id == item.template_id
            )
        )
        assert on_hand == Decimal('5')
        assert await _templateless_count(db, async_test_user.organization_id) == before

    async def test_the_unit_column_names_the_unit(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        result = await import_items(
            db,
            _csv([{'Name': 'Imported flour', 'Quantity': 2, 'Unit': 'kg'}]),
            'stock.csv',
            {'name': 'Name', 'quantity': 'Quantity', 'unit': 'Unit'},
            _ctx(async_test_user),
            create_missing_locations=False,
            create_missing_categories=False,
        )

        assert result['imported'] == 1, result
        item = await _item_named(db, 'Imported flour')
        await db.refresh(item, ['uom'])
        assert item.uom.symbol == 'kg'

    async def test_an_unknown_unit_refuses_the_row_by_name(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        result = await import_items(
            real_async_db_session,
            _csv([{'Name': 'Imported flour', 'Quantity': 2, 'Unit': 'bushel'}]),
            'stock.csv',
            {'name': 'Name', 'quantity': 'Quantity', 'unit': 'Unit'},
            _ctx(async_test_user),
            create_missing_locations=False,
            create_missing_categories=False,
        )

        assert result['imported'] == 0
        assert result['errors'][0]['row'] == 1
        assert result['errors'][0]['error'].startswith(
            'Column "Unit": unknown unit "bushel". Known units: '
        )

    async def test_a_priced_row_can_be_valued(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        result = await import_items(
            db,
            _csv([{'Name': 'Imported rice', 'Quantity': 3, 'Price': '2.50'}]),
            'stock.csv',
            {'name': 'Name', 'quantity': 'Quantity', 'purchase_price': 'Price'},
            _ctx(async_test_user),
            create_missing_locations=False,
            create_missing_categories=False,
        )

        assert result['imported'] == 1, result
        item = await _item_named(db, 'Imported rice')
        layer = (
            await db.execute(
                select(StockValuationLayer).where(
                    StockValuationLayer.product_template_id == item.template_id
                )
            )
        ).scalar_one()
        assert layer.unit_cost == Decimal('2.50')
        assert layer.quantity == Decimal('3')

    async def test_a_number_that_is_not_one_is_named_with_its_column(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        result = await import_items(
            real_async_db_session,
            _csv(
                [
                    {'Name': 'Imported salt', 'Quantity': 'plenty'},
                    {'Name': 'Imported sugar', 'Quantity': 1},
                ]
            ),
            'stock.csv',
            {'name': 'Name', 'quantity': 'Quantity'},
            _ctx(async_test_user),
            create_missing_locations=False,
            create_missing_categories=False,
        )

        assert result['imported'] == 1
        assert result['errors'] == [
            {'row': 1, 'error': 'Column "Quantity": "plenty" is not a number'}
        ]

    async def test_a_refused_row_is_numbered_as_the_preview_numbers_it(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """The preview counts data rows from 1, the header not counted. The
        second row of the sheet is "2" there, so the result must not call it
        "3" (the spreadsheet row, which nothing on the screen explains)."""
        result = await import_items(
            real_async_db_session,
            _csv(
                [
                    {'Name': 'Imported salt', 'Quantity': 1},
                    {'Name': 'Imported sugar', 'Quantity': 'abc'},
                ]
            ),
            'stock.csv',
            {'name': 'Name', 'quantity': 'Quantity'},
            _ctx(async_test_user),
            create_missing_locations=False,
            create_missing_categories=False,
        )

        assert [e['row'] for e in result['errors']] == [2]

    async def test_an_unexpected_failure_stays_out_of_the_reply(
        self,
        real_async_db_session,
        async_test_user,
        async_test_storage_location,
        monkeypatch,
    ):
        async def explode(*_args, **_kwargs):
            raise RuntimeError('secret internals')

        monkeypatch.setattr('app.services.items._import.create_item_async', explode)

        result = await import_items(
            real_async_db_session,
            _csv([{'Name': 'Imported pepper', 'Quantity': 1}]),
            'stock.csv',
            {'name': 'Name', 'quantity': 'Quantity'},
            _ctx(async_test_user),
            create_missing_locations=False,
            create_missing_categories=False,
        )

        assert result['failed'] == 1
        assert 'secret internals' not in result['errors'][0]['error']
        assert result['errors'][0]['error'] == 'The row could not be imported'
