"""i18n service for handling translations in the application.

Provides functions to get translated error messages and handle language detection.
"""

import functools
import json
import os
from contextvars import ContextVar
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from babel import Locale
from babel.numbers import get_decimal_symbol
from fastapi import Header

from app.core.logging import get_logger
from app.i18n import (
    COMMUNITY_ERRORS,
    ERRORS,
    SHOPPING_LABELS,
    SUPPORTED_LANGUAGES,
    UNIT_LABELS,
    Language,
)

logger = get_logger(__name__)

# Cache for module translations
# Structure: {module_name: {lang: {key: value}}}
_MODULE_TRANSLATIONS: dict[str, dict[str, dict[str, str]]] = {}


def load_module_translations(module_name: str, i18n_path: Path) -> None:
    """Load translation files from a module's i18n directory."""
    if not i18n_path.exists() or not i18n_path.is_dir():
        return

    _MODULE_TRANSLATIONS[module_name] = {}
    for lang in SUPPORTED_LANGUAGES:
        lang_file = i18n_path / f'{lang}.json'
        if lang_file.exists():
            try:
                with open(lang_file, encoding='utf-8') as f:
                    _MODULE_TRANSLATIONS[module_name][lang] = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(
                    f'Error loading translations for module {module_name}, lang {lang}: {e}'
                )


def get_module_error_message(
    module_name: str, key: str, lang: Language | None = None, **kwargs
) -> str:
    """Get translated error message from a specific module."""
    if lang is None:
        lang = get_current_lang()

    module_data = _MODULE_TRANSLATIONS.get(module_name, {})
    # English is the one catalog a module must ship, so it answers for a
    # language the module has no file for and for a key that language lacks.
    lang_data = module_data.get(lang, {})
    if key not in lang_data:
        lang_data = module_data.get('en', {})

    if key in lang_data:
        msg = lang_data[key]
        if kwargs:
            try:
                return msg.format(**kwargs)
            except (KeyError, ValueError):
                return msg
        return msg

    return get_error_message(key, lang, **kwargs)


# Default language from environment variable, fallback to 'en'
@functools.cache
def get_default_language() -> Language:
    """Get default language from environment or return 'en'."""
    lang = os.getenv('DEFAULT_LANGUAGE', 'en')
    if lang in SUPPORTED_LANGUAGES:
        return lang  # type: ignore
    return 'en'


def get_language_from_accept_header(accept_language: str | None = None) -> Language:
    """Extract language from Accept-Language header.

    Args:
        accept_language: The Accept-Language header value (e.g., "en-US,en;q=0.9,pl;q=0.8")

    Returns:
        Language code from SUPPORTED_LANGUAGES
    """
    if not accept_language:
        return get_default_language()

    # Parse Accept-Language header
    # Format: "en-US,en;q=0.9,pl;q=0.8"
    languages = []
    for part in accept_language.split(','):
        part = part.strip()
        if ';' in part:
            lang, q = part.split(';', 1)
            lang = lang.strip()
            if lang.startswith('-'):
                continue  # Skip region-specific without base lang
            if q.strip().startswith('q='):
                try:
                    quality = float(q.strip()[2:])
                    languages.append((lang, quality))
                except ValueError:
                    languages.append((lang, 1.0))
            else:
                languages.append((lang, 1.0))
        else:
            if part.startswith('-'):
                continue  # Skip region-specific without base lang
            languages.append((part.strip(), 1.0))

    if not languages:
        return get_default_language()

    # Sort by quality and return the highest priority language
    languages.sort(key=lambda x: x[1], reverse=True)

    for lang, _ in languages:
        lang_code = lang.split('-')[0].lower()
        if lang_code in SUPPORTED_LANGUAGES:
            return lang_code  # type: ignore

    return get_default_language()


def _messages_for(lang: Language) -> dict[str, str]:
    """The catalogue *lang* answers from, key by key.

    A maintained language holds every key. A community language holds the
    keys it has so far; the rest are English, the way the interface falls back
    per key, so no change has to translate it.
    """
    if lang in ERRORS:
        return {k: str(v) for k, v in ERRORS[lang].items()}
    messages = {k: str(v) for k, v in ERRORS['en'].items()}
    messages.update(COMMUNITY_ERRORS.get(lang, {}))
    return messages


def get_error_message(key: str, lang: Language | None = None, **kwargs) -> str:
    """Get translated error message by key.

    Args:
        key: The error message key (e.g., "item_not_found")
        lang: The language code (en or pl). If None, uses default language.
        **kwargs: Variables for string interpolation.

    Returns:
        The translated error message, or the key if not found.
    """
    if lang is None:
        lang = get_default_language()

    messages = _messages_for(lang)
    if key not in messages:
        # The fallback answers with the key, so the key reaches the reader as
        # an identifier; this warning is the only record a new key with no
        # catalogue row ever leaves. Every lookup naming a hole is a bug
        # upstream, not a translation miss here.
        logger.warning('Error message key missing from the catalogue: %s', key)
    msg = messages.get(key, key)

    if kwargs:
        try:
            return msg.format(**kwargs)
        except (KeyError, ValueError):
            return msg

    return msg


