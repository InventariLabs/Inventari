"""A number or a date in a sheet is read the way the sheet's country writes it.

A European Excel writes "12,5", "1 289,00 zł" and "05.11.2026"; an English
one writes "$1,289.00" and "11/05/2026". One reader serves every import door,
so a sheet that is right in its own country is right in the product import,
the opening stock, the document lines, the order lines and the equipment
import alike.
"""

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from app.core.import_sheet import (
    SheetColumns,
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
    yield
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
            ('12,5 EUR', '12.5'),
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
        assert parse_sheet_number(cell, money=True) == Decimal(expected)

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
    def test_a_csv_column_of_dot_groups_reads_every_one_as_thousands(
        self, lang: str, cell: str, expected: str
    ) -> None:
        set_current_lang(lang)
        sheet = SheetColumns(read_rows(b'a;qty\nx;1.250\ny;1.234\n', 'sheet.csv'))
        assert sheet.number(cell, 'qty') == Decimal(expected)

    @pytest.mark.parametrize('lang', ['de', 'es', 'pl', 'fr', 'pt'])
    def test_a_decimal_dot_in_the_column_settles_the_dot_as_decimal(
        self, lang: str
    ) -> None:
        set_current_lang(lang)
        sheet = SheetColumns(
            read_rows(b'a,qty\nx,2.5\ny,1.255\nz,0.125\nw,12.375\n', 'sheet.csv')
        )
        assert [
            sheet.number(v, 'qty') for v in ('2.5', '1.255', '0.125', '12.375')
        ] == [Decimal('2.5'), Decimal('1.255'), Decimal('0.125'), Decimal('12.375')]

    @pytest.mark.parametrize('lang', ['en', 'de'])
    def test_a_decimal_comma_in_the_column_settles_the_dot_as_thousands(
        self, lang: str
    ) -> None:
        set_current_lang(lang)
        sheet = SheetColumns(
            read_rows(b'a;qty\nx;2,5\ny;1.250\nz;1.234\n', 'sheet.csv')
        )
        assert sheet.number('1.250', 'qty') == Decimal('1250')
        assert sheet.number('1.234', 'qty') == Decimal('1234')
        assert sheet.number('2,5', 'qty') == Decimal('2.5')

    @pytest.mark.parametrize('lang', ['en', 'de', 'pl'])
    def test_a_decimal_comma_in_the_column_makes_a_lone_comma_decimal(
        self, lang: str
    ) -> None:
        set_current_lang(lang)
        sheet = SheetColumns(read_rows(b'a;qty\nx;12,5\ny;1,250\nz;2\n', 'sheet.csv'))
        assert sheet.number('1,250', 'qty') == Decimal('1.25')
        assert sheet.number('12,5', 'qty') == Decimal('12.5')

    @pytest.mark.parametrize('lang', ['en', 'de', 'pl'])
    def test_a_decimal_dot_in_the_column_makes_a_lone_comma_thousands(
        self, lang: str
    ) -> None:
        set_current_lang(lang)
        sheet = SheetColumns(
            read_rows(b'a;qty\nx;1,234.50\ny;1,250\nz;2.5\n', 'sheet.csv')
        )
        assert sheet.number('1,250', 'qty') == Decimal('1250')
        assert sheet.number('1,234.50', 'qty') == Decimal('1234.50')

    def test_an_undecided_column_reads_a_lone_comma_by_the_language(self) -> None:
        sheet = SheetColumns(read_rows(b'a;qty\nx;1,250\ny;2\n', 'sheet.csv'))
        set_current_lang('en')
        assert sheet.number('1,250', 'qty') == Decimal('1250')
        set_current_lang('pl')
        assert SheetColumns(read_rows(b'a;qty\nx;1,250\ny;2\n', 'sheet.csv')).number(
            '1,250', 'qty'
        ) == Decimal('1.25')

    def test_a_pasted_column_is_typed_text_like_a_file_column(self) -> None:
        from app.modules.warehouse.document_import_service import parse_pasted_text

        set_current_lang('de')
        sheet = SheetColumns(parse_pasted_text('Name\tQty\nA\t1.250\nB\t1.234\n'))
        assert sheet.number('1.250', 'Qty') == Decimal('1250')
        assert sheet.number('1.234', 'Qty') == Decimal('1234')

    def test_an_english_pasted_column_in_a_polish_session_keeps_its_comma_groups(
        self,
    ) -> None:
        from app.modules.warehouse.document_import_service import parse_pasted_text

        set_current_lang('pl')
        sheet = SheetColumns(
            parse_pasted_text('Name\tQty\nA\t1,234.50\nB\t1,250\nC\t2.5\n')
        )
        assert [sheet.number(v, 'Qty') for v in ('1,234.50', '1,250', '2.5')] == [
            Decimal('1234.50'),
            Decimal('1250'),
            Decimal('2.5'),
        ]

    def test_a_workbook_column_keeps_its_decimal_dot(self) -> None:
        set_current_lang('de')
        frame = pd.DataFrame({'qty': ['2.125', '3.375', '1.200']})
        sheet = SheetColumns(frame)
        assert sheet.number('2.125', 'qty') == Decimal('2.125')
        assert sheet.number('1.200', 'qty') == Decimal('1200')

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

    @pytest.mark.parametrize(
        'cell',
        [
            '3 ft',
            '10 ft',
            '2 kr',
            '5 fr',
            '3 lei',
            '2 cup',
            '2 CUP',
            '3 top',
            '2 TOP',
            '5 all',
            '5 ALL',
            '1 bob',
            'PLN 12',
        ],
    )
    def test_a_word_beside_a_quantity_is_not_dropped(self, cell: str) -> None:
        """``ft`` is the forint and feet, ``CUP`` the Cuban peso and a cup.

        Only a price cell names a currency. Anywhere else the word is the
        sheet's own unit, and the cell is refused rather than read as a bare
        number with its unit dropped.
        """
        with pytest.raises(ValueError):
            parse_sheet_number(cell)
        sheet = SheetColumns(pd.DataFrame({'qty': [cell]}))
        with pytest.raises(ValueError):
            sheet.number(cell, 'qty')

    @pytest.mark.parametrize(
        ('cell', 'expected'),
        [
            ('12,5 eur', '12.5'),
            ('12,5 Eur', '12.5'),
            ('12 usd', '12'),
            ('pln 12,5', '12.5'),
            ('PLN 12,5', '12.5'),
            ('1 290 Ft', '1290'),
            ('12,50 ZŁ', '12.50'),
        ],
    )
    def test_a_price_reads_its_currency_whatever_its_case(
        self, cell: str, expected: str
    ) -> None:
        sheet = SheetColumns(pd.DataFrame({'price': [cell]}))
        assert sheet.number(cell, 'price', money=True) == Decimal(expected)

    def test_a_price_with_its_code_still_settles_its_columns_dot(self) -> None:
        set_current_lang('en')
        sheet = SheetColumns(pd.DataFrame({'price': ['12,5 eur', '1.250 eur']}))
        assert sheet.number('1.250 eur', 'price', money=True) == Decimal('1250')

    @pytest.mark.parametrize(
        ('cell', 'restated'), [('1.250 eur', '1250'), ('3 ft', None)]
    )
    def test_a_cell_taken_out_of_its_column_is_restated_as_it_was_read(
        self, cell: str, restated: str | None
    ) -> None:
        """The refused-rows file keeps a price's reading and a quantity's unit."""
        set_current_lang('en')
        money = restated is not None
        sheet = SheetColumns(pd.DataFrame({'a': ['12,5', cell]}))
        if money:
            sheet.number(cell, 'a', money=True)
        else:
            with pytest.raises(ValueError):
                sheet.number(cell, 'a')
        assert sheet.restate(cell, 'a') == restated


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

    def test_a_twelve_hour_time_follows_the_order_its_column_decided(self) -> None:
        """``AM`` after the time is part of the time, not a reason to guess.

        The suffix is read where the column's order is applied, so the day
        keeps its place and an expiry term does not move by months.
        """
        assert parse_sheet_date('05/11/2026 10:30 AM', True) == date(2026, 11, 5)
        assert parse_sheet_date('05/11/2026 10:30 AM', False) == date(2026, 5, 11)
        assert parse_sheet_date('05/11/2026 10:30:15 pm', True) == date(2026, 11, 5)
        assert parse_sheet_date('05.11.2026 10:30 a.m.', True) == date(2026, 11, 5)

    @pytest.mark.parametrize(
        'cell',
        [
            '05/11/2026 10 AM',
            '05/11/2026 10pm',
            '05/11/2026, 10:30',
            '05/11/2026, 10:30 AM',
            '05/11/2026,10:30:15',
            '05/11/2026 10h30',
            '05/11/2026 10h',
            '05/11/2026 10:30 UTC',
            '05/11/2026 10:30:00 +01:00',
            '5. 11. 2026',
            '05 / 11 / 2026, 10:30',
            '2026-11-05, 10:30',
            '2026-11-05 10:30:00 UTC',
        ],
    )
    def test_a_time_however_written_keeps_the_day_where_the_column_put_it(
        self, cell: str
    ) -> None:
        assert parse_sheet_date(cell, True) == date(2026, 11, 5)

    @pytest.mark.parametrize(
        'cell',
        [
            '05/11/2026 morning',
            '05/11/2026 - 10:30',
            '05/11/2026 at 10:30',
            'Thu 05/11/2026',
            '10:30 05/11/2026',
            '05.11.26 half past ten',
        ],
    )
    def test_a_year_last_date_in_an_unknown_shape_is_refused_not_guessed(
        self, cell: str
    ) -> None:
        """No other reader gets to choose which part of it is the month."""
        with pytest.raises(ValueError):
            parse_sheet_date(cell, True)

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
        dates = SheetColumns(sheet)
        assert dates.date('05.11.2026', 'expiry') == date(2026, 11, 5)

    def test_a_time_on_the_date_does_not_hide_it_from_its_column(self) -> None:
        sheet = read_rows(
            b'name;at\nA;05/11/2026 10:30 AM\nB;28/02/2025\n', 'sheet.csv'
        )
        dates = SheetColumns(sheet)
        assert dates.date('05/11/2026 10:30 AM', 'at') == date(2026, 11, 5)


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

    async def test_a_date_with_a_time_is_shown_as_its_stored_day(self) -> None:
        from app.core.file_import import analyze_import_file

        report = await analyze_import_file(
            b'name;expiry\nA;05/11/2026 10:30 AM\nB;28/02/2025\n', 'sheet.csv'
        )

        assert report['preview_rows'][0]['expiry'] == '5 lis 2026'

    async def test_the_cells_as_written_ride_along_for_a_text_field(self) -> None:
        """A date-shaped column is a batch number as often as an expiry.

        The mapping step shows the stored day for a date field and the text
        as written for a text field, so the analysis carries both readings;
        rewriting the only preview would move a batch number's date.
        """
        from app.core.file_import import analyze_import_file

        report = await analyze_import_file(
            b'name;batch\nA;05.11.2026\nB;28.02.2025\n', 'sheet.csv'
        )

        assert [row['batch'] for row in report['preview_rows']] == [
            '5 lis 2026',
            '28 lut 2025',
        ]
        assert [row['batch'] for row in report['preview_rows_as_written']] == [
            '05.11.2026',
            '28.02.2025',
        ]
