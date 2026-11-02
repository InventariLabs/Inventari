"""Every country code the API accepts must print as a name, in five languages.

The printed name used to come from a hand-maintained map of 40 codes while
the API validated against the full ISO 3166-1 set, so a partner in Dubai
appeared on screen as "United Arab Emirates" and on the PDF as "AE". The map
is gone — names now come from Babel's CLDR territory tables — but nothing
pinned the guarantee, and a fallback map is exactly the kind of thing that
gets reintroduced for one missing locale.
"""

import pytest

from app.core.contracts._core_dtos import ISO_3166_ALPHA2_CODES
from app.i18n import SUPPORTED_LANGUAGES
from app.services.pdf_utils import country_name


class TestCountryName:
    @pytest.mark.parametrize('lang', SUPPORTED_LANGUAGES)
    def test_every_accepted_code_resolves_to_a_name(self, lang: str) -> None:
        unresolved = [
            code
            for code in sorted(ISO_3166_ALPHA2_CODES)
            if country_name(code, lang) == code
        ]
        assert unresolved == [], (
            f'{len(unresolved)} code(s) print as a bare code in {lang}: {unresolved[:10]}'
        )

    def test_names_differ_by_language(self) -> None:
        assert country_name('DE', 'pl') == 'Niemcy'
        assert country_name('DE', 'de') == 'Deutschland'
        assert country_name('AE', 'en') == 'United Arab Emirates'

    def test_unknown_language_falls_back_to_english(self) -> None:
        assert country_name('DE', 'sv') == country_name('DE', 'en')

    def test_free_text_is_printed_as_it_stands(self) -> None:
        """Addresses older than the ISO validation carry prose, not codes."""
        assert country_name('Polska', 'pl') == 'Polska'
