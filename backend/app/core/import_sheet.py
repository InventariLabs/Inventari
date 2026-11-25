"""Reading a spreadsheet for an import — the part every entity shares.

Products and partners arrive the same way: a header row, a column mapping
chosen by the reader, one row per record, and a report that names the row
and the reason for each refusal. What differs per entity is what a row
becomes; what is here is how a row is read and how a refusal is worded.
"""

import re
from collections import Counter
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from math import isnan
from typing import Any
from unicodedata import category
from zipfile import BadZipFile

import pandas as pd
from babel.numbers import list_currencies
from pydantic import ValidationError

from app.core.exceptions import AppException, QuotaExceededError, ServiceRejectionError
from app.core.logging import get_logger
from app.core.upload_validation import MAX_IMPORT_ROWS
from app.i18n._validation import translate_validation_error
from app.i18n.service import get_current_lang, writes_decimal_comma

logger = get_logger(__name__)

#: The encodings an uploaded CSV may actually carry, in the order tried.
#: Excel in most European locales writes cp1250, and ``utf-8-sig`` reads
#: plain utf-8 and a BOM'd file with one codec. A file neither rung names
#: comes back as the decode refusal the callers already word.
_CSV_ENCODINGS = ('utf-8-sig', 'cp1250')

#: Delimiters a spreadsheet program writes into a file, in the order the
#: reader consults them: the comma first, and a non-comma separator only
#: when the comma cannot be right — when it leaves the whole header in one
#: column, the shape a semicolon sheet arrives in. Ranking candidates by
#: column count instead would let the semicolons inside a quoted header
#: cell ("name,"opis; a; b; c"") steal the split from a comma that already
#: worked. Sniffing the whole file instead mangles small sheets: pandas'
#: probe invents separators a one-column header has not got.
_CSV_DELIMITERS = (',', ';', '\t')

#: Delimiters clipboard text carries, in the order a paste writes them:
#: a spreadsheet paste is tabs, and the comma inside a header cell
#: ("Name, full") is part of the name — it must not steal the split from
#: the tab that already worked, the way a file's comma-first order reads it.
PASTE_DELIMITERS = ('\t', ';', ',')

#: How many lines the delimiter probe reads: the header plus the first
#: data rows. A candidate must split them all into the same field count
#: before it may win, so one line — usually the header with its quoted
#: cells — cannot decide alone.
_DELIMITER_PROBE_ROWS = 5


def _pick_delimiter(
    lines: list[str], candidates: tuple[str, ...] = _CSV_DELIMITERS
) -> str:
    """The candidate the sheet's first lines honestly agree on.

    A candidate qualifies when walking every probed line with it gives the
    same field count, the count is more than one — a sheet that never
    splits has no delimiter to detect — and the walk is HONEST: every
    quote character sits where it opens or closes a quoted field, never
    inside a field's text. A quote in a field's text means the candidate
    treated structure as content — the semicolons inside
    'nazwa,"opis; a; b; c",ilosc' split that comma line four ways
    precisely because under a semicolon the quote no longer opens the
    field. Among the qualifying candidates the widest split wins; the
    candidates' order breaks a tie, and the order each caller passes IS
    that caller's decision (a file is comma-first, clipboard text is
    tab-first).

    The agreement across lines is what a quoted cell in the header can no
    longer buy by itself: 'nazwa;"cena, netto";ilosc' splits two ways
    under the comma but three under the semicolon, and when the data rows
    hold three fields under the semicolon and one under the comma, the
    comma does not qualify at all. No qualifying candidate
    leaves the comma the reader always assumed.
    """
    probe = [line for line in lines if line.strip()]
    best: str | None = None
    best_width = 1
    for delimiter in candidates:
        counts = {_probe_fields(line, delimiter) for line in probe}
        if len(counts) != 1:
            continue
        width = counts.pop()
        if width is not None and width > best_width:
            best, best_width = delimiter, width
    return best if best is not None else ','


