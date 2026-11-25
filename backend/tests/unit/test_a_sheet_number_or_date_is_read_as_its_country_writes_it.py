"""A number or a date in a sheet is read the way the sheet's country writes it.

A European Excel writes "12,5", "1 289,00 zł" and "05.11.2026"; an English
one writes "$1,289.00" and "11/05/2026". One reader serves every import door,
so a sheet that is right in its own country is right in the product import,
the opening stock, the document lines, the order lines and the equipment
import alike.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.import_sheet import (
    DateColumns,
    _sheet_is_csv,
    column_day_first,
    parse_sheet_date,
    parse_sheet_number,
    read_rows,
)
from app.i18n.service import set_current_lang

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _polish_reader():
    set_current_lang('pl')
    token = _sheet_is_csv.set(False)
    yield
    _sheet_is_csv.reset(token)
    set_current_lang('en')


class TestNumbers:
    @pytest.mark.parametrize(
        ('cell', 'expected'),
        [
            ('12,5', '12.5'),
            ('7,49', '7.49'),
            ('1 200', '1200'),
            ('1 200', '1200'),
            ('1 200', '1200'),
            ('1 289,00 zł', '1289.00'),
            ('€ 4,50', '4.50'),
            ('$4.50', '4.50'),
            ('$1,289.00', '1289.00'),
            ('1,099.00', '1099.00'),
            ('1.234,50', '1234.50'),
            ('1.234.567', '1234567'),
            ('1.200', '1200'),
            ('12.000', '12000'),
            ('1.200 €', '1200'),
            ('2.125', '2.125'),
            ('R$ 4,50', '4.50'),
            ('R$1.289,00', '1289.00'),
            ('PLN 12,5', '12.5'),
            ('12,5 eur', '12.5'),
            ("1'289.50", '1289.50'),
            ('-5,5', '-5.5'),
            ('0,125', '0.125'),
            ('1e-05', '0.00001'),
            ('3', '3'),
            ('2.5', '2.5'),
        ],
    )
    def test_a_price_or_quantity_as_it_is_written(
        self, cell: str, expected: str
    ) -> None:
        assert parse_sheet_number(cell) == Decimal(expected)

    def test_a_lone_comma_before_three_digits_follows_the_language(self) -> None:
        assert parse_sheet_number('1,250') == Decimal('1.25')
        set_current_lang('en')
        assert parse_sheet_number('1,250') == Decimal('1250')
        assert parse_sheet_number('4,50') == Decimal('4.50')
        assert parse_sheet_number('1.200') == Decimal('1.2')

    @pytest.mark.parametrize('lang', ['de', 'es', 'pl'])
    @pytest.mark.parametrize(
        ('cell', 'expected'),
        [
            ('1.234', '1234'),
            ('2.345', '2345'),
            ('12.345', '12345'),
            ('1.250', '1250'),
            ('1.255', '1255'),
            ('1.234 €', '1234'),
            ('0.125', '0.125'),
            ('1.5', '1.5'),
        ],
    )
    def test_a_csv_dot_before_three_digits_is_thousands_whatever_they_are(
        self, lang: str, cell: str, expected: str
    ) -> None:
        set_current_lang(lang)
        read_rows(b'a;b\nx;1\n', 'sheet.csv')
        assert parse_sheet_number(cell) == Decimal(expected)

    def test_a_workbook_number_cell_keeps_its_decimal_dot(self) -> None:
        set_current_lang('de')
        read_rows(b'a;b\nx;1\n', 'sheet.csv')
        assert parse_sheet_number('1.234') == Decimal('1234')
        _sheet_is_csv.set(False)
        assert parse_sheet_number('1.234') == Decimal('1.234')
        assert parse_sheet_number('1.200') == Decimal('1200')

    @pytest.mark.parametrize(
        'cell',
        [
            'abc',
            'tanio',
            '12abc',
            'zł',
            '',
            'NaN',
            'Infinity',
            '1,2,3',
            '1.2.3,4',
            '12 5',
        ],
    )
    def test_a_value_that_is_not_a_number_is_refused(self, cell: str) -> None:
        with pytest.raises(ValueError):
            parse_sheet_number(cell)


class TestDates:
    def test_a_day_first_date_is_not_swapped(self) -> None:
        assert parse_sheet_date('05.11.2026', True) == date(2026, 11, 5)
        assert parse_sheet_date('03/12/2025', True) == date(2025, 12, 3)
        assert parse_sheet_date('12.01.2025', True) == date(2025, 1, 12)

    def test_a_month_first_date_stays_month_first(self) -> None:
        assert parse_sheet_date('11/05/2026', False) == date(2026, 11, 5)

    def test_a_part_above_twelve_settles_the_value_itself(self) -> None:
        assert parse_sheet_date('28.02.2025', False) == date(2025, 2, 28)
        assert parse_sheet_date('02/28/2025', True) == date(2025, 2, 28)

    @pytest.mark.parametrize(
        'cell',
        ['2026-11-05', '2026-11-05 00:00:00', '2026-11-05T10:30:00', '5 Nov 2026'],
    )
    def test_unambiguous_shapes_read_the_same_both_ways(self, cell: str) -> None:
        assert parse_sheet_date(cell, True) == date(2026, 11, 5)
        assert parse_sheet_date(cell, False) == date(2026, 11, 5)

    @pytest.mark.parametrize(
        'cell', ['end of March', 'tomorrow-ish', '31.02.2026', '99']
    )
    def test_an_unreadable_date_is_refused(self, cell: str) -> None:
        with pytest.raises(ValueError):
            parse_sheet_date(cell, True)

    def test_an_all_ambiguous_column_follows_the_language(self) -> None:
        assert column_day_first(['05.11.2026', '03/12/2025']) is True
        set_current_lang('en')
        assert column_day_first(['05.11.2026', '03/12/2025']) is False

    def test_one_value_settles_the_whole_column(self) -> None:
        set_current_lang('en')
        assert column_day_first(['05.11.2026', '28.02.2025']) is True
        set_current_lang('pl')
        assert column_day_first(['05.11.2026', '02/28/2025']) is False

    def test_a_row_is_read_by_what_its_column_says(self) -> None:
        sheet = read_rows(b'name;expiry\nA;05.11.2026\nB;28.02.2025\n', 'sheet.csv')
        set_current_lang('en')
        dates = DateColumns(sheet)
        assert dates.parse('05.11.2026', 'expiry') == date(2026, 11, 5)


class TestThePreviewShowsTheDateAsItWillBeStored:
    async def test_a_day_first_column_is_shown_as_its_stored_day(self) -> None:
        from app.core.file_import import analyze_import_file

        report = await analyze_import_file(
            b'name;expiry;qty\nA;05.11.2026;3\nB;28.02.2025;4\n', 'sheet.csv'
        )

        shown = [row['expiry'] for row in report['preview_rows']]
        assert shown == ['5 lis 2026', '28 lut 2025']
        assert [row['qty'] for row in report['preview_rows']] == ['3', '4']

    async def test_an_all_ambiguous_column_is_shown_the_way_the_import_reads_it(
        self,
    ) -> None:
        from app.core.file_import import analyze_import_file

        set_current_lang('en')
        report = await analyze_import_file(b'name;expiry\nA;05.11.2026\n', 'sheet.csv')

        assert report['preview_rows'][0]['expiry'] == 'May 11, 2026'

    async def test_a_column_that_is_not_all_dates_is_left_as_written(self) -> None:
        from app.core.file_import import analyze_import_file

        report = await analyze_import_file(
            b'name;note\nA;05.11.2026\nB;end of March\n', 'sheet.csv'
        )

        assert report['preview_rows'][0]['note'] == '05.11.2026'
