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

    @pytest.mark.parametrize(
        ('lang', 'singular_advice', 'plural_advice'),
        [
            ('en', 'ask for the permission', 'ask for these permissions'),
            ('pl', 'poproś o to uprawnienie', 'poproś o te uprawnienia'),
            (
                'de',
                'fordern Sie die Berechtigung an',
                'fordern Sie diese Berechtigungen an',
            ),
            ('fr', 'demandez la permission', 'demandez ces permissions'),
            ('es', 'solicita el permiso', 'solicita esos permisos'),
            ('pt', 'peça a permissão', 'peça essas permissões'),
        ],
    )
    def test_the_import_refusal_agrees_with_its_count_to_the_end(
        self, lang, singular_advice, plural_advice
    ):
        """Two missing permissions are asked for as two, and one permission
        is one toggle to turn off, not several."""
        two = get_plural_error_message(
            'import_create_forbidden',
            2,
            lang,
            permissions='categories:write, locations:write',
        )
        one = get_plural_error_message(
            'import_create_forbidden', 1, lang, permissions='locations:write'
        )

        assert two.endswith(plural_advice)
        assert singular_advice not in two
        assert one.endswith(singular_advice)

    @pytest.mark.parametrize(
        ('lang', 'one_toggle'),
        [
            ('en', 'Turn off the matching toggle in the import dialog'),
            ('pl', 'Wyłącz odpowiedni przełącznik w oknie importu'),
            ('de', 'Deaktivieren Sie den entsprechenden Schalter im Importdialog'),
            ('fr', "Désactivez l'interrupteur correspondant dans la boîte d'import"),
            ('es', 'Desactiva el interruptor correspondiente en el diálogo'),
            ('pt', 'Desative a opção correspondente na janela de importação'),
        ],
    )
    def test_one_permission_names_one_toggle(self, lang, one_toggle):
        one = get_plural_error_message(
            'import_create_forbidden', 1, lang, permissions='locations:write'
        )

        assert one_toggle in one

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


class TestPolishCountedRefusalsAgreeWithTheirCount:
    """A Polish refusal that counts things inflects the noun for every count.

    "przez 1 miejsc" is the one sentence these keys used to carry; Polish needs
    a form for one, for two to four and for the rest.
    """

    @pytest.mark.parametrize(
        ('key', 'count', 'expected'),
        [
            ('storage_type_in_use', 1, 'przez 1 miejsce'),
            ('storage_type_in_use', 3, 'przez 3 miejsca'),
            ('storage_type_in_use', 5, 'przez 5 miejsc'),
            ('template_in_use_by_items', 1, 'używa go 1 produkt'),
            ('template_in_use_by_items', 2, 'używa go 2 produkty'),
            ('template_in_use_by_items', 12, 'używa go 12 produktów'),
            ('storage_archive_blocked_by_items', 1, 'przechowywany jest tu 1 produkt.'),
            ('storage_archive_blocked_by_items', 4, 'przechowywane są tu 4 produkty.'),
            (
                'storage_archive_blocked_by_items',
                7,
                'przechowywanych jest tu 7 produktów.',
            ),
            ('stock_take_uncounted_items', 1, 'Pozostała 1 niepoliczona pozycja'),
            ('stock_take_uncounted_items', 3, 'Pozostały 3 niepoliczone pozycje'),
            ('stock_take_uncounted_items', 8, 'Pozostało 8 niepoliczonych pozycji'),
            ('stock_take_over_cap', 1, 'W 1 pozycji policzona'),
            ('stock_take_over_cap', 2, 'W 2 pozycjach policzona'),
            ('stock_take_stock_moved', 1, 'W 1 pozycji stan'),
            ('stock_take_stock_moved', 6, 'W 6 pozycjach stan'),
            (
                'partner_delete_open_purchase_orders',
                1,
                '1 otwarte zamówienie zakupowe odwołuje się',
            ),
            (
                'partner_delete_open_purchase_orders',
                2,
                '2 otwarte zamówienia zakupowe odwołują się',
            ),
            (
                'partner_delete_open_purchase_orders',
                9,
                '9 otwartych zamówień zakupowych odwołuje się',
            ),
            ('storage_delete_blocked_by_movements', 1, '1 ruch magazynowy'),
            ('storage_delete_blocked_by_movements', 2, '2 ruchy magazynowe'),
            ('storage_delete_blocked_by_movements', 5, '5 ruchów magazynowych'),
        ],
    )
    def test_the_noun_takes_the_form_of_its_count(self, key, count, expected):
        message = get_plural_error_message(key, count, 'pl', count=count)
        assert expected in message

    def test_a_polish_quotation_closes_with_a_curly_quote(self):
        for key in (
            'approval_stage_unsolvable',
            'approval_stage_open_unsolvable',
            'storage_name_collision',
        ):
            message = get_error_message(key, 'pl', label='Etap', name='Półka')
            assert '„' in message
            assert '"' not in message


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
    the public confirm endpoint maps its ValueErrors to. They exist in every
    catalog: get_error_message answers an unknown key with the key itself, so the
    public page would show the identifier raw, in every language, to a reader who
    holds the equipment."""

    def test_both_keys_read_as_sentences_in_every_language(self):
        from app.i18n.service import get_error_message

        for lang in SUPPORTED_LANGUAGES:
            for key in ('campaign_closed', 'assignment_already_returned'):
                value = get_error_message(key, lang)
                assert value != key, (lang, key)
                assert ' ' in value and value.endswith('.'), (lang, key, value)


class TestTheCatalogueSpeaksLikeTheScreens:
    """A refusal uses the words of the screen it is read on."""

    @pytest.mark.parametrize(
        'key',
        [
            'documents_approval_workflow_missing',
            'po_approval_workflow_missing',
            'document_rework_wrong_status',
            'stock_take_tolerance_not_allowed',
        ],
    )
    def test_german_names_an_approval_the_way_its_screens_do(self, key):
        """The German screens of every approval workflow say Genehmigung."""
        message = get_error_message(key, 'de', status='CONFIRMED')

        assert 'genehmig' in message.lower()
        assert 'freigabe' not in message.lower()

    def test_an_account_waiting_for_activation_keeps_its_own_word(self):
        """Activating an account is not an approval workflow."""
        assert 'Freigabe' in get_error_message('user_inactive', 'de')

    @pytest.mark.parametrize(
        ('lang', 'module'),
        [
            ('en', 'warehouse'),
            ('pl', 'Magazyn'),
            ('de', 'Lager'),
            ('es', 'Almacén'),
            ('fr', 'Entrepôt'),
            ('pt', 'armazém'),
        ],
    )
    def test_a_document_template_belongs_to_the_module_the_launcher_names(
        self, lang, module
    ):
        assert module in get_error_message('document_template_wrong_module', lang)
