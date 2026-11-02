"""A duplicate unit conversion is refused, not a raw 500.

The unique index holds one row per (organization, ingredient, unit, language).
A second write for the same key used to reach the client as
``Internal Server Error``; the refusals here name the rule instead, so the
person at the screen knows to edit the existing conversion.
"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.testclient import TestClient

RECIPE_URL = '/api/v1/recipes'
CONVERSIONS_URL = f'{RECIPE_URL}/unit-conversions'


def _payload(**overrides: Any) -> dict[str, Any]:
    base = {
        'ingredient_key': 'flour',
        'ingredient_name': 'Flour',
        'source_unit': 'cup',
        'metric_quantity': '120',
        'metric_unit': 'g',
    }
    base.update(overrides)
    return base


@pytest.mark.integration
class TestUnitConversionConflicts:
    def test_create_duplicate_returns_409(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """The organization already holds this ingredient/unit conversion."""
        first = client.post(CONVERSIONS_URL, json=_payload(), headers=auth_headers)
        assert first.status_code == 201

        r = client.post(CONVERSIONS_URL, json=_payload(), headers=auth_headers)
        assert r.status_code == 409
        detail = r.json()['detail']
        assert detail['code'] == 'UNIT_CONVERSION_ALREADY_EXISTS'
        assert 'cup' in detail['message']

    def test_create_duplicate_is_normalised_before_the_check(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Key and unit are lower-cased and stripped, so case cannot dodge it."""
        client.post(
            CONVERSIONS_URL,
            json=_payload(ingredient_key='Flour', source_unit='Cup'),
            headers=auth_headers,
        )
        r = client.post(
            CONVERSIONS_URL,
            json=_payload(ingredient_key='  flour ', source_unit='cup'),
            headers=auth_headers,
        )
        assert r.status_code == 409

    def test_update_onto_another_conversion_returns_409(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Editing a conversion onto a taken (ingredient, unit) is refused."""
        client.post(CONVERSIONS_URL, json=_payload(), headers=auth_headers)
        second_id = client.post(
            CONVERSIONS_URL,
            json=_payload(ingredient_key='sugar', ingredient_name='Sugar'),
            headers=auth_headers,
        ).json()['id']

        r = client.put(
            f'{CONVERSIONS_URL}/{second_id}',
            json={'ingredient_key': 'flour'},
            headers=auth_headers,
        )
        assert r.status_code == 409
        assert r.json()['detail']['code'] == 'UNIT_CONVERSION_ALREADY_EXISTS'
