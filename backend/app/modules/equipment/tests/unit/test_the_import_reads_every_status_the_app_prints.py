"""The import reads back every status label the app prints, in every language.

The import's status words are a copy of the frontend ``equipment`` catalogs'
``status.*`` labels: a sheet exported from the list carries the label, not
the stored code. A copy drifts silently — the Portuguese labels were never
in it, so a Portuguese sheet re-imported failed every row. This reads each
catalog shipped in the tree, so a label changed in a catalog and not in the
import, or a language added without its words, fails here first.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest

from app.modules.equipment.import_service import (
    _STATUS_WORDS,
    _normalize_header,
    _sheet_status,
)

pytestmark = pytest.mark.unit

_CODES = {
    'available': 'AVAILABLE',
    'deployed': 'DEPLOYED',
    'maintenance': 'MAINTENANCE',
    'retired': 'RETIRED',
}


def _catalogs() -> list[Path]:
    root = Path(os.environ.get('INVENTARI_REPO_ROOT', Path(__file__).parents[6]))
    found = sorted(
        (root / 'frontend' / 'src' / 'modules' / 'equipment' / 'i18n').glob('*.json')
    )
    assert found, f'no equipment catalogs under {root}'
    return found


@pytest.mark.parametrize('catalog', _catalogs(), ids=lambda p: p.stem)
def test_every_printed_status_imports_as_its_code(catalog: Path) -> None:
    labels = json.loads(catalog.read_text(encoding='utf-8'))['status']

    read_back = {
        key: _sheet_status(pd.Series({'status': labels[key]}), 'status')
        for key in _CODES
    }

    assert read_back == _CODES, (
        f'{catalog.name}: a status label the app prints is not one the import '
        'reads — add it to _STATUS_WORDS in import_service.py'
    )


def test_no_word_means_two_statuses() -> None:
    seen: dict[str, str] = {}
    for code, words in _STATUS_WORDS.items():
        for word in [code, *words]:
            key = _normalize_header(word)
            assert seen.setdefault(key, code) == code, (word, seen[key], code)