def _probe_fields(line: str, delimiter: str) -> int | None:
    """How many fields the line splits into under the delimiter, or
    ``None`` when the walk is not honest: a quote character met anywhere
    but at a field's start (or inside a quoted field, where a doubled
    quote is the escaped content) means this parse took a quote for
    content. A trailing carriage return is line furniture.
    """
    fields = 1
    in_quotes = False
    at_field_start = True
    i = 0
    while i < len(line):
        ch = line[i]
        i += 1
        if ch == '\r':
            continue
        if in_quotes:
            if ch == '"':
                if i < len(line) and line[i] == '"':
                    i += 1  # an escaped quote: content, not the closing one
                else:
                    in_quotes = False
        elif ch == '"':
            if not at_field_start:
                return None  # a quote inside a field's text: content read as structure
            in_quotes = True
        elif ch == delimiter:
            fields += 1
            at_field_start = True
            continue
        at_field_start = False
    if in_quotes:
        return None  # a quote that never closes: this parse invents a field
    return fields


def _header_is_text(header_line: str) -> bool:
    """A sheet's header is text, not control bytes.

    The test is for control characters (category ``Cc``) — the bytes a
    binary blob scatters — and nothing else. Everything a text header can
    legitimately carry stays welcome: a no-break space or a soft hyphen
    pasted from a web page is text (``isprintable`` said otherwise, and a
    legal sheet got a bare refusal for it), and so is a zero-width space —
    format characters decode cleanly, and sending the ladder down to
    cp1250 over them turned a correct utf-8 sheet into quiet mojibake
    under a 200. The tab is allowed as a delimiter and a trailing carriage
    return is line furniture.
    """
    return all(ch in ('\t', '\r') or category(ch) != 'Cc' for ch in header_line)


#: The ``attrs`` key of a frame read from delimited text: every value in it
#: is the text as typed. A workbook's number cell arrives as a float's text
#: instead, which reading a number has to tell apart from typed text.
_TEXT_SHEET = 'typed_text'


def read_csv_sheet(
    content: bytes, delimiters: tuple[str, ...] = _CSV_DELIMITERS, **kwargs: Any
) -> pd.DataFrame:
    """A CSV upload as a DataFrame, tolerant of how the spreadsheet saved it.

    A comma-and-utf-8-only reader turned the shortest path a user knows —
    save as CSV, upload — into one column named after the whole header row,
    or a codec traceback. The delimiter is picked from the header row
    (``delimiters`` names the candidates and the order they are consulted —
    a file is comma-first, clipboard text is tab-first) and the encoding
    ladder tries utf-8-with-BOM before the codepage Excel writes at home.

    Every cell is read as the text it is (``dtype=str``): left to its own
    inference, pandas types an all-digit column as int64 — or float64 the
    moment one cell under it is blank — and a leading zero is gone before
    any door sees the cell. '007' is a serial number, not a seven, and no
    post-processing can put the zero back; the doors map cells to text
    through :func:`cell_text`, which reads a text frame as-is. Keyword
    arguments pass through to pandas (``nrows`` keeps the header-only read
    cheap).
    """
    last_decode_error: UnicodeDecodeError | None = None
    for encoding in _CSV_ENCODINGS:
        # The probe lines ride one decoding rung with the header: the
        # delimiter reads the first rows, not the header alone, and a
        # later row this rung cannot name leaves the probe with whatever
        # decoded before it — pd.read_csv still owns the full-file refusal.
        parts = content.split(b'\n', _DELIMITER_PROBE_ROWS)
        probe_sources = parts[:-1] if len(parts) > _DELIMITER_PROBE_ROWS else parts
        try:
            header_line = probe_sources[0].decode(encoding)
        except UnicodeDecodeError as e:
            last_decode_error = e
            continue
        probe = [header_line]
        for raw_line in probe_sources[1:]:
            try:
                probe.append(raw_line.decode(encoding))
            except UnicodeDecodeError:
                break
        if not _header_is_text(header_line):
            # cp1250 names 251 of 256 bytes, so the ladder decodes almost
            # any blob and a binary file would reach the mapping step as
            # one garbage column. A header carrying control characters
            # means this rung is naming noise; the first rung's refusal
            # names the file.
            if last_decode_error is None:
                # No rung failed on decoding, so the refusal is this
                # guard's. Point it at the first control character rather
                # than fabricating position 0: whoever reads the refusal is
                # looking for the byte that broke the file, and 0 is a lie
                # that names an innocent one. (The offset counts characters
                # of the decoded header; for the single-byte rungs that is
                # the byte position too.)
                stop = next(
                    index
                    for index, ch in enumerate(header_line)
                    if ch not in ('\t', '\r') and category(ch) == 'Cc'
                )
                last_decode_error = UnicodeDecodeError(
                    encoding,
                    content,
                    stop,
                    stop + 1,
                    'the header row is not text',
                )
            continue
        try:
            frame = pd.read_csv(
                BytesIO(content),
                sep=_pick_delimiter(probe, delimiters),
                encoding=encoding,
                dtype=str,
                **kwargs,
            )
            frame.attrs[_TEXT_SHEET] = True
            return frame
        except UnicodeDecodeError as e:
            # The header decoded but a later row did not: the next rung
            # names the file.
            last_decode_error = e
    assert last_decode_error is not None
    raise last_decode_error


