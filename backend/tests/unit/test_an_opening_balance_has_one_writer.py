"""An opening balance is written by one rule, whichever door adopts the card.

A record that predates its card joins the register with an opening: a quant
on its shelf, a movement marked ``opening_balance`` and a cost layer. The
rule was written twice — once in the Core for its edit and quantity paths,
once in the documents executor for its receipts, dispatches, transfers and
scraps — and the two copies agreed only because each docstring pointed at the
other. A change to what an opening writes had to find both, and a third door
would have written a third. The documents executor now asks the Core through
``core_api.items.post_opening_balance_async``; the movement is spelled in one
place, and this keeps it there.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / 'app'

_WRITES_AN_OPENING = re.compile(
    r'reference_type\s*=\s*'
    r"(StockMoveReferenceType\.OPENING_BALANCE|['\"]opening_balance['\"])"
)


def test_the_opening_movement_has_one_writer() -> None:
    writers = [
        path.relative_to(BACKEND_ROOT).as_posix()
        for path in sorted(APP_ROOT.rglob('*.py'))
        if 'tests' not in path.parts and _WRITES_AN_OPENING.search(_read(path))
    ]
    assert writers == ['app/services/items/_stock_quant.py'], (
        'An opening balance is posted by post_opening_balance_async '
        '(core_api.items.post_opening_balance_async from a module) — '
        f'written again in: {writers}'
    )


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        return ''
