"""PDF numbers take their decimal separator from the one set in the i18n service.

CONTRIBUTING promises the comma-decimal languages are named in one place. The
PDF filters once kept a hand-written tuple of their own, so a language added
to that set would still have printed dots on every document.
"""

import pytest

from app.i18n import SUPPORTED_LANGUAGES, service
from app.services.pdf_utils import (
    filter_format_decimal,
    filter_format_pct,
    filter_format_qty,
)


@pytest.mark.parametrize('lang', SUPPORTED_LANGUAGES)
def test_each_supported_language_prints_the_separator_the_service_names(
    lang: str,
) -> None:
    expected = '1,50' if lang in service._COMMA_DECIMAL_LANGUAGES else '1.50'
    assert filter_format_decimal('1.5', lang) == expected


def test_a_regional_tag_follows_its_language() -> None:
    assert filter_format_decimal('1.5', 'pl-PL') == '1,50'
    assert filter_format_decimal('1.5', 'en-GB') == '1.50'


def test_a_language_added_to_the_service_set_prints_commas_without_a_second_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert filter_format_decimal('1.5', 'it') == '1.50'
    monkeypatch.setattr(service, '_COMMA_DECIMAL_LANGUAGES', frozenset({'it'}))
    assert filter_format_decimal('1.5', 'it') == '1,50'
    assert filter_format_qty('2.5', 'it') == '2,5'
    assert filter_format_pct('7.5', 'it') == '7,50%'
