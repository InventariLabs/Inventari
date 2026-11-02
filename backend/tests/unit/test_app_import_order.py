"""Cold-import smoke test: ``app.main`` must import in production order.

Regression guard: module-level SQLAlchemy Load options
(``undefer``/``selectinload``/…) force configuration of ALL mappers at
import time — before module models (e.g. ``StockTakeItem``) register —
which crashed uvicorn startup with ``InvalidRequestError: failed to locate
a name``. The pytest suite never sees this because conftest preloads every
model, so run the import in a fresh interpreter with production import
order instead.
"""

from __future__ import annotations

import subprocess
import sys


def test_app_main_imports_cold() -> None:
    result = subprocess.run(
        [sys.executable, '-c', 'import app.main'],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f'cold import of app.main failed (exit {result.returncode}):\n'
        f'{result.stderr[-3000:]}'
    )