class RowError(ValueError):
    """A reason the reader can act on, worded for the import result screen."""


def read_sheet(content: bytes, filename: str, **kwargs: Any) -> pd.DataFrame:
    """The raw frame: every data row of the upload, every cell typed as the
    text it is — both branches read ``dtype=str``.

    The one place that knows how a spreadsheet turns into a frame — CSV
    through the tolerant reader (the extension names the format, upper- or
    lower-case), anything else through Excel. Left to its
    own inference pandas types a digit column int64 — or float64 the moment
    one cell under it is blank — and a leading zero is gone before any door
    sees the cell, on either branch: '007' is a serial number, not a seven,
    and no post-processing can put the zero back. A cell the workbook typed
    as a number arrives as its digits, one it typed as text stays the text
    it typed. Keyword arguments pass through to pandas on the Excel branch
    (``sheet_name`` names one sheet of a multi-sheet workbook). Callers
    that show a preview read this; callers that turn rows into records read
    :func:`read_rows`, which adds the blanks and the row cap on top.

    Cells the NA vocabulary catches ('NA', 'N/A', 'NULL') read as missing
    on both branches — pandas' answer, and the one the items and partners
    doors have always given. The equipment door reads them through the same shared reader, which cannot
    carry both answers, so a row whose only name is 'NA' is refused at the door as missing —
    loudly, at import time — rather than imported as the string.
    """
    try:
        if filename.lower().endswith('.csv'):
            return read_csv_sheet(content)
        return pd.read_excel(BytesIO(content), dtype=str, **kwargs)
    except (BadZipFile, pd.errors.ParserError, ValueError, OSError) as e:
        # BadZipFile is what a workbook truncated mid-download raises before
        # pandas says anything, and it subclasses none of the parse errors —
        # left out, it escapes the reader and answers an unimportable file
        # with an unhandled 500 instead of a refusal.
        logger.warning('Spreadsheet unreadable: %s', e)
        raise ServiceRejectionError('sheet_unreadable') from e


def refuse_beyond_row_cap(count: int) -> None:
    """Refuse a row count past the import cap, worded once for every door.

    Every import door — products, partners, order lines, documents, the
    clipboard paste — owes its refusals the same sentence, so the raise
    lives here and nowhere else.
    """
    if count > MAX_IMPORT_ROWS:
        raise ServiceRejectionError(
            'import_too_many_rows', count=count, limit=MAX_IMPORT_ROWS
        )


def read_rows(content: bytes, filename: str) -> pd.DataFrame:
    """Every data row of the upload, blanks read as None, within the row cap."""
    df = read_sheet(content, filename)
    df = df.where(pd.notnull(df), None)
    refuse_beyond_row_cap(len(df))
    return df