@functools.lru_cache(maxsize=32)
def _plural_category(lang: Language, count: int) -> str:
    """The CLDR plural category *count* falls in for *lang*: 'one', 'few', …"""
    return Locale.parse(lang).plural_form(count)


def get_plural_error_message(
    key: str, count: int, lang: Language | None = None, **kwargs
) -> str:
    """Get a translated error message whose counted noun agrees with *count*.

    The catalogue may carry ``<key>_<category>`` rows, where the category is
    the CLDR plural category for *count* in *lang* — ``_one`` for 1, ``_few``
    for 2–4 in Polish, the base key for every category a language carries no
    row for. A language whose counted noun does not inflect therefore keeps a
    single sentence. *count* only picks the row; the sentence interpolates
    *kwargs* as usual (``{min_length}``, not ``{count}``).
    """
    if lang is None:
        lang = get_default_language()

    plural_key = f'{key}_{_plural_category(lang, count)}'
    resolved = plural_key if plural_key in _messages_for(lang) else key
    return get_error_message(resolved, lang, **kwargs)


# Dependency for extracting language from header
async def get_lang_from_header(
    accept_language: Annotated[str | None, Header(alias='Accept-Language')] = None,
) -> Language:
    """Dependency to extract language from Accept-Language header.

    Usage:
        @router.get("/items/{item_id}")
        async def get_item(
            item_id: UUID,
            lang: Language = Depends(get_lang_from_header),
            db: AsyncSession = Depends(get_async_db)
        ):
            ...
    """
    return get_language_from_accept_header(accept_language)


# Context variable for storing current language (for use in exception handlers)
_current_lang: ContextVar[Language | None] = ContextVar('current_lang', default=None)


def set_current_lang(lang: Language) -> None:
    """Set the current language context variable."""
    _current_lang.set(lang)


def get_current_lang() -> Language:
    """Get the current language context variable."""
    return _current_lang.get() or get_default_language()


#: Languages that write the decimal mark as a comma. Read from CLDR through
#: Babel rather than kept as a second hand list: the separator is a property
#: of the language, so a new one arrives with the right answer instead of with
#: whatever a contributor remembered to type.
_COMMA_DECIMAL_LANGUAGES = frozenset(
    language for language in SUPPORTED_LANGUAGES if get_decimal_symbol(language) == ','
)


def stated_quantity(quantity: Decimal, lang: Language | None = None) -> str:
    """The quantity as a refusal states it, whatever scale it arrived on.

    A refusal is read beside the screen's own numbers, so it uses the same
    shape: trailing zeros the store kept are dropped (``2.000`` is "2"), a
    whole number stays out of scientific notation (``1E+1`` is a number no
    reader typed), and the decimal separator follows the reader — a reader of
    pl/de/fr/es gets "2,5", not the store's dot. Callers interpolate the
    result into a translated sentence, never the raw ``Decimal``.
    """
    if lang is None:
        lang = get_current_lang()
    stated = format(quantity.normalize(), 'f')
    if lang in _COMMA_DECIMAL_LANGUAGES:
        stated = stated.replace('.', ',')
    return stated


def get_unit_label(symbol: str, lang: Language | None = None) -> str:
    """The unit's label in *lang* — a piece is "szt." in a Polish session.

    A refusal that says "the unit 'pcs'" names the unit by a code the reader
    never saw; the screen called it "szt.". The catalogue is the frontend's
    own ``units.*`` labels (see :mod:`app.i18n._units`), and a symbol it does
    not carry — an organization's own unit — is returned unchanged: the
    symbol is unfamiliar, but it is what the data says, which beats inventing
    a word for it.
    """
    if lang is None:
        lang = get_current_lang()

    labels: dict[str, str] = {
        k: str(v) for k, v in UNIT_LABELS.get(lang, UNIT_LABELS['en']).items()
    }
    return labels.get(symbol, symbol)


def get_shopping_label(key: str, lang: Language | None = None) -> str:
    """Get translated shopping label by key.

    Args:
        key: The label key (e.g., "default_name_template", "month_1")
        lang: The language code (en or pl). If None, uses current context language.

    Returns:
        The translated label, or the key if not found.
    """
    if lang is None:
        lang = get_current_lang()

    labels: dict[str, str] = {
        k: str(v) for k, v in SHOPPING_LABELS.get(lang, SHOPPING_LABELS['en']).items()
    }
    return labels.get(key, key)
