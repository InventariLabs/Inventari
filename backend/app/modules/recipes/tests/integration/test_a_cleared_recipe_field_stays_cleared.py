"""A cleared recipe field saves as empty — and reads back empty.

The form's four clearable fields (description, instructions, prep time,
tags) used to travel only as `undefined`, so the update's exclude_unset
never saw them and the old values came back after every save. The form
now sends explicit nulls; this pins the server side of that contract:
an explicit null clears the field, a missing key leaves it alone.
"""

from __future__ import annotations

import pytest
from fastapi import status
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration


def _create(client: TestClient, auth_headers: dict[str, str]) -> str:
    created = client.post(
        '/api/v1/recipes',
        headers=auth_headers,
        json={
            'name': 'Clearable recipe',
            'servings': 2,
            'ingredients': [],
            'description': 'Old description',
            'instructions': 'Old steps',
            'prep_time_minutes': 30,
            'tags': ['dinner'],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    recipe_id: str = created.json()['id']
    return recipe_id


def test_an_explicit_null_clears_and_a_missing_key_leaves_alone(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    recipe_id = _create(client, auth_headers)

    touched = client.put(
        f'/api/v1/recipes/{recipe_id}',
        headers=auth_headers,
        json={'servings': 6},
    )
    assert touched.status_code == status.HTTP_200_OK, touched.text
    body = touched.json()
    assert body['description'] == 'Old description'
    assert body['instructions'] == 'Old steps'
    assert body['prep_time_minutes'] == 30
    assert body['tags'] == ['dinner']

    cleared = client.put(
        f'/api/v1/recipes/{recipe_id}',
        headers=auth_headers,
        json={
            'description': None,
            'instructions': None,
            'prep_time_minutes': None,
            'tags': None,
        },
    )
    assert cleared.status_code == status.HTTP_200_OK, cleared.text
    body = cleared.json()
    assert body['description'] is None
    assert body['instructions'] is None
    assert body['prep_time_minutes'] is None
    assert body['tags'] in (None, [])


def test_the_read_after_the_save_stays_empty(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    recipe_id = _create(client, auth_headers)

    client.put(
        f'/api/v1/recipes/{recipe_id}',
        headers=auth_headers,
        json={
            'description': None,
            'instructions': None,
            'prep_time_minutes': None,
            'tags': None,
        },
    )

    read = client.get(f'/api/v1/recipes/{recipe_id}', headers=auth_headers)
    assert read.status_code == status.HTTP_200_OK, read.text
    body = read.json()
    assert body['description'] is None
    assert body['instructions'] is None
    assert body['prep_time_minutes'] is None
    assert body['tags'] in (None, [])
