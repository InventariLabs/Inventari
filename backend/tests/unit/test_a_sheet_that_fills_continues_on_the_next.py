"""An export is written row by row, and a sheet that fills continues on the next.

A workbook built in memory grew a worker until its container killed it at
100 000 products, and an xlsx sheet holds at most 1 048 576 rows, so a
million-product export failed even with the memory. The rows now go to a
temporary file as they come, and the answer for a catalogue past one sheet
is the next sheet, header included.
"""

import io

import pytest
from openpyxl import load_workbook

from app.core import xlsx_export
from app.core.xlsx_export import rows_to_xlsx_response


async def _workbook(response):
    body = b''.join([chunk async for chunk in response.body_iterator])
    return load_workbook(io.BytesIO(body))


async def test_rows_past_a_full_sheet_continue_on_the_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(xlsx_export, 'MAX_ROWS_PER_SHEET', 2)

    response = rows_to_xlsx_response(
        ['Name', 'Quantity'],
        ([f'Item {n}', n] for n in range(5)),
        sheet_name='Inventory',
        filename_stem='test',
    )

    workbook = await _workbook(response)
    assert workbook.sheetnames == ['Inventory', 'Inventory 2', 'Inventory 3']
    names = [
        [row[0] for row in workbook[sheet].iter_rows(values_only=True)]
        for sheet in workbook.sheetnames
    ]
    assert names == [
        ['Name', 'Item 0', 'Item 1'],
        ['Name', 'Item 2', 'Item 3'],
        ['Name', 'Item 4'],
    ]


async def test_an_empty_export_still_has_its_header() -> None:
    response = rows_to_xlsx_response(
        ['Name', 'Quantity'], iter(()), sheet_name='Inventory', filename_stem='test'
    )

    workbook = await _workbook(response)
    assert list(workbook['Inventory'].iter_rows(values_only=True)) == [
        ('Name', 'Quantity')
    ]


async def test_a_cell_that_looks_like_a_formula_stays_text() -> None:
    response = rows_to_xlsx_response(
        ['Name'],
        [["=cmd|'/c calc'!A1"]],
        sheet_name='Inventory',
        filename_stem='test',
    )

    cell = (await _workbook(response))['Inventory']['A2']
    assert cell.data_type == 's'
    assert cell.value == "=cmd|'/c calc'!A1"
