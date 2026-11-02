"""Translation of built-in pydantic validation errors.

FastAPI's default 422 prints pydantic's own English sentences ("String
should have at most 255 characters") at every consumer, in every language.
The infrastructure for translated errors already existed — ``get_error_message``
and the session language set by middleware — but it only served our own
``ValueError`` validators; the built-in constraint checks never went through it.

This map names the error types a person can act on and which ``ctx`` values
their messages take. A type the catalog does not carry keeps pydantic's
wording: an untranslated but precise sentence beats a silently dropped one.
"""

from typing import Any

from app.i18n._types import Language
from app.i18n.service import (
    get_current_lang,
    get_error_message,
    get_plural_error_message,
)

#: pydantic error type → (catalog key, ctx keys the message interpolates).
_VALIDATION_TEMPLATES: dict[str, tuple[str, tuple[str, ...]]] = {
    'missing': ('validation_missing', ()),
    'string_too_long': ('validation_string_too_long', ('max_length',)),
    'string_too_short': ('validation_string_too_short', ('min_length',)),
    'string_pattern_mismatch': ('validation_pattern', ()),
    'greater_than_equal': ('validation_greater_than_equal', ('ge',)),
    'greater_than': ('validation_greater_than', ('gt',)),
    'less_than_equal': ('validation_less_than_equal', ('le',)),
    'less_than': ('validation_less_than', ('lt',)),
    'enum': ('validation_enum', ('expected',)),
    'literal_error': ('validation_enum', ('expected',)),
    'int_parsing': ('validation_int', ()),
    'int_from_float': ('validation_int', ()),
    'float_parsing': ('validation_number', ()),
    'decimal_parsing': ('validation_number', ()),
    'finite_number': ('validation_number', ()),
    'bool_parsing': ('validation_boolean', ()),
    'uuid_parsing': ('validation_identifier', ()),
    'date_parsing': ('validation_date', ()),
    'date_from_datetime_parsing': ('validation_date', ()),
    'datetime_parsing': ('validation_date', ()),
    'datetime_from_date_parsing': ('validation_date', ()),
}

#: pydantic wraps a validator's own ValueError as "Value error, <message>".
_VALUE_ERROR_PREFIX = 'Value error, '

#: Types whose sentence counts characters; the count is the one ctx parameter
#: and the catalogue carries the plural forms the language needs.
_COUNTED_ERROR_TYPES = frozenset({'string_too_long', 'string_too_short'})


def translate_validation_error(
    error: dict[str, Any], lang: Language | None = None
) -> str:
    """One pydantic error dict in, a message in the session's language out.

    The dict is pydantic's own shape (``type``, ``msg``, ``ctx``) — read-only
    here; the caller decides what to do with the result. Our own validator
    ``ValueError`` messages are already written for a person, so they only
    lose the "Value error, " wrapper pydantic bolts on.
    """
    if lang is None:
        lang = get_current_lang()

    kind = str(error.get('type', ''))
    if kind == 'value_error':
        msg = str(error.get('msg', ''))
        return (
            msg.removeprefix(_VALUE_ERROR_PREFIX)
            if msg.startswith(_VALUE_ERROR_PREFIX)
            else msg
        )

    template = _VALIDATION_TEMPLATES.get(kind)
    if template is None:
        return str(error.get('msg', 'invalid input'))

    key, param_names = template
    ctx = error.get('ctx') or {}
    kwargs = {name: ctx[name] for name in param_names if name in ctx}
    if kind in _COUNTED_ERROR_TYPES and param_names and param_names[0] in kwargs:
        return get_plural_error_message(
            key, int(kwargs[param_names[0]]), lang, **kwargs
        )
    return get_error_message(key, lang, **kwargs)
