"""Unit tests for i18n service."""

import logging

import pytest

from app.i18n import SUPPORTED_LANGUAGES, Language
from app.i18n.service import (
    get_default_language,
    get_error_message,
    get_language_from_accept_header,
    get_plural_error_message,
)


class TestGetErrorMessage:
    """Tests for get_error_message function."""

    def test_get_error_message_english(self):
        """Test getting error message in English."""
        msg = get_error_message('item_not_found', 'en')
        assert msg == 'Item not found'

    def test_get_error_message_polish(self):
        """Test getting error message in Polish."""
        msg = get_error_message('item_not_found', 'pl')
        assert msg == 'Produkt nie został znaleziony'

    def test_get_error_message_invalid_key(self):
        """Test getting error message for invalid key returns the key."""
        msg = get_error_message('nonexistent_key', 'en')
        assert msg == 'nonexistent_key'

    def test_get_error_message_invalid_key_polish(self):
        """Test getting error message for invalid key in Polish returns the key."""
        msg = get_error_message('nonexistent_key', 'pl')
        assert msg == 'nonexistent_key'

    def test_get_error_message_invalid_key_leaves_a_trace(self, caplog):
        """The fallback still answers with the key, but not in silence: a key
        the catalogue does not know reaches the reader as an identifier, so
        each lookup leaves a warning naming it."""
        with caplog.at_level(logging.WARNING):
            msg = get_error_message('nonexistent_key_without_a_row', 'en')

        assert msg == 'nonexistent_key_without_a_row'
        assert any(
            record.levelno == logging.WARNING
            and 'nonexistent_key_without_a_row' in record.getMessage()
            for record in caplog.records
        ), caplog.records

    def test_get_error_message_known_key_stays_silent(self, caplog):
        """The trace must point at a hole, not at every lookup."""
        with caplog.at_level(logging.WARNING):
            msg = get_error_message('item_not_found', 'en')

        assert msg == 'Item not found'
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings == [], warnings

    def test_get_error_message_default_language(self):
        """Test getting error message with default language."""
        msg = get_error_message('invalid_credentials')
        assert msg == 'Invalid email or password'

    def test_get_error_message_auth_errors(self):
        """Test all auth error messages."""
        assert (
            get_error_message('invalid_credentials', 'en')
            == 'Invalid email or password'
        )
        assert (
            get_error_message('user_already_exists', 'en')
            == 'User with this email already exists'
        )
        assert (
            get_error_message('token_expired', 'en')
            == 'Authentication token has expired'
        )

    def test_get_error_message_validation_errors(self):
        """Test validation error messages."""
        assert get_error_message('field_required', 'en') == 'This field is required'
        assert get_error_message('invalid_email', 'en') == 'Invalid email format'
        assert (
            get_error_message('password_too_short', 'en')
            == 'Password must be at least 8 characters'
        )


class TestGetPluralErrorMessage:
    """A sentence with a counted noun takes the form the language counts with.

    Polish says "1 znak", "2 znaki", "5 znaków" — one sentence cannot serve all
    three, so the catalogue carries the forms and the service picks one from
    the count. A language whose noun does not change keeps its single sentence.
    """

    def test_polish_singular(self):
        assert (
            get_plural_error_message(
                'validation_string_too_short', 1, 'pl', min_length=1
            )
            == 'Musi mieć co najmniej 1 znak'
        )

    def test_polish_few(self):
        for count in (2, 3, 4, 22, 24):
            assert (
                get_plural_error_message(
                    'validation_string_too_short', count, 'pl', min_length=count
                )
                == f'Musi mieć co najmniej {count} znaki'
            )

    def test_polish_many(self):
        for count in (0, 5, 21, 112):
            assert (
                get_plural_error_message(
                    'validation_string_too_short', count, 'pl', min_length=count
                )
                == f'Musi mieć co najmniej {count} znaków'
            )

    def test_polish_upper_limit(self):
        assert (
            get_plural_error_message(
                'validation_string_too_long', 1, 'pl', max_length=1
            )
            == 'Może mieć najwyżej 1 znak'
        )

    def test_english_singular(self):
        assert (
            get_plural_error_message(
                'validation_string_too_short', 1, 'en', min_length=1
            )
            == 'Should have at least 1 character'
        )

    @pytest.mark.parametrize(
        ('count', 'clause', 'pronoun'),
        [
            (1, 'trwa 1 aktywna sesja kompletacji', 'ją'),
            (2, 'trwają 2 aktywne sesje kompletacji', 'je'),
            (5, 'trwa 5 aktywnych sesji kompletacji', 'je'),
        ],
    )
    def test_the_session_refusal_agrees_with_its_count(self, count, clause, pronoun):
        message = get_plural_error_message(
            'document_wms_picking_active', count, 'pl', sessions=count
        )
        assert clause in message
        assert f'Najpierw {pronoun} zakończ' in message

    @pytest.mark.parametrize(
        ('lang', 'short', 'long'),
        [
            (
                'fr',
                'Doit contenir au minimum 1 caractère',
                'Doit contenir au maximum 1 caractère',
            ),
            (
                'es',
                'Debe tener al menos 1 carácter',
                'Debe tener como máximo 1 carácter',
            ),
        ],
    )
    def test_french_and_spanish_count_one_character_in_the_singular(
        self, lang, short, long
    ):
        assert (
            get_plural_error_message(
                'validation_string_too_short', 1, lang, min_length=1
            )
            == short
        )
        assert (
            get_plural_error_message(
                'validation_string_too_long', 1, lang, max_length=1
            )
            == long
        )

    @pytest.mark.parametrize(
        ('lang', 'expected'),
        [
            ('fr', 'Doit contenir au minimum 2 caractères'),
            ('es', 'Debe tener al menos 2 caracteres'),
        ],
    )
    def test_french_and_spanish_keep_the_plural_for_other_counts(self, lang, expected):
        assert (
            get_plural_error_message(
                'validation_string_too_short', 2, lang, min_length=2
            )
            == expected
        )

    def test_a_language_without_plural_forms_keeps_the_single_sentence(self):
        assert (
            get_plural_error_message(
                'validation_string_too_short', 1, 'de', min_length=1
            )
            == 'Muss mindestens 1 Zeichen haben'
        )

    def test_a_key_without_plural_forms_falls_back_to_the_base(self):
        assert (
            get_plural_error_message('item_not_found', 2, 'pl')
            == 'Produkt nie został znaleziony'
        )

    def test_an_unknown_key_still_warns_and_answers_with_the_key(self, caplog):
        with caplog.at_level(logging.WARNING):
            msg = get_plural_error_message('nonexistent_key_without_a_row', 2, 'en')

        assert msg == 'nonexistent_key_without_a_row'
        assert any(
            record.levelno == logging.WARNING
            and 'nonexistent_key_without_a_row' in record.getMessage()
            for record in caplog.records
        ), caplog.records


