"""A printed discrepancy is a word the reader can act on, never the stored code."""

from __future__ import annotations

import pytest

from app.modules.warehouse._pdf_labels import _get_discrepancy_map
from app.modules.warehouse.models.document import DocumentDiscrepancyCode


@pytest.mark.parametrize('lang', ['en', 'pl', 'de', 'fr', 'es'])
def test_every_discrepancy_code_has_a_label_in_every_language(lang: str) -> None:
    labels = _get_discrepancy_map(lang)
    for code in DocumentDiscrepancyCode:
        assert labels.get(code.value), f'{code.value} prints raw in {lang}'
        assert labels[code.value] != code.value
