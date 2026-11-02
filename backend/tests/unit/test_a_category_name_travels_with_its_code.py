"""A category's name never leaves the API without its code.

The reader's language names a seeded category through its code; the name on
the record is the seed's English fallback. A response that carries the name
alone leaves the screen nothing to translate with, and it prints "Deli" one
tab away from "Cold cuts". Three stats rows once gained a ``category_code``
field that nothing filled — so this gate reads the published contract, and
the integration tests in ``app/modules/stats/tests`` check that the field is
actually filled.

The rule, over every schema in the OpenAPI document:

- a string property ``category_name`` or ``category`` has a ``category_code``
  sibling;
- an object property ``category`` refers to a schema that has a ``code``.

A property that is not an item category at all — a unit's dimension, an app
store shelf — is listed below with the reason.
"""

from __future__ import annotations

from typing import Any

import pytest

#: ``Schema.property`` -> why it is not a category name without its code.
NOT_A_CATEGORY_RECORD: dict[str, str] = {
    'ModuleInfo.category': "an app-store module's shelf, not an item category",
    'UnitConversionCreate.category': 'a unit-conversion group, not an item category',
    'UnitConversionSchema.category': 'a unit-conversion group, not an item category',
    'UnitConversionUpdate.category': 'a unit-conversion group, not an item category',
    'UomInfoWithCategory.category_name': "a unit's dimension (weight, volume)",
    'VisionExtractResponse.category': (
        "the vision model's own free-text guess, matched against the "
        'categories rather than naming one of them'
    ),
    'PutawayRuleOut.category_name': (
        'a snapshot for a category since deleted; the rules screen resolves '
        'the live category by category_id and names it through its code'
    ),
    # Equipment keeps a separate category universe with its own resolver on
    # the screen; the resolution this gate guards is not applied there yet.
    'ByCategory.category_name': "equipment's categories, a separate dataset",
    'EquipmentModelSchema.category_name': "equipment's categories, a separate dataset",
}


def _is_string(prop: dict[str, Any]) -> bool:
    if prop.get('type') == 'string':
        return True
    return any(v.get('type') == 'string' for v in prop.get('anyOf', []))


def _refs(prop: dict[str, Any]) -> list[str]:
    candidates = [prop, *prop.get('anyOf', []), *prop.get('allOf', [])]
    return [c['$ref'].rsplit('/', 1)[-1] for c in candidates if '$ref' in c]


def findings(schemas: dict[str, dict[str, Any]]) -> list[str]:
    """Every property that names a category and cannot hand over its code."""
    found: list[str] = []
    for name, schema in sorted(schemas.items()):
        props = schema.get('properties', {})
        for prop_name in ('category_name', 'category'):
            prop = props.get(prop_name)
            key = f'{name}.{prop_name}'
            if prop is None or key in NOT_A_CATEGORY_RECORD:
                continue
            if _is_string(prop) and 'category_code' not in props:
                found.append(f'{key}: a name with no category_code beside it')
            for ref in _refs(prop):
                if 'code' not in schemas.get(ref, {}).get('properties', {}):
                    found.append(f'{key}: refers to {ref}, which has no code')
    return found


@pytest.fixture(scope='module')
def schemas() -> dict[str, dict[str, Any]]:
    from app.main import app

    return app.openapi()['components']['schemas']


@pytest.mark.unit
class TestACategoryNameTravelsWithItsCode:
    def test_every_category_name_in_the_api_has_its_code(self, schemas) -> None:
        assert findings(schemas) == []

    def test_the_scan_reads_the_rows_it_exists_for(self, schemas) -> None:
        # Not vacuous: the stats rows this gate was written over are in the
        # document, and they do carry a name.
        for name in ('CategoryRotation', 'CategoryCostItem', 'SavingsOpportunity'):
            assert 'category_name' in schemas[name]['properties']

    def test_a_name_without_its_code_is_a_finding(self) -> None:
        assert findings(
            {
                'Row': {
                    'properties': {
                        'category_name': {'type': 'string'},
                        'total': {'type': 'number'},
                    }
                }
            }
        ) == ['Row.category_name: a name with no category_code beside it']

    def test_a_nested_category_without_a_code_is_a_finding(self) -> None:
        assert findings(
            {
                'Brief': {'properties': {'id': {}, 'name': {'type': 'string'}}},
                'Archived': {
                    'properties': {
                        'category': {
                            'anyOf': [
                                {'$ref': '#/components/schemas/Brief'},
                                {'type': 'null'},
                            ]
                        }
                    }
                },
            }
        ) == ['Archived.category: refers to Brief, which has no code']

    def test_every_exemption_still_names_a_real_property(self, schemas) -> None:
        # An exemption outliving its property would wave the next one through.
        stale = [
            key
            for key in NOT_A_CATEGORY_RECORD
            if key.split('.')[1]
            not in schemas.get(key.split('.')[0], {}).get('properties', {})
        ]
        assert stale == []
