"""
Unit tests for module settings validation.

The validator is a minimal JSON-Schema subset implementation
(string / integer / number / boolean / enum / object / secret).
External deps are avoided on purpose — the schema surface is tiny.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import ContractViolationError
from app.core.settings_validator import (
    SCHEMA_VERSION_KEY,
    SchemaValidationError,
    settings_schema_version,
    validate_payload_against_schema,
)


def test_rejects_non_dict_payload() -> None:
    with pytest.raises(SchemaValidationError):
        validate_payload_against_schema('not a dict', {'type': 'object'})


def test_rejects_unknown_property_when_additional_properties_false() -> None:
    schema = {
        'type': 'object',
        'properties': {'a': {'type': 'integer'}},
        'additionalProperties': False,
    }
    with pytest.raises(SchemaValidationError) as exc:
        validate_payload_against_schema({'a': 1, 'b': 2}, schema)
    assert 'b' in str(exc.value)


def test_allows_unknown_property_when_additional_properties_true() -> None:
    schema = {
        'type': 'object',
        'properties': {'a': {'type': 'integer'}},
        'additionalProperties': True,
    }
    validate_payload_against_schema({'a': 1, 'b': 'x'}, schema)


def test_validates_integer_with_min_max() -> None:
    schema = {
        'type': 'object',
        'properties': {
            'n': {'type': 'integer', 'minimum': 1, 'maximum': 10},
        },
    }
    validate_payload_against_schema({'n': 5}, schema)
    with pytest.raises(SchemaValidationError):
        validate_payload_against_schema({'n': 0}, schema)
    with pytest.raises(SchemaValidationError):
        validate_payload_against_schema({'n': 11}, schema)


def test_validates_number_with_min_max() -> None:
    schema = {
        'type': 'object',
        'properties': {'x': {'type': 'number', 'minimum': 0.0, 'maximum': 1.0}},
    }
    validate_payload_against_schema({'x': 0.5}, schema)
    with pytest.raises(SchemaValidationError):
        validate_payload_against_schema({'x': 1.5}, schema)


def test_validates_string() -> None:
    schema = {
        'type': 'object',
        'properties': {'name': {'type': 'string', 'minLength': 1}},
    }
    validate_payload_against_schema({'name': 'hello'}, schema)
    with pytest.raises(SchemaValidationError):
        validate_payload_against_schema({'name': ''}, schema)


def test_validates_boolean() -> None:
    schema = {
        'type': 'object',
        'properties': {'enabled': {'type': 'boolean'}},
    }
    validate_payload_against_schema({'enabled': True}, schema)
    with pytest.raises(SchemaValidationError):
        validate_payload_against_schema({'enabled': 'yes'}, schema)


def test_validates_enum() -> None:
    schema = {
        'type': 'object',
        'properties': {'mode': {'enum': ['A', 'B', 'C']}},
    }
    validate_payload_against_schema({'mode': 'A'}, schema)
    with pytest.raises(SchemaValidationError):
        validate_payload_against_schema({'mode': 'D'}, schema)


def test_validates_nested_object() -> None:
    schema = {
        'type': 'object',
        'properties': {
            'jina': {
                'type': 'object',
                'properties': {
                    'api_key': {'type': 'string', 'format': 'secret'},
                },
                'required': ['api_key'],
            },
        },
    }
    validate_payload_against_schema({'jina': {'api_key': 'abc'}}, schema)
    with pytest.raises(SchemaValidationError):
        validate_payload_against_schema({'jina': {}}, schema)


def test_detects_secret_format_in_schema() -> None:
    schema = {
        'type': 'object',
        'properties': {'api_key': {'type': 'string', 'format': 'secret'}},
    }
    fields = _secret_fields_in_schema(schema)
    assert fields == [('api_key',)]


def test_returns_empty_when_no_secret() -> None:
    schema = {
        'type': 'object',
        'properties': {'count': {'type': 'integer'}},
    }
    assert _secret_fields_in_schema(schema) == []


def _secret_fields_in_schema(schema: dict) -> list[tuple[str, ...]]:
    from app.core.settings_validator import iter_secret_paths

    return list(iter_secret_paths(schema))


def test_a_refusal_carries_its_key_and_the_values_it_names() -> None:
    schema = {'type': 'object', 'properties': {'n': {'type': 'integer', 'minimum': 5}}}

    with pytest.raises(SchemaValidationError) as exc:
        validate_payload_against_schema({'n': 1}, schema)

    assert exc.value.key == 'settings_number_too_small'
    assert exc.value.kwargs == {'path': 'n', 'limit': 5, 'value': 1}


def test_a_schema_the_validator_cannot_read_is_the_authors_mistake() -> None:
    schema = {'type': 'object', 'properties': {'x': {'type': 'tuple'}}}

    with pytest.raises(ContractViolationError, match='unsupported type'):
        validate_payload_against_schema({'x': 1}, schema)


@pytest.mark.parametrize(
    ('payload', 'schema', 'key'),
    [
        ('text', {'type': 'object'}, 'settings_payload_not_object'),
        (
            {},
            {
                'type': 'object',
                'properties': {'a': {'type': 'string'}},
                'required': ['a'],
            },
            'settings_field_required',
        ),
        (
            {'a': 1},
            {'properties': {'a': {'type': 'string'}}},
            'settings_value_not_string',
        ),
        (
            {'a': 'x'},
            {'properties': {'a': {'type': 'string', 'minLength': 2}}},
            'settings_text_too_short',
        ),
        (
            {'a': 'xyz'},
            {'properties': {'a': {'type': 'string', 'maxLength': 2}}},
            'settings_text_too_long',
        ),
        (
            {'a': 'x'},
            {'properties': {'a': {'type': 'integer'}}},
            'settings_value_not_integer',
        ),
        (
            {'a': 'x'},
            {'properties': {'a': {'type': 'number'}}},
            'settings_value_not_number',
        ),
        (
            {'a': 'x'},
            {'properties': {'a': {'type': 'boolean'}}},
            'settings_value_not_boolean',
        ),
        (
            {'a': 'x'},
            {'properties': {'a': {'type': 'object'}}},
            'settings_value_not_object',
        ),
        (
            {'a': 'x'},
            {'properties': {'a': {'enum': ['p', 'q']}}},
            'settings_value_not_allowed',
        ),
        (
            {'a': 'x'},
            {'properties': {'a': {'type': 'array'}}},
            'settings_value_not_array',
        ),
        (
            {'a': 9},
            {'properties': {'a': {'type': 'integer', 'maximum': 3}}},
            'settings_number_too_large',
        ),
    ],
)
def test_every_reader_refusal_carries_a_catalogue_key(payload, schema, key) -> None:
    from app.i18n.service import get_error_message

    with pytest.raises(SchemaValidationError) as exc:
        validate_payload_against_schema(payload, schema)

    assert exc.value.key == key
    # The key has a sentence of its own in every language, not the key back.
    for lang in ('de', 'en', 'es', 'fr', 'pl'):
        assert get_error_message(key, lang) != key


@pytest.mark.parametrize(
    ('payload', 'schema', 'fragment'),
    [
        ({}, 'not a schema', 'Schema must be a JSON object'),
        ({}, {'type': 'array'}, 'Root schema type'),
        ({}, {'properties': 'x'}, '"properties" must be an object'),
        ({}, {'required': 'a'}, '"required" must be a list'),
        ({'a': 1}, {'required': ['a']}, 'has no schema entry'),
        (
            {'a': 'x'},
            {'properties': {'a': {'enum': 'pq', 'type': 'enum'}}},
            'enum must be a list',
        ),
    ],
)
def test_every_unreadable_schema_is_the_authors_mistake(
    payload, schema, fragment
) -> None:
    with pytest.raises(ContractViolationError, match=fragment):
        validate_payload_against_schema(payload, schema)


# ---------------------------------------------------------------------------
# Settings schema version — the `version` keyword and the reserved stamp key
# ---------------------------------------------------------------------------


def test_schema_version_defaults_to_one_when_absent() -> None:
    assert settings_schema_version({'type': 'object'}) == 1


def test_schema_version_defaults_to_one_when_schema_is_none() -> None:
    assert settings_schema_version(None) == 1


def test_schema_version_reads_the_declared_version() -> None:
    assert settings_schema_version({'type': 'object', 'version': 3}) == 3


@pytest.mark.parametrize('bad', ['2', True, 0, -1, 2.0])
def test_schema_version_must_be_a_positive_integer(bad) -> None:
    with pytest.raises(ContractViolationError):
        settings_schema_version({'type': 'object', 'version': bad})


def test_a_schema_may_not_declare_the_reserved_stamp_key() -> None:
    schema = {
        'type': 'object',
        'properties': {'__schema_version': {'type': 'integer'}},
    }
    with pytest.raises(ContractViolationError, match='reserved'):
        validate_payload_against_schema({}, schema)


def test_a_nested_schema_may_not_declare_the_reserved_stamp_key() -> None:
    schema = {
        'type': 'object',
        'properties': {
            'inner': {
                'type': 'object',
                'properties': {'__schema_version': {'type': 'integer'}},
            }
        },
    }
    with pytest.raises(ContractViolationError, match='reserved'):
        validate_payload_against_schema({'inner': {}}, schema)


def test_the_stamp_key_in_a_payload_is_ignored_not_refused() -> None:
    schema = {
        'type': 'object',
        'properties': {'a': {'type': 'integer'}},
        'additionalProperties': False,
    }
    cleaned = validate_payload_against_schema({'a': 1, '__schema_version': 7}, schema)
    assert cleaned == {'a': 1}


def test_the_stamp_key_is_ignored_inside_nested_objects_too() -> None:
    schema = {
        'type': 'object',
        'properties': {
            'inner': {
                'type': 'object',
                'properties': {'a': {'type': 'integer'}},
                'additionalProperties': False,
            }
        },
    }
    cleaned = validate_payload_against_schema(
        {'inner': {'a': 1, '__schema_version': 7}}, schema
    )
    assert cleaned == {'inner': {'a': 1}}


def test_the_reserved_key_is_a_stable_contract() -> None:
    assert SCHEMA_VERSION_KEY == '__schema_version'
