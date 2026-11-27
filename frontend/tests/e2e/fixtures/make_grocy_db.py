"""Writes ``grocy.db``, the Grocy file the browser spec of the move uploads.

The tables are Grocy's own (``backend/tests/fixtures/grocy_schema.sql``) and
the rows are added by the builder the backend tests use. Run after changing
either, from the repository root, and commit the result::

    python3 frontend/tests/e2e/fixtures/make_grocy_db.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'backend' / 'tests' / 'integration'))

from _grocy import GrocyDb  # noqa: E402


def household() -> GrocyDb:
    g = GrocyDb()
    pantry = g.location('E2E-Grocy pantry')
    freezer = g.location('E2E-Grocy freezer', is_freezer=True)
    g.location('E2E-Grocy old cellar', active=False)
    sweets = g.group('E2E-Grocy sweets')
    g.group('E2E-Grocy old snacks', active=False)
    shop = g.store('E2E-Grocy corner shop')
    g.store('E2E-Grocy closed market', active=False)
    piece = g.unit('Piece', 'Pieces')
    gram = g.unit('Gram', 'Grams')
    cookies = g.product(
        'E2E-Grocy cookies', location=pantry, unit=piece, group=sweets, store=shop
    )
    g.barcode(cookies, 'GROCY-A')
    g.barcode(cookies, 'GROCY-B')
    g.stock(cookies, 3, purchased='2026-11-02', price=1.25, location=pantry)
    g.stock(cookies, 2, location=freezer)
    flour = g.product('E2E-Grocy flour', location=pantry, unit=gram)
    g.stock(flour, 750, location=pantry)
    # No stock: a product of the catalogue only.
    g.product('E2E-Grocy saffron', location=pantry, unit=gram)
    g.product('E2E-Grocy retired jam', location=pantry, unit=piece, active=False)
    g.recipe('Cheesecake')
    g.chore('Vacuum')
    return g


if __name__ == '__main__':
    Path(__file__).with_name('grocy.db').write_bytes(household().content())
