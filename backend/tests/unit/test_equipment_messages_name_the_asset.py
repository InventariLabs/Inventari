"""The equipment module's refusals name the thing with the module's own word.

The module calls the individual it tracks an asset (Gerät, actif, activo).
Item, Artikel and article are retired words there, and the French refusal
for a second return called the assignment an attribute.
"""

import pytest

from app.i18n.service import get_error_message

ASSET_WORD = {
    'en': 'asset',
    'de': 'gerät',
    'fr': 'actif',
    'es': 'activo',
    'pt': 'ativo',
}
RETIRED = {
    'en': ('item',),
    'de': ('artikel', 'assets'),
    'fr': ('article', 'élément'),
    'es': ('artículo', 'elemento'),
    'pt': ('item',),
}


@pytest.mark.parametrize('lang', sorted(ASSET_WORD))
def test_a_second_assignment_names_the_asset(lang: str) -> None:
    text = get_error_message('equipment_assignment_already_active', lang).lower()
    assert ASSET_WORD[lang] in text
    assert not any(word in text for word in RETIRED[lang])


def test_a_second_return_in_french_speaks_of_the_assignment() -> None:
    text = get_error_message('equipment_assignment_already_checked_in', 'fr')
    assert 'attribut' not in text.replace('attribution', '')
    assert 'attribution' in text


def test_a_mailbox_less_account_in_german_has_no_english_word() -> None:
    text = get_error_message('user_email_required', 'de')
    assert 'Assets' not in text
    assert 'Geräte' in text
