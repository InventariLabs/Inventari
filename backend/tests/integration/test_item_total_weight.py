"""Unit weight is recorded on the product template; the line weight is derived.

See ADR-015. The item no longer carries a weight column, so a save cannot
change one.
"""

from __future__ import annotations

import pytest
from fastapi import status

pytestmark = pytest.mark.integration


@pytest.mark.integration
class TestTotalWeightThroughTheApi:
    def test_unit_weight_lands_on_the_template_and_the_total_is_derived(
        self, client, auth_headers, test_storage_location, db_session
    ):
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Milk 500 g',
                'quantity': 3,
                'weight_value': 500.0,
                'location_id': str(test_storage_location.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        created = response.json()
        # 3 × 500 g = 1.5 kg, computed rather than stored
        assert float(created['weight']) == pytest.approx(1.5)
        assert created['template_id'] is not None

    def test_the_total_says_which_unit_it_is_in(
        self, client, auth_headers, test_storage_location
    ):
        """A reader cannot tell kilograms from litres by looking at a number,
        and a stats table that assumed kilograms mislabelled every drink."""
        created = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Flour 1 kg',
                'quantity': 2,
                'weight_value': 1000.0,
                'location_id': str(test_storage_location.id),
            },
        ).json()

        assert float(created['weight']) == pytest.approx(2.0)
        assert created['weight_unit'] == 'kg'

    def test_an_item_with_no_weight_names_no_unit(
        self, client, auth_headers, test_storage_location
    ):
        created = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Loose screws',
                'quantity': 5,
                'location_id': str(test_storage_location.id),
            },
        ).json()

        assert created['weight'] is None
        assert created['weight_unit'] is None

    def test_saving_an_item_untouched_leaves_its_weight_alone(
        self, client, auth_headers, test_storage_location
    ):
        """The regression this replaced multiplied the weight on every save."""
        created = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Butter 200 g',
                'quantity': 2,
                'weight_value': 200.0,
                'location_id': str(test_storage_location.id),
            },
        ).json()

        item_id = created['id']
        first = float(created['weight'])

        for _ in range(2):
            response = client.put(
                f'/api/v1/items/{item_id}',
                headers=auth_headers,
                json={'name': 'Butter 200 g'},
            )
            assert response.status_code == status.HTTP_200_OK
            assert float(response.json()['weight']) == pytest.approx(first)

    def test_changing_the_quantity_rescales_the_total(
        self, client, auth_headers, test_storage_location
    ):
        created = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Flour 1000 g',
                'quantity': 1,
                'weight_value': 1000.0,
                'location_id': str(test_storage_location.id),
            },
        ).json()

        response = client.put(
            f'/api/v1/items/{created["id"]}',
            headers=auth_headers,
            json={'quantity': 4},
        )

        assert response.status_code == status.HTTP_200_OK
        assert float(response.json()['weight']) == pytest.approx(4.0)

    def test_an_item_without_a_unit_weight_has_no_total(
        self, client, auth_headers, test_storage_location
    ):
        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Screwdriver',
                'quantity': 2,
                'location_id': str(test_storage_location.id),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['weight'] is None
