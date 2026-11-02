"""The refusal codes on docs/api/ERRORS.md are the ones the backend raises.

Same pattern as ``test_event_catalog_drift.py``: the generator prints the page
with its table refreshed from the catalogue, and the committed page has to
equal it. A refusal added without regenerating the page, or a key renamed, is
a code a client can branch on that the page does not name.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = Path(os.environ.get('INVENTARI_REPO_ROOT') or _BACKEND_DIR.parent)
_GENERATOR_SCRIPT = _BACKEND_DIR / 'scripts' / 'generate_error_codes.py'
_PAGE = _PROJECT_ROOT / 'docs' / 'api' / 'ERRORS.md'


@pytest.mark.integration
class TestErrorCodesPageDrift:
    def test_the_page_matches_the_generator(self) -> None:
        assert _PAGE.exists(), f'{_PAGE} is not reachable from here'

        result = subprocess.run(
            [sys.executable, str(_GENERATOR_SCRIPT)],
            capture_output=True,
            text=True,
            cwd=str(_BACKEND_DIR),
        )

        assert result.returncode == 0, f'Generator failed:\n{result.stderr}'
        assert result.stdout == _PAGE.read_text(encoding='utf-8'), (
            'docs/api/ERRORS.md is out of sync with the catalogue — regenerate: '
            '`docker compose exec -T backend python scripts/generate_error_codes.py '
            '> /tmp/ERRORS.md && mv /tmp/ERRORS.md docs/api/ERRORS.md`'
        )

    def test_a_refusal_the_backend_raises_is_on_the_page(self) -> None:
        page = _PAGE.read_text(encoding='utf-8')

        assert '| `ITEM_ALREADY_DELETED` |' in page