def cell_text(raw: Any) -> str | None:
    """A cell as the reader typed it, or None when it is blank.

    Both branches type the sheet as text — ``read_csv_sheet`` on the CSV
    side, ``dtype=str`` on the workbook side of :func:`read_sheet` — so a
    leading zero the sheet typed survives the read and a cell the workbook
    typed as a number arrives as its digits. The float branch is the belt
    for a frame that reached the caller without the reader: pandas left to
    its own inference types an all-digit column int64 — or float64 the
    moment one cell under it is blank — and a whole float goes back to its
    digits, so a barcode column with one blank survives.
    """
    if raw is None:
        return None
    if isinstance(raw, float):
        if isnan(raw):
            return None
        if raw.is_integer():
            return str(int(raw))
    text = str(raw).strip()
    return text or None


def row_text(row: pd.Series, col: str | None) -> str | None:
    """A mapped cell as the reader typed it, or None when absent or blank."""
    if not col or col not in row.index:
        return None
    return cell_text(row[col])


def row_get(row: pd.Series, mapping: dict[str, Any], key: str) -> Any:
    """Look up a mapped column value in a row, or None if not mapped/present."""
    col = mapping.get(key)
    if not col:
        return None
    return row.get(col)


def explain(exc: Exception, mapping: dict[str, Any]) -> str:
    """The reason a row was refused, for the reader — never a Python repr.

    Whatever the importer did not foresee is logged with its traceback and
    reported as just that; the repr of an exception is not a reason. What
    the importer *does* foresee is reported as itself: a row error, a
    validation, an application exception — and the quota gate's refusal,
    which a reader can act on and which the form and the scan already
    answer with this very sentence.
    """
    if isinstance(exc, RowError | ValueError) and not isinstance(exc, ValidationError):
        return str(exc)
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        field_name = str(first['loc'][0]) if first.get('loc') else ''
        column = mapping.get(field_name) or field_name
        return str(
            ServiceRejectionError(
                'import_column_reason',
                column=column,
                reason=translate_validation_error(dict(first)),
            )
        )
    if isinstance(exc, AppException):
        detail = exc.detail
        if isinstance(detail, dict) and detail.get('message'):
            return str(detail['message'])
        return str(detail)
    if isinstance(exc, QuotaExceededError):
        # An expected refusal, not a fault: the organization stands at its
        # limit. It reaches the reader as itself — the same sentence the
        # form and the scan give — and it never reaches the traceback
        # logger below, so a sheet of five hundred rows cannot bury five
        # hundred stacks of a refusal that was decided before the row ran.
        return str(exc)
    logger.exception('Import row failed')
    return str(ServiceRejectionError('import_row_failed'))


# ---------------------------------------------------------------------------
# Numbers and dates as a sheet's country writes them
# ---------------------------------------------------------------------------


class UnreadableCellError(ValueError):
    """A cell that is not the number or the date its column promises.

    The door that met it words the refusal; this carries only the cell.
    """


#: What may stand beside a price without being part of the number: ISO codes
#: ("PLN", "eur") and the short words a till writes ("zł", "Kč", "kr").
_CURRENCY_WORDS = frozenset(code.lower() for code in list_currencies()) | {
    'zł',
    'zl',
    'kč',
    'kc',
    'kr',
    'ft',
    'lei',
    'fr',
}

_LEADING_WORD = re.compile(r'^([^\W\d_]+)\.?\s*(.*)$', re.DOTALL)
_TRAILING_WORD = re.compile(r'^(.*?)\s*([^\W\d_]+)\.?$', re.DOTALL)

#: Digit groups a typographer separates with a space, a no-break space, a
#: narrow no-break space or an apostrophe ("1 289,00", "1'289.50").
_SPACE_GROUPS = re.compile(r"^\d{1,3}(?:[ \u00a0\u202f'\u2019]\d{3})+(?=[.,]\d*$|$)")

#: A float as Python and Excel write it when the cell holds a number
#: ("1e-05"): digits, a dot, an exponent — never a locale's separators.
_FLOAT_TEXT = re.compile(r'^[+-]?\d+(?:\.\d+)?[eE][+-]?\d+$')


