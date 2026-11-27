"""The rows an import refused, as a file the reader corrects and uploads.

The file carries the upload's own columns and one more with the reason, in
the upload's format: a workbook comes back as a workbook, delimited text
with the delimiter it had. A second attempt therefore maps the same way, and
uploading the file alone adds what the first attempt did not.
"""

from __future__ import annotations

import base64
import csv
import io
from pathlib import PurePath
from typing import Any

import pandas as pd

from app.core.export_hygiene import defuse
from app.core.import_sheet import CSV_DELIMITER_ATTR, SheetColumns
from app.core.xlsx_export import write_rows_xlsx
from app.i18n.service import get_current_lang, get_error_message
from app.schemas._common import RefusedRowsFile

__all__ = ['RefusedRowsFile', 'refused_rows_file']

_SUFFIX = '-refused'


def refused_rows_file(
    df: pd.DataFrame,
    errors: list[dict[str, Any]],
    filename: str,
    sheet: SheetColumns | None = None,
) -> dict[str, str] | None:
    """The refused rows of *df* as a :class:`RefusedRowsFile`, or ``None``.

    *errors* name each row by its number among the data rows, from 1, as the
    result screen lists them. An import that read dates or numbers by what
    their whole column says passes the *sheet* it read them with. A
    dictionary, so that a background job can keep it with the rest of its
    result.
    """
    reasons: dict[int, list[str]] = {}
    for error in errors:
        reasons.setdefault(error['row'] - 1, []).append(error['error'])
    if not reasons:
        return None
    reason_column = get_error_message('import_reason_column', get_current_lang())
    # A file that already went round once has the column: it is written anew.
    columns = [column for column in df.columns if str(column) != reason_column]
    header = [str(column) for column in columns] + [reason_column]
    rows = [
        [_cell(df, sheet, index, column) for column in columns]
        + ['; '.join(reasons[index])]
        for index in sorted(reasons)
    ]

    name = PurePath(filename or 'import.csv')
    stem = name.stem.removesuffix(_SUFFIX) + _SUFFIX
    if name.suffix.lower() == '.csv':
        extension = 'csv'
        content = _delimited(header, rows, df.attrs.get(CSV_DELIMITER_ATTR, ','))
    else:
        extension = 'xlsx'
        with write_rows_xlsx(header, rows, sheet_name='Refused') as workbook:
            content = workbook.read()
    return RefusedRowsFile(
        filename=f'{stem}.{extension}',
        content_base64=base64.b64encode(content).decode('ascii'),
    ).model_dump()


def _cell(
    df: pd.DataFrame, sheet: SheetColumns | None, index: int, column: str
) -> str | None:
    restated = sheet.restate(index, column) if sheet else None
    if restated is not None:
        return restated
    value = df[column].iloc[index]
    return None if pd.isna(value) else str(value)


def _delimited(header: list[str], rows: list[list[Any]], delimiter: str) -> bytes:
    """*rows* as delimited text a spreadsheet opens as UTF-8.

    Every cell is user text, the header included, so each is defused; the
    import strips the tab the defusing adds.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter)
    writer.writerows([defuse(value) for value in row] for row in [header, *rows])
    return buffer.getvalue().encode('utf-8-sig')
