"""A model's category is stored, or it is not offered.

The edit dialog offered a category, the API answered 200 with the category
in the body, and nothing wrote it: twenty-six models, none with a category,
no refusal anywhere. ``ProductTemplate`` is a Core table with no category
column, so the module keeps its own answer in its own corner of
``meta_data`` — and the response is read back from what was stored rather
than echoed from the request, which is what made the loss invisible.
"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.testclient import TestClient

from app.models.category import Category

MODELS_URL = '/api/v1/equipment/models'


def _create(
    client: TestClient, headers: dict[str, str], **extra: object
) -> dict[str, Any]:
    response = client.post(
        MODELS_URL,
        headers=headers,
        json={'name': 'Dell Latitude 5540', 'brand': 'Dell', **extra},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


@pytest.mark.integration
class TestTheModelStoresTheCategoryItConfirms:
    def test_the_category_comes_back_from_the_list(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_category: Category,
    ) -> None:
        created = _create(client, eq_auth_headers, category_id=str(eq_category.id))
        assert created['category_id'] == str(eq_category.id)

        listed = client.get(MODELS_URL, headers=eq_auth_headers)
        assert listed.status_code == 200, listed.text
        row = next(r for r in listed.json()['items'] if r['id'] == created['id'])
        assert row['category_id'] == str(eq_category.id)
        assert row['category_name'] == eq_category.name

    def test_an_edit_that_only_sets_the_category_stores_it(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_category: Category,
    ) -> None:
        """The measured walk: open a model with no category, pick one, save."""
        created = _create(client, eq_auth_headers)
        assert created['category_id'] is None

        response = client.put(
            f'{MODELS_URL}/{created["id"]}',
            headers=eq_auth_headers,
            json={'category_id': str(eq_category.id)},
        )
        assert response.status_code == 200, response.text
        assert response.json()['category_id'] == str(eq_category.id)

        listed = client.get(MODELS_URL, headers=eq_auth_headers)
        row = next(r for r in listed.json()['items'] if r['id'] == created['id'])
        assert row['category_id'] == str(eq_category.id)

    def test_clearing_the_category_clears_it(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_category: Category,
    ) -> None:
        created = _create(client, eq_auth_headers, category_id=str(eq_category.id))

        response = client.put(
            f'{MODELS_URL}/{created["id"]}',
            headers=eq_auth_headers,
            json={'category_id': None},
        )
        assert response.status_code == 200, response.text
        assert response.json()['category_id'] is None

        listed = client.get(MODELS_URL, headers=eq_auth_headers)
        row = next(r for r in listed.json()['items'] if r['id'] == created['id'])
        assert row['category_id'] is None

    def test_the_rest_of_the_module_metadata_survives_a_category_edit(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_category: Category,
    ) -> None:
        created = _create(
            client, eq_auth_headers, equipment_meta={'warranty_months': 36}
        )

        client.put(
            f'{MODELS_URL}/{created["id"]}',
            headers=eq_auth_headers,
            json={'category_id': str(eq_category.id)},
        )

        listed = client.get(MODELS_URL, headers=eq_auth_headers)
        row = next(r for r in listed.json()['items'] if r['id'] == created['id'])
        assert row['equipment_meta']['warranty_months'] == 36
        assert row['category_id'] == str(eq_category.id)