#: The Brazilian real is written "R$": the R belongs to the symbol.
_REAL_SYMBOL = re.compile(r'(?<![^\W\d_])R\$')


def _strip_currency(text: str) -> str:
    """The text without a currency symbol, code or word at either end."""
    text = _REAL_SYMBOL.sub('', text)
    text = ''.join(ch for ch in text if category(ch) != 'Sc').strip()
    lead = _LEADING_WORD.match(text)
    if lead and lead.group(1).lower() in _CURRENCY_WORDS:
        text = lead.group(2).strip()
    tail = _TRAILING_WORD.match(text)
    if tail and tail.group(2).lower() in _CURRENCY_WORDS:
        text = tail.group(1).strip()
    return text


def parse_sheet_number(raw: Any, dot_thousands: bool | None = None) -> Decimal:
    """A number cell as a ``Decimal``, read the way the sheet's country writes it.

    Raises ``UnreadableCellError`` (a ``ValueError``) when the cell is not a number. Currency symbols
    and codes, spaces (no-break and narrow no-break included) and an
    apostrophe between digit groups are not part of the number. A value
    carrying both separators says which is the decimal mark — the last one
    ("1.234,50", "1,234.50"); the same separator repeated is a thousands
    separator ("1.234.567"); a lone comma is a decimal mark ("12,5"), except
    that exactly three digits after it read as a thousands group for a
    language that writes the decimal mark as a dot ("1,250" in English is
    1250).

    A lone dot before exactly three digits ("1.234") is the one cell no
    value settles: *dot_thousands* says what its column decided
    (:meth:`SheetColumns.number`). Without a decision it is the decimal mark
    a workbook's number cell writes ("2.125"), except that for a language
    that writes a decimal comma a group ending in 0 ("1.200") is thousands —
    a float's text never ends in 0 after the dot. Any other lone dot is a
    decimal mark.
    """
    text = cell_text(raw)
    if text is None:
        raise UnreadableCellError(raw)
    if _FLOAT_TEXT.match(text):
        return Decimal(text)
    sign, text = _signed_digits(text, raw)
    return Decimal(sign + _normalize_separators(text, dot_thousands))


def _signed_digits(text: str, raw: Any) -> tuple[str, str]:
    """A number cell's sign and its digits with separators, no symbol or space groups."""
    text = _strip_currency(text)
    sign = ''
    if text.startswith(('+', '-', '\u2212')):
        sign = '-' if text[0] in '-\u2212' else ''
        text = text[1:].lstrip()
    groups = _SPACE_GROUPS.match(text)
    if groups:
        head = re.sub(r"[ \u00a0\u202f'\u2019]", '', groups.group(0))
        text = head + text[groups.end() :]
    if not re.fullmatch(r'[\d.,]*\d[\d.,]*', text):
        raise UnreadableCellError(raw)
    return sign, text


def _lone_group(text: str, mark: str) -> tuple[str, str] | None:
    """The two parts of ``1.234`` / ``12,345`` — one mark before exactly three digits.

    None for any other shape: more than one mark, a fraction of another
    length, or a whole that cannot be a thousands group ("0.125", "1234.567").
    """
    if text.count(mark) != 1:
        return None
    whole, _, fraction = text.partition(mark)
    if len(fraction) == 3 and 1 <= len(whole) <= 3 and not whole.startswith('0'):
        return whole, fraction
    return None


def _normalize_separators(text: str, dot_thousands: bool | None) -> str:
    """Digits with at most one dot: the sheet's separators resolved."""
    has_dot, has_comma = '.' in text, ',' in text
    if has_dot and has_comma:
        decimal = '.' if text.rfind('.') > text.rfind(',') else ','
        thousands = ',' if decimal == '.' else '.'
        whole, _, fraction = text.rpartition(decimal)
        if decimal in whole or not _is_grouped(whole, thousands):
            raise UnreadableCellError(text)
        return whole.replace(thousands, '') + '.' + fraction
    if not has_dot and not has_comma:
        return text
    mark = '.' if has_dot else ','
    if text.count(mark) > 1:
        if not _is_grouped(text, mark):
            raise UnreadableCellError(text)
        return text.replace(mark, '')
    group = _lone_group(text, mark)
    if group and _is_thousands_group(mark, group[1], dot_thousands):
        return group[0] + group[1]
    whole, _, fraction = text.partition(mark)
    return f'{whole or "0"}.{fraction or "0"}'