class TestGetLanguageFromAcceptHeader:
    """Tests for get_language_from_accept_header function."""

    def test_get_language_from_accept_header_english(self):
        """Test extracting English from Accept-Language header."""
        lang = get_language_from_accept_header('en-US,en;q=0.9')
        assert lang == 'en'

    def test_get_language_from_accept_header_polish(self):
        """Test extracting Polish from Accept-Language header."""
        lang = get_language_from_accept_header('pl-PL,pl;q=0.9,en;q=0.8')
        assert lang == 'pl'

    def test_get_language_from_accept_header_no_header(self):
        """Test default language when no header provided."""
        lang = get_language_from_accept_header(None)
        assert lang == 'en'

    def test_get_language_from_accept_header_empty_header(self):
        """Test default language when header is empty."""
        lang = get_language_from_accept_header('')
        assert lang == 'en'

    def test_get_language_from_accept_header_german(self):
        """German is negotiated from the header."""
        lang = get_language_from_accept_header('de-DE,de;q=0.9')
        assert lang == 'de'

    def test_get_language_from_accept_header_french_region_fallback(self):
        """Regional variant falls back to the base language."""
        lang = get_language_from_accept_header('fr-CA,fr;q=0.9')
        assert lang == 'fr'

    def test_get_language_from_accept_header_spanish_quality(self):
        """Highest quality value wins."""
        lang = get_language_from_accept_header('es;q=0.9,en;q=0.5')
        assert lang == 'es'

    def test_get_language_from_accept_header_unsupported_language(self):
        """Test default language when only unsupported languages."""
        lang = get_language_from_accept_header('ja-JP,ja;q=0.9')
        assert lang == 'en'

    def test_get_language_from_accept_header_with_quality(self):
        """Test extracting language with quality values."""
        lang = get_language_from_accept_header('en;q=0.9,pl;q=1.0')
        assert lang == 'pl'

    def test_get_language_from_accept_header_simple(self):
        """Test extracting language from simple header."""
        lang = get_language_from_accept_header('pl')
        assert lang == 'pl'


class TestGetDefaultLanguage:
    """Tests for get_default_language function."""

    def test_get_default_language_from_env(self, monkeypatch):
        """Test getting default language from environment variable."""
        # Clear the @functools.cache so the env var change takes effect
        get_default_language.cache_clear()

        monkeypatch.setenv('DEFAULT_LANGUAGE', 'pl')
        # The function reads env var at call time, not import time
        lang = get_default_language()
        assert lang == 'pl'

        # Reset cache after test so other tests aren't affected
        get_default_language.cache_clear()

    def test_get_default_language_fallback(self):
        """Test default language fallback to English."""
        lang = get_default_language()
        assert lang == 'en'


class TestLanguageType:
    """Tests for Language type alias."""

    def test_language_type_valid_values(self):
        """Test that Language type accepts valid values."""
        lang: Language = 'en'
        assert lang == 'en'

        lang = 'pl'
        assert lang == 'pl'


class TestTheAttestationRefusalsExistInEveryCatalog:
    """``campaign_closed`` and ``assignment_already_returned`` are the keys
    the public confirm endpoint maps its ValueErrors to. They used to exist
    nowhere, and get_error_message answers an unknown key with the key
    itself — so the public page showed the identifier raw, in every
    language, to a reader who holds the equipment."""

    def test_both_keys_read_as_sentences_in_every_language(self):
        from app.i18n.service import get_error_message

        for lang in SUPPORTED_LANGUAGES:
            for key in ('campaign_closed', 'assignment_already_returned'):
                value = get_error_message(key, lang)
                assert value != key, (lang, key)
                assert ' ' in value and value.endswith('.'), (lang, key, value)
