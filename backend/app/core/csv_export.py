"""One CSV writer for every export, with the formula guard built in.

A CSV cell has no notion of a literal, so user text that starts with ``=``,
``+``, ``-`` or ``@`` has to be defused on its way out
(:mod:`app.core.export_hygiene`). Exports that each wrote their own
``csv.writer`` loop had to remember that; this is the one place that does.
"""

import csv
import io
from collections.abc import Iterable, Sequence
from typing import Any

from app.core.export_hygiene import defuse


def rows_to_csv(header: Sequence[str], rows: Iterable[Iterable[Any]]) -> str:
    """The *header* and *rows* as CSV text, every data cell defused.

    The header is the application's own wording and is written as given.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in rows:
        writer.writerow([defuse(value) for value in row])
    return buf.getvalue()
