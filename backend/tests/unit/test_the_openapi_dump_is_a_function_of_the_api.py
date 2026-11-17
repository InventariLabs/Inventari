"""The OpenAPI dump is a function of the API alone.

`docs/api/openapi.json` is a maintained artifact guarded by `make
check-openapi-fresh`, which dumps the live schema through
`scripts/dump_openapi.py` and refuses drift. The dump is canonicalised —
`paths` and `components.schemas` sorted by key — so that router
registration order cannot make two hosts serving the *identical* API
produce byte-different files and fail the gate on a diff nobody can act
on. The TS-types pipeline canonicalises for the same reason; the shared
wisdom lives in `frontend/scripts/generate-api-types.sh`.

These tests pin the canonical half: the two maps are sorted, everything
else keeps the order the code declared it in, and a schema too small to
carry the optional parts survives untouched. The other half is the
library's own wording: pydantic 2.13 describes a `Decimal` string with a
regular expression and 2.14 does not, so the dump leaves that expression
out rather than depend on which one the container happens to run.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'dump_openapi.py'


def _load_script():
    spec = importlib.util.spec_from_file_location('dump_openapi', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schema() -> dict:
    return {
        'openapi': '3.1.0',
        'info': {'title': 'Inventari', 'version': '0.1.0'},
        'paths': {
            '/api/v1/items': {'get': {'summary': 'list'}},
            '/api/v1/auth/login': {'post': {'summary': 'login'}},
        },
        'components': {
            'schemas': {
                'ItemRead': {'type': 'object'},
                'ItemCreate': {'type': 'object'},
            },
            'securitySchemes': {
                'OAuth2': {'type': 'oauth2'},
                'ApiKey': {'type': 'apiKey'},
            },
        },
    }


def test_paths_are_sorted_by_key() -> None:
    canonical = _load_script().canonical

    result = canonical(_schema())

    assert list(result['paths']) == ['/api/v1/auth/login', '/api/v1/items']


def test_component_schemas_are_sorted_by_key() -> None:
    canonical = _load_script().canonical

    result = canonical(_schema())

    assert list(result['components']['schemas']) == ['ItemCreate', 'ItemRead']


def test_every_other_key_keeps_its_declared_order() -> None:
    """Only the two registration-order maps are touched.

    `securitySchemes` is a components map too, but its order is declared
    once at app setup, not discovered per module — sorting it would be
    noise, so the canonical form leaves it alone.
    """
    canonical = _load_script().canonical

    result = canonical(_schema())

    assert list(result['components']['securitySchemes']) == ['OAuth2', 'ApiKey']
    assert list(result['info']) == ['title', 'version']
    assert result['paths']['/api/v1/items']['get']['summary'] == 'list'


def test_a_schema_without_components_survives() -> None:
    canonical = _load_script().canonical
    schema = {'openapi': '3.1.0', 'paths': {'/b': {}, '/a': {}}}

    result = canonical(schema)

    assert list(result['paths']) == ['/a', '/b']
    assert 'components' not in result


def test_canonicalising_twice_is_a_fixed_point() -> None:
    """The generator and the gate share the dump: re-running must not move.

    A gate whose canonical form is not idempotent could keep failing on an
    already-regenerated file, and regenerating would oscillate between two
    shapes forever.
    """
    canonical = _load_script().canonical

    once = canonical(_schema())
    twice = canonical(_schema())

    assert once == twice


_DECIMAL_PATTERN = r'^(?!^[-+.]*$)[+-]?0*\d*\.?\d*$'
_BOUNDED_DECIMAL_PATTERN = (
    r'^(?!^[-+.]*$)[+-]?0*(?:\d{0,9}|(?=[\d.]{1,13}0*$)\d{0,9}\.\d{0,3}0*$)'
)


def test_a_decimal_pattern_is_left_out_wherever_it_sits() -> None:
    """Which pydantic the container runs must not decide the artifact.

    2.13 emits the Decimal regular expression, 2.14 does not; a committed
    file carrying it fails the freshness gate on every stack synced to the
    lock, and one without it fails on every older image. Dropping it, both
    as a union member and as a plain string, makes the two agree.
    """
    canonical = _load_script().canonical
    schema = _schema()
    schema['components']['schemas']['ItemRead'] = {
        'type': 'object',
        'properties': {
            'price': {'type': 'string', 'pattern': _DECIMAL_PATTERN},
            'qty': {
                'anyOf': [
                    {'type': 'number', 'exclusiveMinimum': 0.0},
                    {'type': 'string', 'pattern': _BOUNDED_DECIMAL_PATTERN},
                ]
            },
        },
    }

    result = canonical(schema)

    props = result['components']['schemas']['ItemRead']['properties']
    assert props['price'] == {'type': 'string'}
    assert props['qty']['anyOf'][1] == {'type': 'string'}
    assert props['qty']['anyOf'][0] == {'type': 'number', 'exclusiveMinimum': 0.0}


def test_a_pattern_the_api_declared_is_kept() -> None:
    canonical = _load_script().canonical
    schema = _schema()
    schema['paths']['/api/v1/items']['get']['parameters'] = [
        {'schema': {'type': 'string', 'pattern': '^(asc|desc)$'}}
    ]

    result = canonical(schema)

    kept = result['paths']['/api/v1/items']['get']['parameters'][0]['schema']
    assert kept['pattern'] == '^(asc|desc)$'
