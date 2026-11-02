"""A value the import could not save is a refused row, not a quiet loss.

The importer asked the same question in three places — the sheet names
something the organization does not have — and used to answer it three
ways. An unknown location refused the row; an unknown category was
dropped and the row still counted as a success; a date nobody could read
went to the server log and the row kept its success too. The report then
said "failed 0" while the sheet's own data was gone: the category the
reader typed never existed, and the term they wrote for a product never
reached "expiring soon".

One answer for all three: a cell the importer cannot honour refuses the
row, naming the column and the cell — the way quantity and location
already did.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.models.category import Category
from app.models.item import Item
from app.services.items._import import import_items

pytestmark = pytest.mark.integration

MAPPING = {
    'name': 'Name',
    'category': 'Category',
    'expiry_date': 'Expiry',
    'freeze_date': 'Freeze',
}


def _csv(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _ctx(user) -> UserContextDTO:
    return UserContextDTO(
        id=user.id, organization_id=user.organization_id, role='admin'
    )


async def _import(db: AsyncSession, user, rows: list[dict], **kwargs) -> dict:
    return await import_items(
        db, _csv(rows), 'stock.csv', MAPPING, _ctx(user), **kwargs
    )


async def _item_named(db: AsyncSession, name: str) -> Item:
    return (await db.execute(select(Item).where(Item.name == name))).scalar_one()


async def _assert_not_saved(db: AsyncSession, name: str) -> None:
    found = (
        await db.execute(select(Item).where(Item.name == name))
    ).scalar_one_or_none()
    assert found is None, f'{name} was written despite the refusal'


class TestAnUnknownCategoryRefusesTheRow:
    async def test_the_row_is_refused_and_the_value_named(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """The same answer the unknown location already gave."""
        result = await _import(
            real_async_db_session,
            async_test_user,
            [{'Name': 'Cocoa', 'Category': 'Spices'}],
            create_missing_categories=False,
        )

        assert result['imported'] == 0
        assert result['failed'] == 1
        assert result['errors'] == [
            {'row': 2, 'error': 'Column "Category": category "Spices" not found'}
        ]
        # Nothing was written: the refusal must not leave behind the product
        # it was refusing to give a category.
        await _assert_not_saved(real_async_db_session, 'Cocoa')

    async def test_a_category_the_organization_has_still_imports(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """Refusing what is missing must not refuse what is there."""
        db, user = real_async_db_session, async_test_user
        existing = Category(name='Spices', organization_id=user.organization_id)
        db.add(existing)
        await db.flush()

        result = await _import(
            db,
            user,
            [{'Name': 'Pepper', 'Category': 'spices'}],
            create_missing_categories=False,
        )

        assert result['failed'] == 0, result
        assert (await _item_named(db, 'Pepper')).category_id == existing.id

    async def test_the_category_and_the_location_answer_alike(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """Two doors, one sentence: column, value, "not found"."""
        mapping = {
            'name': 'Name',
            'category': 'Category',
            'location': 'Storage',
        }
        result = await import_items(
            real_async_db_session,
            _csv(
                [
                    {'Name': 'Cocoa', 'Category': 'Spices'},
                    {'Name': 'Rice', 'Storage': 'Attic'},
                ]
            ),
            'stock.csv',
            mapping,
            _ctx(async_test_user),
            create_missing_categories=False,
            create_missing_locations=False,
        )

        assert result['imported'] == 0
        assert result['failed'] == 2
        category_error = result['errors'][0]['error']
        location_error = result['errors'][1]['error']
        assert category_error == 'Column "Category": category "Spices" not found'
        assert location_error == 'Column "Storage": location "Attic" not found'


class TestAnUnreadableDateRefusesTheRow:
    async def test_the_row_is_refused_with_the_column_and_the_cell(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """31.02.2027 has no day; the row that carried it is not a success.

        The date was the one cell the importer let go without a word —
        quantity, unit and location all refuse theirs — so a term the
        reader had typed vanished under a report of zero failures and the
        product stayed off every expiring-soon screen.
        """
        result = await _import(
            real_async_db_session,
            async_test_user,
            [{'Name': 'Oliwa', 'Expiry': '31.02.2027'}],
        )

        assert result['imported'] == 0
        assert result['failed'] == 1
        assert result['errors'] == [
            {'row': 2, 'error': 'Column "Expiry": "31.02.2027" is not a date'}
        ]
        await _assert_not_saved(real_async_db_session, 'Oliwa')

    async def test_a_date_that_reads_still_imports(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """The refusal is for the unreadable cell, not for the column."""
        db = real_async_db_session

        result = await _import(
            db,
            async_test_user,
            [
                {'Name': 'Oliwa', 'Expiry': '2027-12-31'},
                {'Name': 'Ryz', 'Expiry': None},
            ],
        )

        assert result['failed'] == 0, result
        assert result['imported'] == 2
        assert (await _item_named(db, 'Oliwa')).expiry_date == date(2027, 12, 31)
        assert (await _item_named(db, 'Ryz')).expiry_date is None


class TestTheFreezeDateTravelsWithTheSheet:
    async def test_a_freeze_date_column_lands_on_the_new_product(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """The export writes a Freeze Date column; importing it back keeps it."""
        db = real_async_db_session

        result = await _import(
            db,
            async_test_user,
            [{'Name': 'Soup', 'Expiry': '2027-12-31', 'Freeze': '2026-10-01'}],
        )

        assert result['failed'] == 0, result
        soup = await _item_named(db, 'Soup')
        assert soup.expiry_date == date(2027, 12, 31)
        assert soup.meta_data['food']['freeze_date'] == '2026-10-01'

    async def test_an_unreadable_freeze_date_refuses_the_row(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        result = await _import(
            real_async_db_session,
            async_test_user,
            [{'Name': 'Soup', 'Freeze': '31.02.2026'}],
        )

        assert result['errors'] == [
            {'row': 2, 'error': 'Column "Freeze": "31.02.2026" is not a date'}
        ]
        await _assert_not_saved(real_async_db_session, 'Soup')
