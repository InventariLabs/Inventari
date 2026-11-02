"""A row filed under an existing product by its code may not change its unit.

A sheet row whose barcode named a product kept in kilograms, with 'pcs' in
its unit column, was filed under that product and came out as kilograms
with the number unchanged — three pieces of something booked as three
kilograms of the other product, under the name the row happened to carry.
"""

from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.models.item import Item
from app.models.product_template import ProductTemplate
from app.services.items._import import import_items
from app.services.uom_service import get_uom_by_symbol_async

CODE = '2000000009018'
MAPPING = {
    'name': 'Name',
    'quantity': 'Quantity',
    'unit': 'Unit',
    'barcode': 'Barcode',
}


def _csv(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows, dtype=str).to_csv(index=False).encode()


def _ctx(user) -> UserContextDTO:
    return UserContextDTO(
        id=user.id, organization_id=user.organization_id, role='admin'
    )


async def _plum_butter_in_kg(
    db: AsyncSession, user, jar_kg: Decimal | None = None
) -> ProductTemplate:
    kg = await get_uom_by_symbol_async(db, 'kg', user.organization_id)
    card = ProductTemplate(
        organization_id=user.organization_id,
        name='Plum Butter',
        barcode=CODE,
        uom_id=kg.id,
        weight_value=jar_kg,
        weight_uom_id=kg.id if jar_kg else None,
    )
    db.add(card)
    await db.flush()
    return card


async def _import(db, user, rows):
    return await import_items(
        db,
        _csv(rows),
        'stock.csv',
        MAPPING,
        _ctx(user),
        create_missing_locations=False,
        create_missing_categories=False,
    )


@pytest.mark.integration
@pytest.mark.asyncio
class TestARowUnderAProductsCodeKeepsThatProductsUnit:
    async def test_pieces_against_a_kilogram_product_are_refused_naming_both_units(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        await _plum_butter_in_kg(db, async_test_user)

        result = await _import(
            db,
            async_test_user,
            [
                {
                    'Name': 'Imported Tuna dup barcode',
                    'Quantity': '3',
                    'Unit': 'pcs',
                    'Barcode': CODE,
                }
            ],
        )

        assert result['imported'] == 0, result
        assert result['failed'] == 1, result
        message = result['errors'][0]['error']
        assert 'pcs' in message and 'kg' in message, message
        assert 'Plum Butter' in message, message
        rows = await db.scalars(
            select(Item).where(Item.name == 'Imported Tuna dup barcode')
        )
        assert rows.all() == []

    async def test_a_convertible_unit_is_converted_not_relabelled(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        await _plum_butter_in_kg(db, async_test_user)

        result = await _import(
            db,
            async_test_user,
            [
                {
                    'Name': 'Plum Butter',
                    'Quantity': '500',
                    'Unit': 'g',
                    'Barcode': CODE,
                }
            ],
        )

        assert result['imported'] == 1, result
        item = (await db.scalars(select(Item).where(Item.name == 'Plum Butter'))).one()
        await db.refresh(item, ['uom'])
        assert item.uom.symbol == 'kg'
        assert item.quantity == Decimal('0.500')

    async def test_a_row_filed_under_an_existing_product_carries_its_name(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session
        card = await _plum_butter_in_kg(db, async_test_user)

        result = await _import(
            db,
            async_test_user,
            [
                {
                    'Name': 'Plum butter jar',
                    'Quantity': '2',
                    'Unit': 'kg',
                    'Barcode': CODE,
                }
            ],
        )

        assert result['imported'] == 1, result
        # The result says the row added stock to a product, not that it made one.
        assert result['joined_existing'] == 1, result
        item = (await db.scalars(select(Item).where(Item.template_id == card.id))).one()
        assert item.name == 'Plum Butter'

    async def test_pieces_are_weighed_by_the_products_piece_weight_and_named_after_it(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """The row's three pieces become the jar weight times three, as plum butter.

        The unit is converted by what the product says one piece weighs, never
        relabelled, and the record carries the product's name rather than the
        one the row happened to bring.
        """
        db = real_async_db_session
        card = await _plum_butter_in_kg(db, async_test_user, Decimal('0.5'))

        result = await _import(
            db,
            async_test_user,
            [
                {
                    'Name': 'Imported Tuna dup barcode',
                    'Quantity': '3',
                    'Unit': 'pcs',
                    'Barcode': CODE,
                }
            ],
        )

        assert result['imported'] == 1, result
        item = (await db.scalars(select(Item).where(Item.template_id == card.id))).one()
        await db.refresh(item, ['uom'])
        assert item.name == 'Plum Butter'
        assert item.uom.symbol == 'kg'
        assert item.quantity == Decimal('1.500')

    async def test_two_rows_of_one_new_product_make_one_product_and_one_join(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        db = real_async_db_session

        result = await _import(
            db,
            async_test_user,
            [
                {
                    'Name': 'Frozen peas',
                    'Quantity': '1',
                    'Unit': 'pcs',
                    'Barcode': '5905555000043',
                },
                {
                    'Name': 'Frozen peas',
                    'Quantity': '2',
                    'Unit': 'pcs',
                    'Barcode': '5905555000043',
                },
            ],
        )

        assert result['imported'] == 2, result
        assert result['joined_existing'] == 1, result
