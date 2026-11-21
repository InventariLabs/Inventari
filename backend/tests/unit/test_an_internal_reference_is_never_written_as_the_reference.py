"""A reference a reader sees is a number or a name, never ``kind:<uuid>``.

Passes this comes from (the 2026-11 QA round): the document list and the
stock register printed ``picking:<uuid>`` and ``stock_take:<uuid>`` under
Reference — the writer's own handle on the record that caused the document,
shown to the person as if it were a document number.

The rule. A keyword argument named ``reference`` or ``external_reference`` in
any non-test module of ``app/`` may not be an f-string of the shape
``'<kind>:' + {value}``. A reference to the cause belongs in a typed column
(``reference_type`` / ``reference_id``) that the screen turns into a link and
a word; the free-text Reference carries what a person would write there.

``_OPEN`` names the writers that still do it. The goal is an empty set; a new
writer fails here.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / 'app'

_FIELDS = frozenset({'reference', 'external_reference'})

#: Writers still putting ``kind:<id>`` where a reader reads the Reference.
_OPEN = frozenset(
    {
        'app/modules/mcp_server/tools/_writes.py::reference=f"mcp:{…}"',
        'app/modules/recipes/_picking_document.py::external_reference=f"picking:{…}"',
        'app/modules/stock_takes/stock_take_service.py::reference=f"stock_take:{…}"',
    }
)


def is_kind_colon_value(node: ast.expr) -> str | None:
    """The ``kind`` of an f-string written ``'<kind>:' + {value}``, else None."""
    if not isinstance(node, ast.JoinedStr) or len(node.values) < 2:
        return None
    head, second = node.values[0], node.values[1]
    if not (isinstance(head, ast.Constant) and isinstance(head.value, str)):
        return None
    text = head.value
    if not (text.endswith(':') and text[:-1].replace('_', '').isalpha()):
        return None
    return text[:-1] if isinstance(second, ast.FormattedValue) else None


def references_in(rel: str, tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            kind = keyword.arg in _FIELDS and is_kind_colon_value(keyword.value)
            if kind:
                found.add(f'{rel}::{keyword.arg}=f"{kind}:{{…}}"')
    return found


def scan(app_root: Path = APP_ROOT) -> set[str]:
    found: set[str] = set()
    for path in sorted(app_root.rglob('*.py')):
        parts = path.relative_to(app_root).parts
        if 'tests' in parts or path.name.startswith('test_'):
            continue
        rel = 'app/' + '/'.join(parts)
        found |= references_in(rel, ast.parse(path.read_text(encoding='utf-8')))
    return found


def test_no_new_writer_puts_a_kind_and_an_id_where_the_reference_goes() -> None:
    assert scan() - _OPEN == set()


def test_the_open_list_names_only_writers_that_still_do_it() -> None:
    assert _OPEN - scan() == set(), 'fixed — remove from _OPEN'


def test_a_planted_writer_is_found() -> None:
    planted = ast.parse("make(external_reference=f'receipt:{doc.id}', note='x')")

    assert references_in('app/planted.py', planted) == {
        'app/planted.py::external_reference=f"receipt:{…}"'
    }


def test_a_document_number_or_a_free_text_reference_passes() -> None:
    fine = ast.parse(
        "make(reference=f'{prefix}-{number}', external_reference=po_number,"
        " note=f'picking:{x}')"
    )

    assert references_in('app/planted.py', fine) == set()
