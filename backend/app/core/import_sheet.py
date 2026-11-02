"""Reading a spreadsheet for an import — the part every entity shares.

Products and partners arrive the same way: a header row, a column mapping
chosen by the reader, one row per record, and a report that names the row
and the reason for each refusal. What differs per entity is what a row
becomes; what is here is how a row is read and how a refusal is worded.
"""

from io import BytesIO
from math import isnan
from typing import Any
from unicodedata import category
from zipfile import BadZipFile

import pandas as pd
from pydantic import ValidationError

from app.core.exceptions import AppException, QuotaExceededError, ServiceRejectionError
from app.core.logging import get_logger
from app.core.upload_validation import MAX_IMPORT_ROWS
from app.i18n._validation import translate_validation_error

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
#: column count instead used to let the semicolons inside a quoted header
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
            # any blob and a binary file used to reach the mapping step as
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
            return pd.read_csv(
                BytesIO(content),
                sep=_pick_delimiter(probe, delimiters),
                encoding=encoding,
                dtype=str,
                **kwargs,
            )
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
    doors have always given. The equipment door's private reader used to
    keep them as literal text; one shared reader cannot carry both answers,
    so a row whose only name is 'NA' is refused at the door as missing —
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
