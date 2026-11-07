"""Turn a table into a downloadable sheet, once.

Two exports now write XLSX — the item list and the movement ledger — and
both need the same three things: the openpyxl writer, the formula-injection
defusing that must never be forgotten (see :mod:`app.core.export_hygiene`),
and a filename with a date in it. Copying that into the second export is how
the second export ends up without the defusing.
"""

from __future__ import annotations

import io
import math
import tempfile
from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime
from typing import IO, Any

import pandas as pd
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell

from app.core.export_hygiene import defuse_worksheet, is_formula_like

XLSX_MEDIA_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

#: Rows a sheet takes before the next one starts. A sheet holds at most
#: 1 048 576 rows (``This sheet is too large!``), the header is one of them,
#: and the margin keeps a reader's own header or total row from overflowing it.
MAX_ROWS_PER_SHEET = 1_000_000

#: How much of the finished workbook one read of the response takes.
_STREAM_CHUNK = 64 * 1024


def _as_written(number: float) -> str:
    """*number* as the text a cell stores: what the screen showed for it.

    openpyxl writes a float with sixteen significant digits, and sixteen
    spell the double nearest to 95.35 as 95.34999999999999 — the text a CSV
    conversion, a script or the file itself then shows beside a screen and a
    printout that said 95.35. Fifteen is what a spreadsheet keeps, and
    fifteen read the same double back for every figure typed with up to
    fifteen digits; a double they cannot carry is written in full instead.
    """
    text = f'{number:.15g}'
    return text if float(text) == number else repr(float(number))


def _write_numbers_as_written(worksheet: Any) -> None:
    """Store every finite float of *worksheet* as :func:`_as_written` spells it.

    The cell stays a number — the text is what the file stores for it, and
    a spreadsheet reads the same double back.
    """
    for row in worksheet.iter_rows():
        for cell in row:
            if isinstance(cell.value, float) and math.isfinite(cell.value):
                cell.value = _as_written(cell.value)
                cell.data_type = 'n'


def to_xlsx_response(
    df: pd.DataFrame,
    *,
    sheet_name: str,
    filename_stem: str,
    readme: pd.DataFrame | None = None,
    readme_sheet: str = 'Read me',
) -> StreamingResponse:
    """One data sheet, defused, as an attachment named after today.

    ``readme`` is an optional second sheet for what the data sheet cannot
    say about itself — which of its columns come back on import, say.
    """
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
        # Every text column here came from a user at some point; openpyxl
        # would type a leading '=' as a formula.
        defuse_worksheet(writer.sheets[sheet_name])
        _write_numbers_as_written(writer.sheets[sheet_name])
        if readme is not None:
            readme.to_excel(writer, index=False, sheet_name=readme_sheet)
            defuse_worksheet(writer.sheets[readme_sheet])

    output.seek(0)
    filename = f'{filename_stem}_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
    return StreamingResponse(
        output,
        media_type=XLSX_MEDIA_TYPE,
        headers={'Content-Disposition': f'attachment; filename={filename}'},
    )


def _defused(sheet: Any, value: Any) -> Any:
    """The cell for *value*, typed as text when a spreadsheet would run it.

    A float is written as :func:`_as_written` spells it, as the table
    export writes it.
    """
    if isinstance(value, float) and math.isfinite(value):
        number = WriteOnlyCell(sheet, value=_as_written(value))
        number.data_type = 'n'
        return number
    if not is_formula_like(value):
        return value
    cell = WriteOnlyCell(sheet, value=value)
    cell.data_type = 's'
    cell.quotePrefix = True
    return cell


def _stream_and_close(file: IO[bytes]) -> Iterator[bytes]:
    try:
        while chunk := file.read(_STREAM_CHUNK):
            yield chunk
    finally:
        file.close()


def rows_to_xlsx_response(
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    *,
    sheet_name: str,
    filename_stem: str,
    readme: pd.DataFrame | None = None,
    readme_sheet: str = 'Read me',
) -> StreamingResponse:
    """A sheet written row by row, so its size does not decide the memory taken.

    :func:`to_xlsx_response` takes a table that is whole in memory and builds
    the workbook in memory too: at 100 000 products the worker grew until its
    container killed it. Here each row goes to a temporary file as it comes
    from *rows* and the response reads the finished workbook back from that
    file, so only one row at a time is held. A sheet that reaches
    :data:`MAX_ROWS_PER_SHEET` continues on the next, named
    ``<sheet_name> 2``, ``<sheet_name> 3`` and so on, each with the header.

    Cells are defused the way :func:`to_xlsx_response` defuses them.
    """
    workbook = Workbook(write_only=True)
    sheets = 0

    def _start_sheet() -> Any:
        nonlocal sheets
        sheets += 1
        started = workbook.create_sheet(
            sheet_name if sheets == 1 else f'{sheet_name} {sheets}'
        )
        started.append([_defused(started, column) for column in columns])
        return started

    sheet = None
    written = 0
    for row in rows:
        if sheet is None or written >= MAX_ROWS_PER_SHEET:
            sheet = _start_sheet()
            written = 0
        sheet.append([_defused(sheet, value) for value in row])
        written += 1
    if sheet is None:  # an empty export still has its header
        _start_sheet()

    if readme is not None:
        notes = workbook.create_sheet(readme_sheet)
        notes.append([_defused(notes, column) for column in readme.columns])
        for note_row in readme.itertuples(index=False):
            notes.append([_defused(notes, value) for value in note_row])

    output = tempfile.TemporaryFile()
    workbook.save(output)
    output.seek(0)
    filename = f'{filename_stem}_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
    return StreamingResponse(
        _stream_and_close(output),
        media_type=XLSX_MEDIA_TYPE,
        headers={'Content-Disposition': f'attachment; filename={filename}'},
    )