def _is_thousands_group(mark: str, fraction: str, dot_thousands: bool | None) -> bool:
    """Whether one separator before exactly three digits is a thousands mark.

    A comma is for a language that writes its decimal mark as a dot ("1,250"
    in English). A dot follows *dot_thousands* when the column decided it;
    undecided, it is for a language that writes a decimal comma ("1.200 kg"
    in German) when the group ends in 0, the only ending a workbook's float
    text cannot have.
    """
    comma_decimal = writes_decimal_comma(get_current_lang())
    if mark == ',':
        return not comma_decimal
    if dot_thousands is not None:
        return dot_thousands
    return comma_decimal and fraction.endswith('0')


def _is_grouped(text: str, separator: str) -> bool:
    """Whether *text* is digit groups of three after a first of one to three."""
    return (
        re.fullmatch(rf'\d{{1,3}}(?:{re.escape(separator)}\d{{3}})*', text) is not None
    )


def _dot_evidence(raw: Any) -> bool | None:
    """What one value says about the dot of its column.

    True when the value writes its decimals with a comma ("12,5",
    "1.234,50"), or groups with repeated dots ("1.234.567"): the dot is a
    thousands mark. False when it writes a decimal dot ("2.5", "1289.00",
    "0.125", "1,234.50", "1e-05"). None for a value that says nothing about
    it, the lone group "1.234" included.
    """
    text = cell_text(raw)
    if text is None:
        return None
    if _FLOAT_TEXT.match(text):
        return False
    try:
        _, text = _signed_digits(text, raw)
    except UnreadableCellError:
        return None
    has_dot, has_comma = '.' in text, ',' in text
    if has_dot and has_comma:
        return text.rfind(',') > text.rfind('.')
    if has_comma:
        if text.count(',') > 1:
            return False if _is_grouped(text, ',') else None
        return None if _lone_group(text, ',') else True
    if not has_dot:
        return None
    if text.count('.') > 1:
        return True if _is_grouped(text, '.') else None
    return None if _lone_group(text, '.') else False


_TIME_TAIL = r'(?:[T ]\d{1,2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?'
_YEAR_FIRST = re.compile(rf'^(\d{{4}})[-./ ](\d{{1,2}})[-./ ](\d{{1,2}}){_TIME_TAIL}$')
_YEAR_LAST = re.compile(
    rf'^(\d{{1,2}})[-./ ](\d{{1,2}})[-./ ](\d{{4}}|\d{{2}}){_TIME_TAIL}$'
)


def looks_like_numeric_date(text: str) -> bool:
    """Whether *text* is written as three numeric parts with a year, e.g. ``05.11.2026``."""
    return bool(_YEAR_FIRST.match(text) or _YEAR_LAST.match(text))


def _two_digit_year(year: str) -> int:
    return int(year) if len(year) == 4 else 2000 + int(year)


def _day_month_pair(text: str) -> tuple[int, int] | None:
    """The first two parts of a ``a.b.year`` date, or None for any other shape."""
    match = _YEAR_LAST.match(text)
    return (int(match.group(1)), int(match.group(2))) if match else None


def column_day_first(values: Iterable[Any]) -> bool:
    """Whether a column of dates writes the day first, decided from all of it.

    A value whose first part is above 12 settles day-first, one whose
    second part is above 12 settles month-first; the order most such values
    settle is the column's. A column of values that are all ambiguous
    follows the language of the person importing: month-first for English,
    day-first for every other maintained language.
    """
    evidence: Counter[bool] = Counter()
    for raw in values:
        text = cell_text(raw)
        pair = _day_month_pair(text) if text else None
        if pair is None:
            continue
        if pair[0] > 12 >= pair[1]:
            evidence[True] += 1
        elif pair[1] > 12 >= pair[0]:
            evidence[False] += 1
    if evidence:
        return evidence[True] >= evidence[False]
    return get_current_lang() != 'en'


