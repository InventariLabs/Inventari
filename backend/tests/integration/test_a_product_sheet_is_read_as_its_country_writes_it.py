"""A product sheet from a European Excel imports with the numbers and dates it holds.

The product import read every cell with ``Decimal(text)`` and
``pd.to_datetime(text)``: "12,5" and "1 289,00 zł" were refused, and
"05.11.2026" was stored as 11 May with the row counted as imported — the
wrong products showed as expiring. The sheet's own country decides how its
numbers and dates are read.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.i18n.service import set_current_lang
from app.models.item import Item
from app.services.items._import import import_items

pytestmark = pytest.mark.integration

MAPPING = {
    'name': 'Produkt',
    'quantity': 'Ilość',
    'purchase_price': 'Cena',
    'expiry_date': 'Ważne do',
    'unit': 'Jm',
}


@pytest.fixture(autouse=True)
def _reader_language():
    yield
    set_current_lang('en')


async def _import(db: AsyncSession, user, sheet: str, language: str = 'pl') -> dict:
    set_current_lang(language)
    return await import_items(
        db,
        sheet.encode('cp1250'),
        'arkusz.csv',
        MAPPING,
        UserContextDTO(id=user.id, organization_id=user.organization_id, role='admin'),
        create_missing_locations=False,
        create_missing_categories=False,
    )


async def _item(db: AsyncSession, name: str) -> Item:
    return (await db.execute(select(Item).where(Item.name == name))).scalar_one()


class TestAProductSheetIsReadAsItsCountryWritesIt:
    async def test_the_numbers_and_dates_are_what_the_sheet_wrote(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        result = await _import(
            real_async_db_session,
            async_test_user,
            'Produkt;Ilość;Cena;Ważne do;Jm\n'
            'Mleko;12,5;1 289,00 zł;05.11.2026;kg\n'
            'Ser;1 200;$4.50;03/12/2025;kg\n'
            'Masło;3;€ 7,49;28.02.2025;kg\n',
        )

        assert (result['imported'], result['failed']) == (3, 0), result['errors']
        milk = await _item(real_async_db_session, 'Mleko')
        assert (milk.quantity, milk.purchase_price) == (
            Decimal('12.5'),
            Decimal('1289.00'),
        )
        assert milk.expiry_date == date(2026, 11, 5)
        cheese = await _item(real_async_db_session, 'Ser')
        assert (cheese.quantity, cheese.purchase_price) == (
            Decimal('1200'),
            Decimal('4.50'),
        )
        assert cheese.expiry_date == date(2025, 12, 3)
        assert (await _item(real_async_db_session, 'Masło')).expiry_date == date(
            2025, 2, 28
        )

    async def test_a_dot_before_three_digits_is_thousands_in_a_german_sheet(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        result = await _import(
            real_async_db_session,
            async_test_user,
            'Produkt;Ilość;Cena;Ważne do;Jm\n'
            'Schraube A;1.250;1.289,00 €;05.11.2026;kg\n'
            'Schraube B;1.234;4,50 €;28.02.2027;kg\n'
            'Schraube C;12.345;R$ 4,50;12.01.2027;kg\n',
            'de',
        )

        assert (result['imported'], result['failed']) == (3, 0), result['errors']
        for name, quantity in (
            ('Schraube A', '1250'),
            ('Schraube B', '1234'),
            ('Schraube C', '12345'),
        ):
            item = await _item(real_async_db_session, name)
            assert item.quantity == Decimal(quantity), name

    async def test_a_decimal_comma_in_the_column_makes_a_lone_comma_decimal_in_english(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """A Polish sheet imported from an English screen: "1,250" is 1.25 kg."""
        result = await _import(
            real_async_db_session,
            async_test_user,
            'Produkt;Ilość;Cena;Ważne do;Jm\n'
            'Sruby;12,5;7,49 zł;05.11.2026;kg\n'
            'Nakretki;1,250;1 289,00 zł;03.12.2026;kg\n'
            'Podkladki;2;4,50 zł;28.02.2027;kg\n',
            'en',
        )

        assert (result['imported'], result['failed']) == (3, 0), result['errors']
        for name, quantity in (
            ('Sruby', '12.5'),
            ('Nakretki', '1.25'),
            ('Podkladki', '2'),
        ):
            item = await _item(real_async_db_session, name)
            assert item.quantity == Decimal(quantity), name

    async def test_an_all_ambiguous_column_follows_the_importers_language(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        sheet = 'Produkt;Ilość;Cena;Ważne do;Jm\nKefir;1;1;05.11.2026;kg\n'

        await _import(real_async_db_session, async_test_user, sheet, 'pl')
        assert (await _item(real_async_db_session, 'Kefir')).expiry_date == date(
            2026, 11, 5
        )

    async def test_an_all_ambiguous_column_is_month_first_for_us_english(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        sheet = 'Produkt;Ilość;Cena;Ważne do;Jm\nJogurt;1;1;05.11.2026;kg\n'

        await _import(real_async_db_session, async_test_user, sheet, 'en')
        assert (await _item(real_async_db_session, 'Jogurt')).expiry_date == date(
            2026, 5, 11
        )

    async def test_a_cell_that_is_not_a_number_or_a_date_is_refused_with_the_cell(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        result = await _import(
            real_async_db_session,
            async_test_user,
            'Produkt;Ilość;Cena;Ważne do;Jm\n'
            'Mleko;1;tanio;;kg\n'
            'Ser;1;1;koniec marca;kg\n',
        )

        assert result['imported'] == 0
        assert 'tanio' in result['errors'][0]['error']
        assert 'koniec marca' in result['errors'][1]['error']
