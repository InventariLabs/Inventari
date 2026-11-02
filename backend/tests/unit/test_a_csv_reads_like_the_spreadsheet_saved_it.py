"""A CSV reads the way the spreadsheet actually saved it.

Excel in most European locales writes a semicolon between columns and the
bytes as cp1250, and it prepends a BOM even when it does pick utf-8. The
reader assumed a comma in utf-8, so the shortest path a user knows — save
as CSV, upload — handed the mapping step one column named after the whole
header row, mangled every Polish letter, or refused the file with a raw
Python codec traceback.

Every upload door reads through the one tolerant reader in
``import_sheet`` now: products, partners and opening-stock through
``read_rows`` and the analyze preview, the order-line import, the
equipment import and the document import alike. What a row becomes is the
door's own business; how a sheet is read is the reader's, and a sheet the
reader misreads would be misread everywhere.
"""

import pytest

from app.core.file_import import analyze_import_file
from app.core.import_sheet import read_rows
from app.modules.warehouse.document_import_service import parse_pasted_text

pytestmark = pytest.mark.unit

SEMICOLON = b'nazwa;ilosc;jednostka\nM\xc4\x85ka;3;kg\n'
CP1250 = 'nazwa,ilosc\nMąka żytnia,3\n'.encode('cp1250')
BOM_SEMICOLON = 'nazwa;ilosc\nMąka;3\n'.encode('utf-8-sig')
BOM_PLAIN = 'nazwa,ilosc\nMąka,3\n'.encode('utf-8-sig')
PLAIN = b'nazwa,ilosc\nM\xc4\x85ka,3\n'
ONE_COLUMN = b'nazwa\nMaka\nKefir\n'


class TestTheProductSheetShell:
    async def test_a_semicolon_sheet_has_one_column_per_header_field(self) -> None:
        report = await analyze_import_file(SEMICOLON, 'sheet.csv')
        assert report['headers'] == ['nazwa', 'ilosc', 'jednostka']

    def test_a_cp1250_sheet_keeps_the_polish_letters(self) -> None:
        df = read_rows(CP1250, 'sheet.csv')
        assert df.iloc[0]['nazwa'] == 'Mąka żytnia'

    async def test_a_bom_semicolon_sheet_reads_whole_without_the_prefix(self) -> None:
        # Excel adds the BOM even when it saves utf-8, and in Polish
        # locales it saves semicolons: one file carrying all three quirks
        # (BOM, delimiter, Polish letters) reads whole or not at all.
        report = await analyze_import_file(BOM_SEMICOLON, 'sheet.csv')
        assert report['headers'] == ['nazwa', 'ilosc']
        assert read_rows(BOM_SEMICOLON, 'sheet.csv').iloc[0]['nazwa'] == 'Mąka'

    async def test_a_bom_comma_sheet_never_grows_an_invisible_prefix(self) -> None:
        # Honest about what carries this criterion: pandas 3.0.5 strips the
        # BOM itself, before any encoding the reader names, so the prefix
        # never reaches a column name on this stack and this test is green
        # under every sabotage of the reader's own code. It documents the
        # behaviour the criterion asks for and the utf-8-sig rung stands as
        # defence in depth for a pandas that stops eating the BOM.
        report = await analyze_import_file(BOM_PLAIN, 'sheet.csv')
        assert report['headers'][0] == 'nazwa'

    async def test_a_tab_sheet_splits_like_a_semicolon_one(self) -> None:
        report = await analyze_import_file(
            b'nazwa\tilosc\nM\xc4\x85ka\t3\n', 'sheet.csv'
        )
        assert report['headers'] == ['nazwa', 'ilosc']

    async def test_a_plain_comma_sheet_reads_as_it_always_did(self) -> None:
        report = await analyze_import_file(PLAIN, 'sheet.csv')
        assert report['headers'] == ['nazwa', 'ilosc']

    def test_a_one_column_sheet_stays_one_column(self) -> None:
        # The delimiter probe refuses to invent columns the file has not
        # got: when every candidate splits the header the same way, the
        # comma the reader always assumed stays the answer.
        assert list(read_rows(ONE_COLUMN, 'sheet.csv').columns) == ['nazwa']

    async def test_semicolons_inside_quoted_headers_do_not_steal_the_split(
        self,
    ) -> None:
        # A comma sheet with a descriptive header cell used to lose to the
        # semicolons inside the quotes: the probe counted them and split the
        # header into four garbage columns. A comma that already yields more
        # than one column is never overruled.
        sheet = b'nazwa,"opis; a; b; c",ilosc\n'
        report = await analyze_import_file(sheet, 'sheet.csv')
        assert report['headers'] == ['nazwa', 'opis; a; b; c', 'ilosc']

    async def test_binary_junk_is_refused_not_parsed_as_one_column(self) -> None:
        # cp1250 names 251 of 256 bytes, so the tolerant ladder decodes
        # almost any blob; a spreadsheet header is text, and control bytes
        # in it mean the rung is naming noise, not a sheet.
        with pytest.raises(ValueError):
            await analyze_import_file(b'\xff\xfe\x00\x01\x02\x03', 'data.csv')

    async def test_a_zero_width_space_in_a_utf8_header_stays_utf8(self) -> None:
        # A header pasted from a web page or a PDF carries a zero-width
        # space (category Cf). The bytes are printable in cp1250, so a
        # guard that bans "unprintable" characters sent the ladder down a
        # rung and the whole sheet came back as confident mojibake under a
        # 200 — 'M?ka ?ytnia' stored beside its correct twin. Format
        # characters are text: the rung that names them names the file.
        sheet = 'nazwa\u200b,ilosc\nMąka,3\n'.encode()
        report = await analyze_import_file(sheet, 'sheet.csv')
        assert report['headers'] == ['nazwa\u200b', 'ilosc']
        rows = read_rows(sheet, 'sheet.csv')
        # The zero-width space is part of the file's own header name and
        # rides faithfully — the failure was the whole sheet falling to
        # cp1250, not the extra character.
        assert rows.iloc[0]['nazwa\u200b'] == 'Mąka'

    async def test_a_no_break_space_in_a_utf8_header_reads_like_text(self) -> None:
        # The same shape from the other side: a hard space (U+00A0) or a
        # soft hyphen is ordinary spreadsheet furniture, and a guard that
        # banned it refused a legal file with no reason at all.
        for furniture in (
            'nazwa\u00a0x,ilosc\nMąka,3\n',
            'nazwa\u00ad,ilosc\nMąka,3\n',
            'nazwa,ilosc\nMąka 🥕,3\n',
        ):
            report = await analyze_import_file(furniture.encode(), 'sheet.csv')
            assert report['headers'][0].startswith('nazwa')
            assert report['headers'][1] == 'ilosc'

    def test_a_digit_column_keeps_the_leading_zero(self) -> None:
        # '007' is a serial number, not a seven. pandas types an all-digit
        # column as int64 — or float64 the moment one cell under it is
        # blank — and the zero is gone before any door sees the cell: no
        # amount of post-processing can tell '007' from '7' or '070'. The
        # reader owes the door the text the sheet typed; equipment holds
        # serials with leading zeros and UPC-A barcodes start with one.
        sheet = b'name,serial,tag\nScanner A,007,0123\nScanner B,,0456\n'
        rows = read_rows(sheet, 'sheet.csv')
        assert rows.iloc[0]['serial'] == '007'
        assert rows.iloc[0]['tag'] == '0123'

    async def test_the_guard_refusal_points_at_the_control_it_found(self) -> None:
        # The codec's sentence (header not text, position 5) is the library's
        # and goes to the log; the reader gets the translated refusal.
        with pytest.raises(ValueError) as excinfo:
            read_rows(b'nazwa\x00,ilosc\nMaka,3\n', 'sheet.csv')
        assert 'could not be read as a spreadsheet' in str(excinfo.value)
        assert 'position' not in str(excinfo.value)


