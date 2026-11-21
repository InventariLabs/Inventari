"""German names a production run, a BOM and the module once each in its refusals.

A run is a ``Produktionslauf`` and a BOM a ``Formel``; the older
``Produktionsauftrag`` and ``Stückliste`` words belong to no screen, so a
refusal that used them read as another product's sentence.
"""

import re

from app.i18n._errors_de import ERRORS_DE

_OLD_WORDS = re.compile(r'Produktionsauftr|Stückliste')


def test_the_german_refusals_use_one_word_for_a_run_and_a_bom():
    stale = {
        code: text
        for code, text in ERRORS_DE.items()
        if _OLD_WORDS.search(text if isinstance(text, str) else str(text))
    }
    assert stale == {}


def test_a_refusal_about_a_run_says_run():
    assert 'Produktionslauf' in ERRORS_DE['production_start_not_draft']
    assert 'Formel' in ERRORS_DE['bom_depth_exceeded']