class SheetColumns:
    """What each column of one sheet decides, from the whole of it.

    Built from the whole frame, so a row is read by what its column says:
    the one row of a file that reads "05.11.2026" follows the "28.02.2027"
    below it, and a "1.234" follows the "2,5" or the "1.289,00" beside it.
    Each column is decided once, on first use.
    """

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df
        self._day_first: dict[str, bool] = {}
        self._dot_thousands: dict[str, bool | None] = {}

    def _known(self, column: str | None) -> bool:
        return bool(column) and column in self._df.columns

    def day_first(self, column: str | None) -> bool:
        if not self._known(column):
            return column_day_first(())
        assert column is not None
        if column not in self._day_first:
            self._day_first[column] = column_day_first(self._df[column])
        return self._day_first[column]

    def date(self, raw: Any, column: str | None) -> date:
        """The cell as a date, or ``UnreadableCellError`` (a ``ValueError``) when it is not one."""
        return parse_sheet_date(raw, self.day_first(column))

    def dot_thousands(self, column: str | None) -> bool | None:
        """Whether the column's lone dot before three digits is a thousands mark.

        A value with a decimal comma, or a dot repeated, settles it as
        thousands; one with a decimal dot ("2.5", "1289.00") settles it as
        the decimal mark; the side with more values wins. A column with no
        such value is decided by the file: delimited text is typed as it is
        read, so for a language that writes a decimal comma the dot is
        thousands there; a workbook's number cell reads as float text, which
        no value of this column can settle, and is left to
        :func:`parse_sheet_number`.
        """
        if not self._known(column):
            return None
        assert column is not None
        if column not in self._dot_thousands:
            votes = Counter(_dot_evidence(raw) for raw in self._df[column])
            if votes[True] != votes[False]:
                decided: bool | None = votes[True] > votes[False]
            elif self._df.attrs.get(_TEXT_SHEET) and writes_decimal_comma(
                get_current_lang()
            ):
                decided = True
            else:
                decided = None
            self._dot_thousands[column] = decided
        return self._dot_thousands[column]

    def number(self, raw: Any, column: str | None) -> Decimal:
        """The cell as a number, or ``UnreadableCellError`` (a ``ValueError``) when it is not one."""
        return parse_sheet_number(raw, self.dot_thousands(column))


def parse_sheet_date(raw: Any, day_first: bool) -> date:
    """A date cell as a ``date``; ``UnreadableCellError`` (a ``ValueError``) when it is not one.

    A cell the workbook typed as a date arrives as a date or a datetime and
    is taken as it is. A year-first text ("2026-11-05") is read as written.
    A text of three numeric parts with the year last is read day-first or
    month-first by *day_first* unless one of its own parts settles it (a
    day above 12). Anything else ("5 Nov 2026") goes to pandas, which reads
    English month names; "end of March" is refused.
    """
    if isinstance(raw, pd.Timestamp):
        if pd.isna(raw):
            raise UnreadableCellError(raw)
        return date(raw.year, raw.month, raw.day)
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = cell_text(raw)
    if text is None:
        raise UnreadableCellError(raw)
    match = _YEAR_FIRST.match(text)
    if match:
        year, month, day = (int(part) for part in match.groups()[:3])
        return date(year, month, day)
    match = _YEAR_LAST.match(text)
    if match:
        first, second = int(match.group(1)), int(match.group(2))
        year = _two_digit_year(match.group(3))
        if first > 12:
            day, month = first, second
        elif second > 12:
            month, day = first, second
        else:
            day, month = (first, second) if day_first else (second, first)
        return date(year, month, day)
    parsed = pd.to_datetime(text)
    if pd.isna(parsed):
        raise UnreadableCellError(text)
    return date(parsed.year, parsed.month, parsed.day)
