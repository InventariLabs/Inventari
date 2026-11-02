"""A module that ships only ``en.json`` answers in English under every language.

The module guides say English is the one required catalog. The runtime has to
back that sentence: a missing language file and a key missing from an existing
language file both fall back to the module's English catalog, not to the bare
key.
"""

import pytest

from app.i18n import SUPPORTED_LANGUAGES
from app.i18n.service import (
    _MODULE_TRANSLATIONS,
    get_module_error_message,
    load_module_translations,
)

MODULE = 'english_only_probe'


@pytest.fixture
def catalogs(tmp_path):
    def _load(files: dict[str, str]):
        for lang, body in files.items():
            (tmp_path / f'{lang}.json').write_text(body, encoding='utf-8')
        load_module_translations(MODULE, tmp_path)

    yield _load
    _MODULE_TRANSLATIONS.pop(MODULE, None)


@pytest.mark.unit
def test_an_english_only_module_answers_in_english_under_every_language(catalogs):
    catalogs({'en': '{"gone": "It is gone"}'})

    for lang in SUPPORTED_LANGUAGES:
        assert get_module_error_message(MODULE, 'gone', lang) == 'It is gone'


@pytest.mark.unit
def test_a_key_missing_from_a_shipped_language_shows_in_english(catalogs):
    catalogs(
        {
            'en': '{"gone": "It is gone", "late": "Too late"}',
            'pl': '{"gone": "Zniknęło"}',
        }
    )

    assert get_module_error_message(MODULE, 'gone', 'pl') == 'Zniknęło'
    assert get_module_error_message(MODULE, 'late', 'pl') == 'Too late'
