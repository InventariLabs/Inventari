"""A corrected sheet can be uploaded whole.

In the skip and overwrite modes a row names a product already in stock by its
Label Code, its SKU or its barcode. Products the same sheet founds on the way
do not count: only what stood there before the upload does. A sheet in add
mode whose rows all find stock is told so before it is imported.
"""

from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.models.item import Item
from app.services.items._import import import_items
from app.services.items._import_existing import count_rows_in_stock_async

_MAPPING = {
    'name': 'Name',
    'sku': 'SKU',
    'barcode': 'Barcode',
    'quantity': 'Quantity',
    'location': 'Location',
}


def _csv(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _ctx(user) -> UserContextDTO:
    return UserContextDTO(
        id=user.id, organization_id=user.organization_id, role='admin'
    )


def _row(name: str, quantity: object, location: str, **extra: object) -> dict:
    return {
        'Name': name,
        'SKU': '',
        'Barcode': '',
        'Quantity': quantity,
        'Location': location,
        **extra,
    }


#: One product by SKU on two shelves, one by barcode, one by name only.
_SHEET = [
    _row('Flour', '12', 'Shelf A', SKU='FL-1'),
    _row('Flour', '2', 'Shelf B', SKU='FL-1'),
    _row('Boxes', '350', 'Shelf A', Barcode='5901234123457'),
    _row('Tape', '5', 'Shelf A'),
]


async def _upload(db, user, rows, mode='add', **kwargs):
    return await import_items(
        db,
        _csv(rows),
        'stock.csv',
        _MAPPING,
        _ctx(user),
        on_label_match=mode,
        **kwargs,
    )


async def _quantities(db: AsyncSession, org_id) -> list[tuple[str, Decimal]]:
    rows = await db.execute(
        select(Item.name, Item.quantity).where(
            Item.organization_id == org_id, Item.is_deleted.is_(False)
        )
    )
    return sorted((name, quantity) for name, quantity in rows.all())


@pytest.mark.integration
@pytest.mark.asyncio
class TestASecondUploadDoesNotDoubleTheStock:
    async def test_skip_mode_reads_a_second_upload_and_changes_no_quantity(
        self, real_async_db_session, async_test_user
    ):
        db = real_async_db_session
        sheet = _SHEET[:3]
        first = await _upload(db, async_test_user, sheet, mode='skip')
        await db.commit()
        before = await _quantities(db, async_test_user.organization_id)

        second = await _upload(db, async_test_user, sheet, mode='skip')
        await db.commit()

        # The first upload took both shelves of one product: a row does not
        # match a product its own sheet founded.
        assert (first['imported'], first['skipped']) == (3, 0), first
        assert (second['imported'], second['skipped']) == (0, 3), second
        assert await _quantities(db, async_test_user.organization_id) == before

    async def test_skip_mode_adds_the_row_that_was_refused_the_first_time(
        self, real_async_db_session, async_test_user
    ):
        db = real_async_db_session
        broken = [_SHEET[0], _row('Sugar', 'lots', 'Shelf A', SKU='SU-1')]
        first = await _upload(db, async_test_user, broken, mode='skip')
        await db.commit()
        corrected = [_SHEET[0], _row('Sugar', '3', 'Shelf A', SKU='SU-1')]

        second = await _upload(db, async_test_user, corrected, mode='skip')
        await db.commit()

        assert (first['imported'], first['failed']) == (1, 1), first
        assert (second['imported'], second['skipped']) == (1, 1), second
        assert await _quantities(db, async_test_user.organization_id) == [
            ('Flour', Decimal('12')),
            ('Sugar', Decimal('3')),
        ]

    async def test_overwrite_writes_onto_the_record_the_sku_and_place_name(
        self, real_async_db_session, async_test_user
    ):
        db = real_async_db_session
        await _upload(db, async_test_user, _SHEET[:3])
        await db.commit()
        before = await _quantities(db, async_test_user.organization_id)
        sheet = [
            _row('Flour', '99', 'Shelf B', SKU='FL-1', Brand='Mill'),
            _row('Cartons', '1', 'Shelf A', Barcode='5901234123457'),
        ]

        result = await import_items(
            db,
            _csv(sheet),
            'stock.csv',
            {**_MAPPING, 'brand': 'Brand'},
            _ctx(async_test_user),
            on_label_match='overwrite',
        )
        await db.commit()

        assert (result['updated'], result['imported']) == (2, 0), result
        after = await _quantities(db, async_test_user.organization_id)
        assert [q for _, q in sorted(after, key=lambda r: r[1])] == [
            q for _, q in sorted(before, key=lambda r: r[1])
        ]
        assert 'Cartons' in [name for name, _ in after]
        brands = await db.execute(
            select(Item.quantity, Item.brand).where(Item.brand == 'Mill')
        )
        assert brands.all() == [(Decimal('2'), 'Mill')]

    async def test_overwrite_refuses_a_row_that_fits_several_records(
        self, real_async_db_session, async_test_user
    ):
        db = real_async_db_session
        await _upload(db, async_test_user, _SHEET[:2])
        await db.commit()

        result = await _upload(
            db,
            async_test_user,
            [_row('Flour', '1', '', SKU='FL-1')],
            mode='overwrite',
        )

        assert (result['updated'], result['failed']) == (0, 1), result
        assert '2' in result['errors'][0]['error']

    async def test_add_mode_still_adds_a_row_that_finds_stock(
        self, real_async_db_session, async_test_user
    ):
        db = real_async_db_session
        await _upload(db, async_test_user, _SHEET[:1])
        await db.commit()

        result = await _upload(db, async_test_user, _SHEET[:1])

        assert (result['imported'], result['joined_existing']) == (1, 1), result


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheSheetIsToldWhatItWillAddAgain:
    async def test_every_row_of_an_imported_sheet_finds_stock(
        self, real_async_db_session, async_test_user
    ):
        db = real_async_db_session
        assert await count_rows_in_stock_async(
            db, _csv(_SHEET), 'stock.csv', _MAPPING, _ctx(async_test_user)
        ) == {'rows': 4, 'rows_in_stock': 0}
        await _upload(db, async_test_user, _SHEET)
        await db.commit()

        found = await count_rows_in_stock_async(
            db,
            _csv([*_SHEET, _row('Glue', '1', 'Shelf A', SKU='GL-1')]),
            'stock.csv',
            _MAPPING,
            _ctx(async_test_user),
        )

        assert found == {'rows': 5, 'rows_in_stock': 4}

    async def test_a_variant_of_a_name_in_stock_is_a_new_product(
        self, real_async_db_session, async_test_user
    ):
        db = real_async_db_session
        await _upload(db, async_test_user, _SHEET[:1])
        await db.commit()

        found = await count_rows_in_stock_async(
            db,
            _csv([_row('Flour', '1', 'Shelf A', SKU='FL-2')]),
            'stock.csv',
            _MAPPING,
            _ctx(async_test_user),
        )

        assert found == {'rows': 1, 'rows_in_stock': 0}

    async def test_a_sheet_without_quantities_adds_no_stock_to_warn_about(
        self, real_async_db_session, async_test_user
    ):
        db = real_async_db_session
        await _upload(db, async_test_user, _SHEET[:1])
        await db.commit()

        found = await count_rows_in_stock_async(
            db,
            _csv(_SHEET[:1]),
            'stock.csv',
            {'name': 'Name', 'sku': 'SKU'},
            _ctx(async_test_user),
        )

        assert found == {'rows': 0, 'rows_in_stock': 0}
