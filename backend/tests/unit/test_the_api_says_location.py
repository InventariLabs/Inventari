"""The REST API calls a location a location, in its paths and its fields.

Inventory's Storages were relabelled Locations before the first release, and
the core key followed. What a client meets on the wire followed after it:
``/api/v1/storages`` is ``/api/v1/locations``, ``/api/v1/storage-types`` is
``/api/v1/location-types``, and a field that named the entity —
``storage_location_id``, ``storage_id``, ``storage_type``,
``total_storages`` — names it ``location`` now. After a release every one of
those is a promise to an integration, so a path, query parameter or field
added later in the old word would bring the second name back for good.

What may still say storage is what does not name the entity: the tables and
columns underneath (the API reaches them through ORM synonyms), the schema
class names, and ``days_in_storage``, which counts how long goods have been
kept, not where.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

pytestmark = pytest.mark.unit

#: The old word, as a path segment (``storages``, ``storage-types``,
#: ``by-storage``) or inside a name (``storage_id``, ``location_in_storage``).
_FORMER = re.compile(r'storage', re.IGNORECASE)

#: Fields that say storage without naming the location entity.
_NOT_THE_ENTITY = frozenset({'days_in_storage'})


def findings(document: dict[str, Any]) -> list[str]:
    """Every path, parameter and field of *document* that says storage."""
    found: list[str] = []
    for path, operations in document.get('paths', {}).items():
        if _FORMER.search(path):
            found.append(f'path {path}')
        for method, operation in operations.items():
            if not isinstance(operation, dict):
                continue
            for parameter in operation.get('parameters', []):
                if _FORMER.search(parameter['name']):
                    found.append(
                        f'{method.upper()} {path}: parameter {parameter["name"]}'
                    )
    for name, schema in document.get('components', {}).get('schemas', {}).items():
        for field in schema.get('properties') or {}:
            if _FORMER.search(field) and field not in _NOT_THE_ENTITY:
                found.append(f'{name}.{field}')
    return sorted(found)


@pytest.fixture(scope='module')
def document() -> dict[str, Any]:
    from app.main import app

    return app.openapi()


def test_no_path_parameter_or_field_says_storage(document) -> None:
    assert findings(document) == []


def test_the_locations_are_where_the_gate_looks(document) -> None:
    # Not vacuous: the routes and fields the rename moved are in the
    # document under their new names.
    assert '/api/v1/locations/{location_id}' in document['paths']
    assert '/api/v1/location-types' in document['paths']
    item = document['components']['schemas']['Item']['properties']
    assert 'location_id' in item


def test_the_old_word_is_a_finding() -> None:
    assert findings(
        {
            'paths': {
                '/api/v1/storages/{storage_id}': {
                    'get': {'parameters': [{'name': 'storage_id'}]}
                }
            },
            'components': {
                'schemas': {
                    'Row': {
                        'properties': {
                            'storage_type': {},
                            'days_in_storage': {},
                        }
                    }
                }
            },
        }
    ) == [
        'GET /api/v1/storages/{storage_id}: parameter storage_id',
        'Row.storage_type',
        'path /api/v1/storages/{storage_id}',
    ]
