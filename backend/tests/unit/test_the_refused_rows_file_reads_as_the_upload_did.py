"""The file of refused rows reads the way the upload did.

It carries the upload's own columns and the reason, in the upload's format.
A cell the whole sheet decided — a day before a month, a dot grouping
thousands — keeps that meaning when only the refused rows are uploaded.
"""

from __future__ import annotations

import base64
import io

import openpyxl
import pandas as pd
import pytest

from app.core.import_sheet import SheetColumns, read_rows
from app.core.refused_rows import refused_rows_file
from app.i18n.service import set_current_lang


@pytest.fixture(autouse=True)
def _english() -> None:
    set_current_lang('en')


def _decoded(answer: dict) -> bytes:
    return base64.b64decode(answer['content_base64'])


def _refusals(*rows: int) -> list[dict]:
    return [{'row': row, 'error': f'no {row}'} for row in rows]


def test_a_csv_comes_back_with_its_delimiter_its_columns_and_a_reason() -> None:
    content = 'Name;Code;Note\nBolt;007;a, b\nNut;010;\nScrew;;x\n'.encode('cp1250')
    df = read_rows(content, 'parts.csv')

    answer = refused_rows_file(df, _refusals(3, 1), 'parts.csv')

    assert answer is not None
    assert answer['filename'] == 'parts-refused.csv'
    assert _decoded(answer).decode('utf-8-sig').splitlines() == [
        'Name;Code;Note;Reason refused',
        'Bolt;007;a, b;no 1',
        'Screw;;x;no 3',
    ]
    again = read_rows(_decoded(answer), answer['filename'])
    assert again['Code'][0] == '007'
    assert pd.isna(again['Code'][1])


def test_a_workbook_comes_back_as_a_workbook_with_its_text_cells() -> None:
    workbook = openpyxl.Workbook()
    workbook.active.append(['Name', 'Code'])
    workbook.active.append(['=1+1', '007'])
    output = io.BytesIO()
    workbook.active['A2'].data_type = 's'
    workbook.save(output)
    df = read_rows(output.getvalue(), 'Stock list.XLSX')

    answer = refused_rows_file(df, _refusals(1), 'Stock list.XLSX')

    assert answer is not None
    assert answer['filename'] == 'Stock list-refused.xlsx'
    sheet = openpyxl.load_workbook(io.BytesIO(_decoded(answer))).active
    assert [[cell.value for cell in row] for row in sheet.iter_rows()] == [
        ['Name', 'Code', 'Reason refused'],
        ['=1+1', '007', 'no 1'],
    ]
    assert sheet['A2'].data_type == 's'


def test_a_formula_in_a_csv_cell_is_defused_and_reads_back_unchanged() -> None:
    df = read_rows(b'Name\n=cmd()\n', 'x.csv')

    answer = refused_rows_file(df, _refusals(1), 'x.csv')

    assert answer is not None
    assert '\t=cmd()' in _decoded(answer).decode('utf-8-sig')
    again = read_rows(_decoded(answer), 'x.csv')
    assert str(again['Name'][0]).strip() == '=cmd()'


def test_dates_the_whole_sheet_decided_keep_their_day() -> None:
    set_current_lang('pl')
    # 06/25 says the month comes first; alone, 05/06 would read as 5 June.
    df = read_rows(b'Name,Expiry\nA,05/06/2020\nB,06/25/2020\n', 'x.csv')
    sheet = SheetColumns(df)
    assert sheet.date('05/06/2020', 'Expiry').isoformat() == '2020-05-06'

    answer = refused_rows_file(df, _refusals(1), 'x.csv', sheet)

    assert answer is not None
    assert read_rows(_decoded(answer), 'x.csv')['Expiry'][0] == '2020-05-06'


@pytest.mark.parametrize(
    ('lang', 'column', 'written'),
    [
        # A decimal comma elsewhere in the column: the dot groups thousands.
        ('en', '1.234\n"2,5"', '1234'),
        # A decimal dot elsewhere: in German "1.200" alone would be 1200.
        ('de', '1.200\n2.5', '1.2000'),
    ],
)
def test_numbers_the_whole_sheet_decided_keep_their_value(
    lang: str, column: str, written: str
) -> None:
    set_current_lang(lang)
    df = read_rows(f'Quantity\n{column}\n'.encode(), 'x.csv')
    sheet = SheetColumns(df)
    first = sheet.number(df['Quantity'][0], 'Quantity')

    answer = refused_rows_file(df, _refusals(1), 'x.csv', sheet)

    assert answer is not None
    again = read_rows(_decoded(answer), 'x.csv')
    assert again['Quantity'][0] == written
    assert SheetColumns(again).number(written, 'Quantity') == first


def test_a_column_no_door_read_as_a_number_is_left_as_typed() -> None:
    df = read_rows(b'SKU,Other\n1.200,"2,5"\n', 'x.csv')

    answer = refused_rows_file(df, _refusals(1), 'x.csv', SheetColumns(df))

    assert answer is not None
    assert read_rows(_decoded(answer), 'x.csv')['SKU'][0] == '1.200'


def test_a_second_attempt_replaces_the_reason_column() -> None:
    df = read_rows(b'Name,Reason refused\nA,old\n', 'x-refused.csv')

    answer = refused_rows_file(df, _refusals(1), 'x-refused.csv')

    assert answer is not None
    assert answer['filename'] == 'x-refused.csv'
    assert _decoded(answer).decode('utf-8-sig').splitlines() == [
        'Name,Reason refused',
        'A,no 1',
    ]


def test_no_refusal_makes_no_file() -> None:
    df = read_rows(b'Name\nA\n', 'x.csv')

    assert refused_rows_file(df, [], 'x.csv') is None