class TestTheOtherDoorsReadLikeTheFirst:
    """The doors that once kept their own readers.

    The order-line import, the equipment import and the document import
    each read through the shared reader now — the wiring is pinned by each
    door's own tests (the PO refusal test, the equipment digits test, the
    document limit tests); what is pinned here is that the door the
    clipboard owns, the one parse outside the file reader, reads the way
    the file reader does.
    """

    async def test_analyze_counts_semicolon_columns(self) -> None:
        report = await analyze_import_file(SEMICOLON, 'sheet.csv')
        assert report['headers'] == ['nazwa', 'ilosc', 'jednostka']

    def test_a_semicolon_paste_keeps_the_polish_letters(self) -> None:
        df = parse_pasted_text('nazwa;ilosc\nMąka żytnia;3\n')
        assert list(df.columns) == ['nazwa', 'ilosc']
        assert df.iloc[0]['nazwa'] == 'Mąka żytnia'


class TestTheDelimiterAgreesWithTheRows:
    """A quoted cell in the header must not hand the split to a bystander.

    'nazwa;"cena, netto";ilosc' came back from analyze with two
    garbage columns: the comma candidate split the header inside the quotes
    and, consulted first, never let the sheet's own semicolon speak. The
    reader now asks the first rows too — a candidate qualifies only when
    every probed line splits into the same field count, quotes honored —
    and among the qualifying ones the widest split wins, the caller's
    candidate order still breaking a tie.
    """

    async def test_a_comma_in_a_quoted_header_of_a_semicolon_sheet(self) -> None:
        # The measured file from the task, a data row included: the comma's
        # two-field header disagrees with the one-field data row under the
        # comma, while the semicolon holds three fields everywhere.
        sheet = 'nazwa;"cena, netto";ilosc\nMąka;3,5;kg\n'.encode()
        report = await analyze_import_file(sheet, 'sheet.csv')
        assert report['headers'] == ['nazwa', 'cena, netto', 'ilosc']
        assert report['preview_rows'][0]['cena, netto'] == '3,5'

    async def test_a_semicolon_in_a_quoted_header_of_a_comma_sheet(self) -> None:
        # The mirror shape: the same theft in the other direction, and the
        # other half of what the honest-split rule guards — under a
        # semicolon the quote no longer opens the field, so the raw count
        # would let the semicolons inside the quotes win.
        sheet = b'nazwa,"waga; netto",ilosc\nMaka,3.5,kg\n'
        report = await analyze_import_file(sheet, 'sheet.csv')
        assert report['headers'] == ['nazwa', 'waga; netto', 'ilosc']

    async def test_a_quoted_header_with_no_rows_still_reads_whole(self) -> None:
        # A header-only upload has no rows to agree with; the wider split
        # is the honest one on its own, since the quotes protect their
        # content under either candidate.
        report = await analyze_import_file(b'nazwa;"cena, netto";ilosc\n', 'sheet.csv')
        assert report['headers'] == ['nazwa', 'cena, netto', 'ilosc']

    def test_a_pasted_semicolon_sheet_keeps_its_quoted_comma(self) -> None:
        # The paste path reads through the same reader with the paste's own
        # candidate order; the quoted cell survives it the same way.
        df = parse_pasted_text('nazwa;"cena, netto";ilosc\nMąka;3,5;kg')
        assert list(df.columns) == ['nazwa', 'cena, netto', 'ilosc']
        assert df.iloc[0]['cena, netto'] == '3,5'
