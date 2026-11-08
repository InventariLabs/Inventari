"""
Minimal JSON-Schema subset validator for module settings payloads.

Supports the schema surface we actually need:
- type: object | string | integer | number | boolean
- properties / required / additionalProperties (object only)
- enum
- minimum / maximum (integer + number)
- minLength / maxLength (string)
- format: "secret" (returns the path; encryption happens elsewhere)
- one level of nested objects
- version: the settings shape version the schema declares (see
  ``settings_schema_version``)

Full JSON-Schema support is intentionally NOT a goal — modules declare
small, focused configs and we want zero new dependencies. If a schema
needs something this validator does not support, it will be rejected
with a clear ``SchemaValidationError`` so the module author knows to
simplify or extend the validator.

The key ``__schema_version`` (``SCHEMA_VERSION_KEY``) is reserved for
core's stamp recording the shape version a stored blob was written
against. A schema may not declare it; a payload that carries it is
ignored, so a stored blob round-trips through validation untouched.

Two kinds of refusal leave this module. A payload that breaks the schema is
a reader's mistake: ``SchemaValidationError`` carries a translation key and
the 400 envelope answers in the reader's language. A schema the validator
cannot read is the module author's mistake: ``ContractViolationError``, for
the developer and the log.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.core.exceptions import ContractViolationError, ServiceRejectionError


class SchemaValidationError(ServiceRejectionError):
    """Raised when a payload does not satisfy the schema.

    Always built from an i18n key, so the refusal reaches the reader in
    their language and the response's ``lang`` stamp is true.
    """


_SECRET_FORMAT_VALUE = 'secret'  # noqa: S105 — schema literal, not a password

#: Reserved key inside a module's settings namespace recording which version
#: of the schema the blob was written against. Core writes it on every write
#: and hides it from every read; a schema that declares it as a property is
#: a contract violation, and a payload that carries it is ignored.
SCHEMA_VERSION_KEY = '__schema_version'

#: The version a blob reads as when it carries no stamp: written before
#: versioning existed.
UNSTAMPED_SCHEMA_VERSION = 0

_DEFAULT_SCHEMA_VERSION = 1


def settings_schema_version(schema: dict[str, object] | None) -> int:
    """Return the settings-shape version *schema* declares.

    This is the version of the settings *shape* — which keys exist and what
    they mean — not the module's own version. A schema that declares no
    ``version`` is shape 1. A ``version`` that is not a positive integer is
    the module author's mistake.
    """
    if not schema:
        return _DEFAULT_SCHEMA_VERSION
    version = schema.get('version', _DEFAULT_SCHEMA_VERSION)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ContractViolationError(
            f'Schema "version" must be a positive integer, got {version!r}'
        )
    return version


def validate_payload_against_schema(
    payload: Any, schema: dict[str, object]
) -> dict[str, object]:
    """Validate *payload* against *schema*; return the cleaned payload.

    Behaviour:
    - declared properties are type-checked; invalid values raise.
    - when ``additionalProperties`` is False (default for new schemas),
      unknown keys raise ``SchemaValidationError``.
    - when ``additionalProperties`` is True, unknown keys pass through.

    The returned dict is a shallow copy containing only validated keys
    (and any unknown keys if allowed by ``additionalProperties``).
    """
    if not isinstance(payload, dict):
        raise SchemaValidationError('settings_payload_not_object')
    if not isinstance(schema, dict):
        raise ContractViolationError('Schema must be a JSON object')

    schema_type = schema.get('type', 'object')
    if schema_type != 'object':
        raise ContractViolationError(
            f'Root schema type must be "object", got {schema_type!r}'
        )

    properties = schema.get('properties', {}) or {}
    required = schema.get('required', []) or []
    additional = schema.get('additionalProperties', False)

    if not isinstance(properties, dict):
        raise ContractViolationError('Schema "properties" must be an object')
    if not isinstance(required, list):
        raise ContractViolationError('Schema "required" must be a list')
    _refuse_the_reserved_key(schema)

    for key in required:
        if key not in payload:
            raise SchemaValidationError('settings_field_required', field=key)
        if key not in properties:
            raise ContractViolationError(f'Required field {key!r} has no schema entry')

    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        # Core's stamp is metadata about the blob, not module data: ignored
        # here (and so stripped from the cleaned payload) the same way at
        # every nesting level, which is what lets a stored blob be validated
        # and written back without the reserved key getting in the way.
        if key == SCHEMA_VERSION_KEY:
            continue
        if key in properties:
            prop_schema = properties[key]
            cleaned[key] = _validate_value(value, prop_schema, path=(key,))
        elif additional is True:
            cleaned[key] = value
        else:
            raise SchemaValidationError('settings_field_unknown', field=key)

    return cleaned


def _refuse_the_reserved_key(schema: object) -> None:
    """Refuse a schema that declares core's stamp key at any depth.

    Checked over the whole schema, not as the payload walks it: a nested
    object the payload leaves out was never visited, so its declaration was
    accepted — and the value dropped on the first save that carried it, since
    the key is stripped from every level of a payload.
    """
    if not isinstance(schema, dict):
        return
    properties = schema.get('properties')
    if isinstance(properties, dict):
        if SCHEMA_VERSION_KEY in properties:
            raise ContractViolationError(
                f"Property {SCHEMA_VERSION_KEY!r} is reserved for core's "
                'settings schema version stamp'
            )
        for prop_schema in properties.values():
            _refuse_the_reserved_key(prop_schema)
    _refuse_the_reserved_key(schema.get('items'))


def iter_secret_paths(
    schema: dict[str, object],
) -> Iterator[tuple[str, ...]]:
    """Yield the JSON-pointer-style paths of every ``format: secret`` leaf.

    Path is a tuple of segment strings, e.g. ``("jina", "api_key")``.
    Caller (crypto_service) uses this to know which fields to encrypt
    on write and mask on read.
    """
    yield from _walk_secret_paths(schema, prefix=())


def _walk_secret_paths(
    schema: dict[str, object], prefix: tuple[str, ...]
) -> Iterator[tuple[str, ...]]:
    if not isinstance(schema, dict):
        return
    if schema.get('format') == _SECRET_FORMAT_VALUE:
        yield prefix
        return
    if schema.get('type') == 'object':
        properties = schema.get('properties') or {}
        if not isinstance(properties, dict):
            return
        for key, sub_schema in properties.items():
            yield from _walk_secret_paths(sub_schema, prefix + (key,))


def _validate_value(  # noqa: C901 - existing complexity/size
    value: Any, schema: dict[str, object], path: tuple[str, ...]
) -> Any:
    """Check *value* against *schema*; return it cleaned for storage.

    Scalars come back unchanged; a nested object comes back with the same
    rules applied to it as to the root — unknown keys refused or passed
    through, the reserved stamp stripped.
    """
    schema_type = schema.get('type')
    if schema_type is None and 'enum' in schema:
        schema_type = 'enum'
    if schema_type is None:
        return value  # no type constraint — accept anything

    dotted = '.'.join(path)

    if schema_type == 'string':
        if not isinstance(value, str):
            raise SchemaValidationError('settings_value_not_string', path=dotted)
        min_len = schema.get('minLength')
        max_len = schema.get('maxLength')
        if isinstance(min_len, int) and len(value) < min_len:
            raise SchemaValidationError(
                'settings_text_too_short', path=dotted, limit=min_len
            )
        if isinstance(max_len, int) and len(value) > max_len:
            raise SchemaValidationError(
                'settings_text_too_long', path=dotted, limit=max_len
            )
        return value

    if schema_type == 'integer':
        if not isinstance(value, int) or isinstance(value, bool):
            raise SchemaValidationError('settings_value_not_integer', path=dotted)
        _check_min_max(value, schema, path)
        return value

    if schema_type == 'number':
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SchemaValidationError('settings_value_not_number', path=dotted)
        _check_min_max(value, schema, path)
        return value

    if schema_type == 'boolean':
        if not isinstance(value, bool):
            raise SchemaValidationError('settings_value_not_boolean', path=dotted)
        return value

    if schema_type == 'object':
        if not isinstance(value, dict):
            raise SchemaValidationError('settings_value_not_object', path=dotted)
        return validate_payload_against_schema(value, schema)

    if schema_type == 'enum':
        values = schema.get('enum')
        if not isinstance(values, list):
            raise ContractViolationError(f'{dotted} enum must be a list')
        if value not in values:
            raise SchemaValidationError(
                'settings_value_not_allowed',
                path=dotted,
                allowed=', '.join(str(v) for v in values),
                value=value,
            )
        return value

    if schema_type == 'array':
        if not isinstance(value, list):
            raise SchemaValidationError('settings_value_not_array', path=dotted)
        items_schema = schema.get('items')
        if isinstance(items_schema, dict):
            return [
                _validate_value(item, items_schema, path + (str(idx),))
                for idx, item in enumerate(value)
            ]
        return value

    raise ContractViolationError(
        f'{dotted} schema has unsupported type {schema_type!r}'
    )


def _check_min_max(
    value: int | float, schema: dict[str, object], path: tuple[str, ...]
) -> None:
    minimum = schema.get('minimum')
    maximum = schema.get('maximum')
    if isinstance(minimum, (int, float)) and value < minimum:
        raise SchemaValidationError(
            'settings_number_too_small', path='.'.join(path), limit=minimum, value=value
        )
    if isinstance(maximum, (int, float)) and value > maximum:
        raise SchemaValidationError(
            'settings_number_too_large', path='.'.join(path), limit=maximum, value=value
        )
