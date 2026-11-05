"""A row is read the way its writer meant it, and refused in the reader's words.

A Polish sheet wrote a piece as "szt" and an empty quantity as nothing. The
app writes "szt." and the import answered the first with a refusal that
named no unit it knew, and stored the second as 1 without a word — a stock
figure nobody typed. The reasons it did give were English in a Polish
session.
"""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.i18n.service import set_current_lang
from app.models.category import Category
from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.services.items._import import import_items

pytestmark = pytest.mark.integration

MAPPING = {'name': 'Name', 'quantity': 'Quantity', 'unit': 'Unit'}


def _csv(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _ctx(user) -> UserContextDTO:
    return UserContextDTO(
        id=user.id, organization_id=user.organization_id, role='admin'
    )


async def _import(db: AsyncSession, user, rows: list[dict], mapping=None) -> dict:
    return await import_items(
        db,
        _csv(rows),
        'stock.csv',
        mapping or MAPPING,
        _ctx(user),
        create_missing_locations=False,
        create_missing_categories=False,
    )


async def _count_named(db: AsyncSession, name: str) -> int:
    return (await db.scalar(select(func.count(Item.id)).where(Item.name == name))) or 0


class TestABlankQuantityIsNotAOne:
    async def test_a_mapped_quantity_left_blank_refuses_the_row(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        result = await _import(
            real_async_db_session,
            async_test_user,
            [
                {'Name': 'Flour', 'Quantity': '', 'Unit': 'kg'},
                {'Name': 'Sugar', 'Quantity': 2, 'Unit': 'kg'},
            ],
        )

        assert result['imported'] == 1
        assert result['failed'] == 1
        assert result['errors'] == [
            {
                'row': 1,
                'error': 'Column "Quantity": the quantity is empty. Fill it in, '
                'or clear the quantity mapping to import every row as 1',
            }
        ]
        assert await _count_named(real_async_db_session, 'Flour') == 0

    async def test_a_sheet_without_a_quantity_column_still_imports_as_one(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        result = await _import(
            real_async_db_session,
            async_test_user,
            [{'Name': 'Salt'}],
            mapping={'name': 'Name'},
        )

        assert result['imported'] == 1, result
        item = (
            await real_async_db_session.execute(select(Item).where(Item.name == 'Salt'))
        ).scalar_one()
        assert item.quantity == 1


class TestAUnitWithoutItsDot:
    @pytest.mark.parametrize(
        ('written', 'symbol'), [('szt', 'pcs'), ('szt.', 'pcs'), ('opak', 'pack')]
    )
    async def test_the_unit_is_the_one_it_names(
        self,
        real_async_db_session,
        async_test_user,
        async_test_storage_location,
        written,
        symbol,
    ):
        result = await _import(
            real_async_db_session,
            async_test_user,
            [{'Name': 'Eggs', 'Quantity': 3, 'Unit': written}],
        )

        assert result['imported'] == 1, result
        item = (
            await real_async_db_session.execute(select(Item).where(Item.name == 'Eggs'))
        ).scalar_one()
        await real_async_db_session.refresh(item, ['uom'])
        assert item.uom.symbol == symbol

    async def test_an_unknown_unit_lists_the_ones_the_app_knows(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        result = await _import(
            real_async_db_session,
            async_test_user,
            [{'Name': 'Eggs', 'Quantity': 3, 'Unit': 'bushel'}],
        )

        reason = result['errors'][0]['error']
        assert 'unknown unit "bushel"' in reason
        assert 'kg' in reason and 'pcs.' in reason


class TestEveryUnitTheRefusalOffersImports:
    @pytest.mark.parametrize(
        ('lang', 'written', 'symbol'),
        [
            ('de', 'Packung', 'pack'),
            ('de', 'Stk.', 'pcs'),
            ('de', 'stk', 'pcs'),
            ('fr', 'bouteille', 'bottle'),
            ('es', 'botella', 'bottle'),
        ],
    )
    async def test_a_label_the_app_shows_is_the_unit_it_names(
        self,
        real_async_db_session,
        async_test_user,
        async_test_storage_location,
        lang,
        written,
        symbol,
    ):
        set_current_lang(lang)
        try:
            result = await _import(
                real_async_db_session,
                async_test_user,
                [{'Name': 'Eggs', 'Quantity': 3, 'Unit': written}],
            )
        finally:
            set_current_lang('en')

        assert result['imported'] == 1, result
        item = (
            await real_async_db_session.execute(select(Item).where(Item.name == 'Eggs'))
        ).scalar_one()
        await real_async_db_session.refresh(item, ['uom'])
        assert item.uom.symbol == symbol


class TestTheReasonsSpeakTheReadersLanguage:
    async def test_polish_reasons(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        set_current_lang('pl')
        try:
            result = await _import(
                real_async_db_session,
                async_test_user,
                [
                    {'Name': 'Mąka', 'Quantity': 'abc', 'Unit': 'kg'},
                    {'Name': 'Cukier', 'Quantity': '', 'Unit': 'kg'},
                    {'Name': 'Sól', 'Quantity': 1, 'Unit': 'wiadro'},
                    {'Name': '', 'Quantity': 1, 'Unit': 'kg'},
                ],
            )
        finally:
            set_current_lang('en')

        reasons = [e['error'] for e in result['errors']]
        assert reasons[0] == 'Kolumna „Quantity”: „abc” nie jest liczbą'
        assert reasons[1].startswith('Kolumna „Quantity”: ilość jest pusta')
        assert reasons[2].startswith(
            'Kolumna „Unit”: nieznana jednostka „wiadro”. Znane jednostki: '
        )
        assert 'szt.' in reasons[2]
        assert reasons[3] == 'Brak nazwy produktu'

    async def test_a_value_outside_the_allowed_range_is_worded_in_polish(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        set_current_lang('pl')
        try:
            result = await _import(
                real_async_db_session,
                async_test_user,
                [
                    {'Name': 'Mąka', 'Quantity': -2, 'Unit': 'kg'},
                    {'Name': 'Cukier', 'Quantity': 99999999999, 'Unit': 'kg'},
                ],
            )
        finally:
            set_current_lang('en')

        reasons = [e['error'] for e in result['errors']]
        assert len(reasons) == 2
        for reason in reasons:
            assert reason.startswith('Kolumna „Quantity”: ')
            assert 'should be' not in reason

    async def test_a_number_that_is_not_finite_is_worded_in_polish(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        set_current_lang('pl')
        try:
            result = await _import(
                real_async_db_session,
                async_test_user,
                [
                    {'Name': 'Mąka', 'Quantity': 'Infinity', 'Unit': 'kg'},
                    {'Name': 'Cukier', 'Quantity': '-inf', 'Unit': 'kg'},
                ],
            )
        finally:
            set_current_lang('en')

        reasons = [e['error'] for e in result['errors']]
        assert reasons == ['Kolumna „Quantity”: Musi być liczbą'] * 2

    async def test_a_choice_outside_a_custom_field_is_worded_in_the_session_language(
        self, real_async_db_session, async_test_user, async_test_storage_type
    ):
        db = real_async_db_session
        db.add(
            StorageLocation(
                organization_id=async_test_user.organization_id,
                created_by=async_test_user.id,
                storage_type_id=async_test_storage_type.id,
                name='Półka wyboru',
                field_definitions=[
                    {
                        'key': 'colour',
                        'label': 'Kolor',
                        'type': 'select',
                        'options': ['czerwony', 'zielony'],
                    },
                    {
                        'key': 'tags',
                        'label': 'Tagi',
                        'type': 'multi-select',
                        'options': ['a', 'b'],
                    },
                ],
            )
        )
        await db.flush()

        for lang, expected in (
            ('pl', 'Kolumna „Kolor”: „niebieski” nie jest jedną z możliwości: '),
            ('de', 'Spalte „Kolor“: „niebieski“ ist keine der Auswahlmöglichkeiten: '),
            ('en', 'Column "Kolor": "niebieski" is not one of the choices: '),
        ):
            set_current_lang(lang)
            try:
                result = await _import(
                    db,
                    async_test_user,
                    [
                        {
                            'Name': 'Farba',
                            'Place': 'Półka wyboru',
                            'Kolor': 'niebieski',
                        },
                        {'Name': 'Klej', 'Place': 'Półka wyboru', 'Tagi': 'a, c'},
                    ],
                    mapping={
                        'name': 'Name',
                        'location': 'Place',
                        'field:colour': 'Kolor',
                        'field:tags': 'Tagi',
                    },
                )
            finally:
                set_current_lang('en')
            reasons = [e['error'] for e in result['errors']]
            assert reasons[0] == f'{expected}czerwony, zielony', (lang, reasons)
            assert 'declared options' not in reasons[1], (lang, reasons)
            assert 'Tagi' in reasons[1] and reasons[1].endswith(': a, b'), (
                lang,
                reasons,
            )

    async def test_a_choice_the_category_narrows_is_worded_in_the_session_language(
        self, real_async_db_session, async_test_user, async_test_storage_type
    ):
        """The shelf allows red; the category the row names allows only green."""
        db = real_async_db_session
        org = async_test_user.organization_id
        db.add_all(
            [
                StorageLocation(
                    organization_id=org,
                    created_by=async_test_user.id,
                    storage_type_id=async_test_storage_type.id,
                    name='Półka kategorii',
                    field_definitions=[
                        {
                            'key': 'colour',
                            'label': 'Kolor',
                            'type': 'select',
                            'options': ['czerwony', 'zielony'],
                        }
                    ],
                ),
                Category(
                    organization_id=org,
                    name='Zielone',
                    field_definitions=[
                        {
                            'key': 'colour',
                            'label': 'Kolor',
                            'type': 'select',
                            'options': ['zielony'],
                        }
                    ],
                ),
            ]
        )
        await db.flush()

        for lang, expected in (
            (
                'pl',
                'Kolumna „Kolor”: „czerwony” nie jest jedną z możliwości: zielony',
            ),
            (
                'de',
                'Spalte „Kolor“: „czerwony“ ist keine der Auswahlmöglichkeiten: zielony',
            ),
            ('en', 'Column "Kolor": "czerwony" is not one of the choices: zielony'),
        ):
            set_current_lang(lang)
            try:
                result = await _import(
                    db,
                    async_test_user,
                    [
                        {
                            'Name': 'Farba',
                            'Place': 'Półka kategorii',
                            'Category': 'Zielone',
                            'Kolor': 'czerwony',
                        }
                    ],
                    mapping={
                        'name': 'Name',
                        'location': 'Place',
                        'category': 'Category',
                        'field:colour': 'Kolor',
                    },
                )
            finally:
                set_current_lang('en')
            reasons = [e['error'] for e in result['errors']]
            assert reasons == [expected], (lang, reasons)

    async def test_a_cell_a_category_field_cannot_take_is_worded_in_the_session_language(
        self, real_async_db_session, async_test_user, async_test_storage_type
    ):
        """The shelf's text field is a price to the category: a cell has no currency."""
        db = real_async_db_session
        org = async_test_user.organization_id
        db.add_all(
            [
                StorageLocation(
                    organization_id=org,
                    created_by=async_test_user.id,
                    storage_type_id=async_test_storage_type.id,
                    name='Półka ceny',
                    field_definitions=[
                        {'key': 'cena', 'label': 'Cena', 'type': 'text'}
                    ],
                ),
                Category(
                    organization_id=org,
                    name='Wyceniane',
                    field_definitions=[
                        {'key': 'cena', 'label': 'Cena', 'type': 'money'}
                    ],
                ),
            ]
        )
        await db.flush()

        set_current_lang('pl')
        try:
            result = await _import(
                db,
                async_test_user,
                [
                    {
                        'Name': 'Obraz',
                        'Place': 'Półka ceny',
                        'Category': 'Wyceniane',
                        'Cena': '12',
                    }
                ],
                mapping={
                    'name': 'Name',
                    'location': 'Place',
                    'category': 'Category',
                    'field:cena': 'Cena',
                },
            )
        finally:
            set_current_lang('en')
        reasons = [e['error'] for e in result['errors']]
        assert reasons == [
            'Kolumna „Cena”: wartość nie pasuje do pola, do którego przypisano kolumnę'
        ]
