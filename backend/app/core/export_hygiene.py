"""Keep user-supplied text from becoming a formula in an exported sheet.

Excel, LibreOffice and Google Sheets treat a cell whose text starts with ``=``,
``+``, ``-`` or ``@`` as a formula. An item named ``=cmd|'/c calc'!A1`` is
harmless in the app and hostile the moment somebody opens the export — the
attacker writes the payload as ordinary data and the victim's spreadsheet runs
it. Neutralising belongs in the export, not in the input: the value is valid
data everywhere else.

CSV has no notion of a literal cell, so a risky value is prefixed with a tab —
the spreadsheet then reads it as text and shows it unchanged. XLSX does have
one, so :func:`defuse_worksheet` marks the cell as a string instead, leaving
the value byte-identical.
"""

from typing import Any

_RISKY_PREFIXES = ('=', '+', '-', '@')


def _looks_numeric(text: str) -> bool:
    """True for plain numbers — ``-12.5`` is data, not an injection attempt."""
    try:
        float(text.replace(',', '.'))
    except ValueError:
        return False
    return True


def is_formula_like(value: Any) -> bool:
    """True when a spreadsheet would read *value* as a formula."""
    if not isinstance(value, str):
        return False
    stripped = value.lstrip()
    if not stripped.startswith(_RISKY_PREFIXES):
        return False
    return not _looks_numeric(stripped)


def defuse(value: Any) -> Any:
    """Return *value* safe to write into a CSV cell."""
    return f'\t{value}' if is_formula_like(value) else value


def defuse_worksheet(worksheet: Any) -> None:
    """Force every formula-like cell of an openpyxl worksheet to be text.

    Writing through pandas hands openpyxl bare strings, and openpyxl types a
    string starting with ``=`` as a formula. Retyping the cell keeps the text
    exactly as the user entered it while stopping the spreadsheet from
    evaluating it.
    """
    for row in worksheet.iter_rows():
        for cell in row:
            if is_formula_like(cell.value):
                cell.data_type = 's'
                cell.quotePrefix = True
