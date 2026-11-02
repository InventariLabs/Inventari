"""A community language ships below full coverage and costs no change a translation.

The backend declares which languages are community in ``app.i18n._types``.
A maintained language holds every key of ``ErrorMessages``; a community one
holds what it has so far and answers the rest in English, key by key, the way
the interface does.
"""

import json
import re
from pathlib import Path

import pytest

from app.cli.module_validator import REQUIRED_LANGUAGES, validate_i18n
from app.i18n import (
    COMMUNITY_ERRORS,
    ERRORS,
    MAINTAINED_LANGUAGES,
    SUPPORTED_LANGUAGES,
)
from app.i18n._types import COMMUNITY_LANGUAGES, ErrorMessages
from app.i18n.service import get_error_message, load_module_translations
from app.i18n.service import get_module_error_message as module_message

_PLACEHOLDER = re.compile(r'\{[A-Za-z_][A-Za-z0-9_]*\}')


def test_the_two_classes_split_the_supported_languages() -> None:
    assert set(MAINTAINED_LANGUAGES) | set(COMMUNITY_LANGUAGES) == set(
        SUPPORTED_LANGUAGES
    )
    assert not set(MAINTAINED_LANGUAGES) & set(COMMUNITY_LANGUAGES)
    assert 'en' in MAINTAINED_LANGUAGES


def test_a_maintained_language_holds_every_key() -> None:
    required = set(ErrorMessages.__required_keys__)

    for language in MAINTAINED_LANGUAGES:
        assert required <= set(ERRORS[language]), language


def test_a_community_catalog_is_declared_for_each_community_language() -> None:
    assert set(COMMUNITY_ERRORS) == set(COMMUNITY_LANGUAGES)
    for language in COMMUNITY_LANGUAGES:
        assert language not in ERRORS


def test_a_community_catalog_holds_no_key_the_english_catalog_lacks() -> None:
    """A key the English catalogue does not know is a typo, not a translation."""
    for language, catalog in COMMUNITY_ERRORS.items():
        assert set(catalog) <= set(ERRORS['en']), language


def test_a_community_message_keeps_the_placeholders_of_the_english_one() -> None:
    for language, catalog in COMMUNITY_ERRORS.items():
        for key, message in catalog.items():
            english = ERRORS['en'][key]
            assert sorted(_PLACEHOLDER.findall(message)) == sorted(
                _PLACEHOLDER.findall(str(english))
            ), (language, key)


@pytest.mark.parametrize('language', COMMUNITY_LANGUAGES)
def test_a_missing_key_answers_in_english(
    language: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = 'item_not_found'
    catalog = dict(COMMUNITY_ERRORS[language])
    assert key in catalog, 'the community catalog is expected to hold this key'
    translated = get_error_message(key, language)  # type: ignore[arg-type]
    assert translated == catalog[key]
    assert translated != ERRORS['en'][key]

    del catalog[key]
    monkeypatch.setitem(COMMUNITY_ERRORS, language, catalog)  # type: ignore[arg-type]

    assert get_error_message(key, language) == ERRORS['en'][key]  # type: ignore[arg-type]


def test_a_key_added_to_the_maintained_languages_alone_is_served_in_english(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The change that adds a string brings the maintained languages only."""
    for language in MAINTAINED_LANGUAGES:
        monkeypatch.setitem(ERRORS[language], 'a_brand_new_refusal', f'new {language}')  # type: ignore[literal-required]

    for language in COMMUNITY_LANGUAGES:
        assert get_error_message('a_brand_new_refusal', language) == 'new en'


def test_a_community_language_answers_interpolation_in_its_own_words() -> None:
    message = get_error_message(
        'item_quantity_above_ceiling',
        'pt',
        quantity='9',
        ceiling='5',
    )

    assert '9' in message and '5' in message
    assert message != get_error_message(
        'item_quantity_above_ceiling', 'en', quantity='9', ceiling='5'
    )


def test_a_module_message_falls_back_to_its_english_before_the_core_one(
    tmp_path: Path,
) -> None:
    """A community module catalog may hold one key; the module's English
    answers for the rest instead of the core catalogue's raw key."""
    i18n = tmp_path / 'i18n'
    i18n.mkdir()
    (i18n / 'en.json').write_text(
        json.dumps({'only_in_english': 'Only English says this'}), encoding='utf-8'
    )
    (i18n / 'pt.json').write_text(json.dumps({'another': 'Outra'}), encoding='utf-8')
    load_module_translations('community_demo', i18n)

    assert module_message('community_demo', 'only_in_english', 'pt') == (
        'Only English says this'
    )


@pytest.mark.parametrize('module_type', ['core', 'official', 'community'])
def test_no_module_is_required_to_carry_a_community_language(
    tmp_path: Path, module_type: str
) -> None:
    mod = tmp_path / 'demo'
    mod.mkdir()
    (mod / 'manifest.json').write_text(
        json.dumps({'name': 'demo', 'version': '1.0.0', 'module_type': module_type}),
        encoding='utf-8',
    )
    (mod / 'i18n').mkdir()
    for language in MAINTAINED_LANGUAGES:
        (mod / 'i18n' / f'{language}.json').write_text('{}', encoding='utf-8')

    assert validate_i18n(mod) == []
    assert not set(REQUIRED_LANGUAGES) & set(COMMUNITY_LANGUAGES)
