"""An equipment sheet is read the way its country writes numbers and dates.

Snipe-IT writes "1,289.00", Shelf "$1,289.00", a Polish Excel "1 289,00 zł"
and "05.11.2026". The price and the purchase and warranty dates go through
the one reader every import door shares, so each of them is the number and
the day the sheet holds — never a refusal for a thousands separator and
never a day swapped with its month.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.contracts import UserContextDTO
from app.i18n import Language
from app.i18n.service import set_current_lang
from app.modules.equipment.import_service import execute_equipment_import

pytestmark = pytest.mark.unit

MAPPING = {
    'name': 'name',
    'purchase_price': 'price',
    'purchase_date': 'bought',
    'warranty_until': 'warranty',
}


@pytest.fixture(autouse=True)
def _language() -> Iterator[None]:
    yield
    set_current_lang('en')


@pytest.fixture
def stubs() -> Iterator[MagicMock]:
    with (
        patch(
            'app.modules.equipment.import_service.resolve_storage_location_async',
            return_value=str(uuid4()),
        ),
        patch(
            'app.modules.equipment.import_service.resolve_category_async',
            return_value=None,
        ),
        patch(
            'app.modules.equipment.import_service.find_item_by_serial_async',
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch('app.core.public_api.core_api') as core,
    ):
        core.items.create_async = AsyncMock(return_value=MagicMock(id=uuid4()))
        yield core


async def _import(sheet: str, language: Language = 'pl') -> dict[str, Any]:
    set_current_lang(language)
    org_id = uuid4()
    return await execute_equipment_import(
        AsyncMock(begin_nested=MagicMock()),
        sheet.encode('cp1250'),
        'sprzet.csv',
        MAPPING,
        org_id,
        UserContextDTO(id=uuid4(), organization_id=org_id),
    )


def _created(stubs: MagicMock, index: int) -> Any:
    return stubs.items.create_async.await_args_list[index].kwargs['data']


class TestTheEquipmentImportReadsTheSheetsNumbersAndDates:
    async def test_prices_and_dates_are_what_the_sheet_wrote(
        self, stubs: MagicMock
    ) -> None:
        result = await _import(
            'name;price;bought;warranty\n'
            'Laptop;1 289,00 zł;05.11.2026;03/12/2025\n'
            'Drukarka;$1,289.00;28.02.2025;\n'
            'Monitor;1.289,00;2026-01-02 00:00:00;\n'
        )

        assert (result['imported'], result['failed']) == (3, 0), result['errors']
        laptop = _created(stubs, 0)
        assert str(laptop.purchase_price) == '1289.00'
        assert laptop.metadata['equipment']['purchase_date'] == '2026-11-05'
        assert laptop.metadata['equipment']['warranty_until'] == '2025-12-03'
        assert str(_created(stubs, 1).purchase_price) == '1289.00'
        assert str(_created(stubs, 2).purchase_price) == '1289.00'
        assert _created(stubs, 2).metadata['equipment']['purchase_date'] == '2026-01-02'

    async def test_an_all_ambiguous_column_follows_the_importers_language(
        self, stubs: MagicMock
    ) -> None:
        sheet = 'name;price;bought;warranty\nLaptop;1;05.11.2026;\n'

        await _import(sheet, 'en')
        assert _created(stubs, 0).metadata['equipment']['purchase_date'] == '2026-05-11'

    async def test_an_unreadable_price_or_date_names_its_cell(
        self, stubs: MagicMock
    ) -> None:
        result = await _import(
            'name;price;bought;warranty\nLaptop;tanio;;\nDrukarka;1;kiedys w maju;\n'
        )

        assert result['imported'] == 0
        assert 'tanio' in result['errors'][0]['error']
        assert 'kiedys w maju' in result['errors'][1]['error']
