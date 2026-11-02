"""The digits a spreadsheet cell typed stay the digits the asset holds.

pandas turns an all-digit column into floats the moment one cell in it is
blank, so a serial number read carelessly arrives as 5901234123457.0. The
dedicated reader dodged that by typing every cell as text; the shared core
reader dodges it by typing the sheet as text on both branches and keeping
``cell_text`` for a frame that arrives without the reader. These tests read
through the real reader — no stub between the sheet bytes and the payload —
so the protection has to live in the reader, not in the test.
"""

from collections.abc import Iterator
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pandas as pd
import pytest

from app.core.contracts import UserContextDTO
from app.modules.equipment.import_service import execute_equipment_import


def _csv(content: str) -> bytes:
    return content.encode('utf-8')


def _xlsx(rows: list[dict[str, Any]]) -> bytes:
    """A workbook as a spreadsheet program would save it.

    ``to_excel`` writes what the cell typed: a number as a numeric cell, a
    string as a text cell, ``None`` as a blank — the same cell types a
    hand-made sheet carries, so the reader gets the shapes a user sends.
    """
    buffer = BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False)
    return buffer.getvalue()


@pytest.mark.unit
class TestTheImportKeepsTheDigitsTheSheetTyped:
    @pytest.fixture
    def _stubs(self) -> Iterator[MagicMock]:
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

    async def _import(
        self, content: bytes, mapping: dict[str, str], filename: str = 'assets.csv'
    ) -> dict[str, Any]:
        org_id = uuid4()
        user = UserContextDTO(id=uuid4(), organization_id=org_id)
        return await execute_equipment_import(
            AsyncMock(),
            content,
            filename,
            mapping,
            org_id,
            user,
        )

    async def test_a_serial_with_a_blank_below_it_stays_digits(
        self, _stubs: MagicMock
    ) -> None:
        """The blank under it is what turns the column into floats.

        One blank cell in the column is enough for pandas to retype every
        other cell as a float; the digits must come out of the import the
        way the sheet typed them.
        """
        csv = _csv(
            'name,serial_number\nBarcode scanner,5901234123457\nLabel printer,\n'
        )
        result = await self._import(
            csv, {'name': 'name', 'serial_number': 'serial_number'}
        )

        assert result['imported'] == 2
        first = _stubs.items.create_async.await_args_list[0].kwargs['data']
        assert first.serial_number == '5901234123457'
        second = _stubs.items.create_async.await_args_list[1].kwargs['data']
        assert second.serial_number is None

    async def test_a_serial_with_a_leading_zero_stays_the_text_it_typed(
        self, _stubs: MagicMock
    ) -> None:
        """A zero the sheet typed is data, not padding pandas may drop.

        '007' in an all-digit column reaches the shared reader as int64
        and would leave cell_text as '7' unless the reader keeps the
        column as text — the serial the asset holds would then differ
        from the serial printed on the box.
        """
        csv = _csv('name,serial_number\nLaptop C,007\n')
        result = await self._import(
            csv, {'name': 'name', 'serial_number': 'serial_number'}
        )

        assert result['imported'] == 1
        payload = _stubs.items.create_async.await_args_list[0].kwargs['data']
        assert payload.serial_number == '007'

    async def test_a_serial_column_without_blanks_stays_digits(
        self, _stubs: MagicMock
    ) -> None:
        """A column pandas reads as integers keeps its digits too."""
        csv = _csv('name,serial_number\nScanner A,4077\nScanner B,4078\n')
        result = await self._import(
            csv, {'name': 'name', 'serial_number': 'serial_number'}
        )

        assert result['imported'] == 2
        payloads = [
            call.kwargs['data'] for call in _stubs.items.create_async.await_args_list
        ]
        assert [p.serial_number for p in payloads] == ['4077', '4078']

    async def test_a_sheet_named_in_capitals_reads_as_its_format(
        self, _stubs: MagicMock
    ) -> None:
        """An extension the browser upper-cased still names the format.

        'ASSETS.CSV' used to miss the case-sensitive comparison and land on
        the Excel branch, which refused a perfectly good sheet as an
        unreadable workbook.
        """
        csv = _csv('name,serial_number\nBarcode scanner,5901234123457\n')
        result = await self._import(
            csv,
            {'name': 'name', 'serial_number': 'serial_number'},
            filename='ASSETS.CSV',
        )

        assert result['imported'] == 1
        payload = _stubs.items.create_async.await_args_list[0].kwargs['data']
        assert payload.serial_number == '5901234123457'

    async def test_an_xlsx_sheet_keeps_the_text_and_the_digits_it_typed(
        self, _stubs: MagicMock
    ) -> None:
        """The workbook branch is under the same loss as the CSV branch.

        A text cell rides into the workbook as text, but pandas' inference
        on the column turns it into a float all the same — '007' comes off
        the frame as 7.0 and the zero is unrecoverable — while a cell the
        sheet typed as a number has to arrive as its digits and not as
        '5901234123457.0'. The reader must keep both, so this reads a
        workbook carrying one of each through the real reader.
        """
        xlsx = _xlsx(
            [
                {'name': 'XLSX scanner', 'serial_number': 5901234123457},
                {'name': 'XLSX printer', 'serial_number': None},
                {'name': 'XLSX laptop', 'serial_number': '007'},
            ]
        )
        result = await self._import(
            xlsx,
            {'name': 'name', 'serial_number': 'serial_number'},
            filename='assets.xlsx',
        )

        assert result['imported'] == 3
        payloads = [
            call.kwargs['data'] for call in _stubs.items.create_async.await_args_list
        ]
        assert [p.serial_number for p in payloads] == [
            '5901234123457',
            None,
            '007',
        ]
