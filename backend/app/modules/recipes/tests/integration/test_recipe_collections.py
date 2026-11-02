"""Integration tests for recipe collections."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from starlette.testclient import TestClient

RECIPE_URL = '/api/v1/recipes'


def _recipe_payload(**overrides: Any) -> dict[str, Any]:
    base = {
        'name': 'Collection Test Recipe',
        'servings': 2,
        'ingredients': [],
    }
    base.update(overrides)
    return base


@pytest.mark.integration
class TestRecipeCollections:
    def test_create_collection_success(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        r = client.post(
            f'{RECIPE_URL}/collections',
            json={'name': 'Weekend Dinners', 'icon': '🍝'},
            headers=auth_headers,
        )
        assert r.status_code == 201
        data = r.json()
        assert data['name'] == 'Weekend Dinners'
        assert data['icon'] == '🍝'
        assert data['parent_id'] is None
        assert 'id' in data

    def test_create_duplicate_name_returns_409(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """An occupied name is refused with a sentence, not a bare 500."""
        first = client.post(
            f'{RECIPE_URL}/collections',
            json={'name': 'Weekend Dinners'},
            headers=auth_headers,
        )
        assert first.status_code == 201

        r = client.post(
            f'{RECIPE_URL}/collections',
            json={'name': 'Weekend Dinners'},
            headers=auth_headers,
        )
        assert r.status_code == 409
        detail = r.json()['detail']
        assert detail['code'] == 'RECIPE_COLLECTION_NAME_TAKEN'
        assert 'Weekend Dinners' in detail['message']

    def test_create_duplicate_name_after_trim_returns_409(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Whitespace is stripped before the insert, so it cannot dodge the name."""
        client.post(
            f'{RECIPE_URL}/collections',
            json={'name': 'Trimmed'},
            headers=auth_headers,
        )
        r = client.post(
            f'{RECIPE_URL}/collections',
            json={'name': '  Trimmed  '},
            headers=auth_headers,
        )
        assert r.status_code == 409

    def test_update_to_taken_name_returns_409(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Renaming onto a sibling's name is refused; keeping one's own is not."""
        client.post(
            f'{RECIPE_URL}/collections',
            json={'name': 'Alpha'},
            headers=auth_headers,
        )
        beta_id = client.post(
            f'{RECIPE_URL}/collections',
            json={'name': 'Beta'},
            headers=auth_headers,
        ).json()['id']

        r = client.put(
            f'{RECIPE_URL}/collections/{beta_id}',
            json={'name': 'Alpha'},
            headers=auth_headers,
        )
        assert r.status_code == 409
        assert r.json()['detail']['code'] == 'RECIPE_COLLECTION_NAME_TAKEN'

        # Its own name is not a collision.
        r2 = client.put(
            f'{RECIPE_URL}/collections/{beta_id}',
            json={'name': 'Beta'},
            headers=auth_headers,
        )
        assert r2.status_code == 200
        assert r2.json()['name'] == 'Beta'

    def test_create_nested_collection_and_tree(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        parent_id = client.post(
            f'{RECIPE_URL}/collections',
            json={'name': 'Parent'},
            headers=auth_headers,
        ).json()['id']
        client.post(
            f'{RECIPE_URL}/collections',
            json={'name': 'Child', 'parent_id': parent_id},
            headers=auth_headers,
        )
        client.post(
            f'{RECIPE_URL}/collections',
            json={'name': 'Sibling'},
            headers=auth_headers,
        )

        r = client.get(f'{RECIPE_URL}/collections', headers=auth_headers)
        assert r.status_code == 200
        tree = r.json()['items']
        root = next(c for c in tree if c['name'] == 'Parent')
        assert len(root['children']) == 1
        assert root['children'][0]['name'] == 'Child'
        assert any(c['name'] == 'Sibling' for c in tree)

    def test_add_remove_recipe_and_filter(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        collection_id = client.post(
            f'{RECIPE_URL}/collections',
            json={'name': 'Favorites'},
            headers=auth_headers,
        ).json()['id']
        recipe_id = client.post(
            RECIPE_URL,
            json=_recipe_payload(name='In collection'),
            headers=auth_headers,
        ).json()['id']
        other_id = client.post(
            RECIPE_URL,
            json=_recipe_payload(name='Not in collection'),
            headers=auth_headers,
        ).json()['id']

        # Add
        r = client.post(
            f'{RECIPE_URL}/collections/{collection_id}/recipes',
            json={'recipe_id': recipe_id},
            headers=auth_headers,
        )
        assert r.status_code == 201
        assert r.json()['recipe_id'] == recipe_id

        # Filter by collection
        r2 = client.get(
            f'{RECIPE_URL}?collection_id={collection_id}',
            headers=auth_headers,
        )
        assert r2.status_code == 200
        names = [item['name'] for item in r2.json()['items']]
        assert 'In collection' in names
        assert 'Not in collection' not in names

        # Collection count reflects membership
        r3 = client.get(f'{RECIPE_URL}/collections', headers=auth_headers)
        fav = next(c for c in r3.json()['items'] if c['id'] == collection_id)
        assert fav['recipe_count'] == 1

        # Idempotent re-add
        r4 = client.post(
            f'{RECIPE_URL}/collections/{collection_id}/recipes',
            json={'recipe_id': recipe_id},
            headers=auth_headers,
        )
        assert r4.status_code == 201

        # Remove
        r5 = client.delete(
            f'{RECIPE_URL}/collections/{collection_id}/recipes/{recipe_id}',
            headers=auth_headers,
        )
        assert r5.status_code == 204
        r6 = client.get(
            f'{RECIPE_URL}?collection_id={collection_id}',
            headers=auth_headers,
        )
        assert r6.status_code == 200
        assert r6.json()['items'] == []

        # Remove again → 404
        r7 = client.delete(
            f'{RECIPE_URL}/collections/{collection_id}/recipes/{recipe_id}',
            headers=auth_headers,
        )
        assert r7.status_code == 404

        # Other recipe still exists
        r8 = client.get(f'{RECIPE_URL}/{other_id}', headers=auth_headers)
        assert r8.status_code == 200

    def test_add_recipe_unknown_collection_returns_400(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        recipe_id = client.post(
            RECIPE_URL, json=_recipe_payload(), headers=auth_headers
        ).json()['id']
        r = client.post(
            f'{RECIPE_URL}/collections/{uuid.uuid4()}/recipes',
            json={'recipe_id': recipe_id},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_collection_cannot_be_own_parent(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        collection_id = client.post(
            f'{RECIPE_URL}/collections',
            json={'name': 'Solo'},
            headers=auth_headers,
        ).json()['id']
        r = client.put(
            f'{RECIPE_URL}/collections/{collection_id}',
            json={'parent_id': collection_id},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_collection_cycle_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        parent_id = client.post(
            f'{RECIPE_URL}/collections',
            json={'name': 'Cycle Parent'},
            headers=auth_headers,
        ).json()['id']
        child_id = client.post(
            f'{RECIPE_URL}/collections',
            json={'name': 'Cycle Child', 'parent_id': parent_id},
            headers=auth_headers,
        ).json()['id']
        # Moving parent under child would create a cycle
        r = client.put(
            f'{RECIPE_URL}/collections/{parent_id}',
            json={'parent_id': child_id},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_delete_collection_cascades(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        collection_id = client.post(
            f'{RECIPE_URL}/collections',
            json={'name': 'Doomed'},
            headers=auth_headers,
        ).json()['id']
        recipe_id = client.post(
            RECIPE_URL, json=_recipe_payload(), headers=auth_headers
        ).json()['id']
        client.post(
            f'{RECIPE_URL}/collections/{collection_id}/recipes',
            json={'recipe_id': recipe_id},
            headers=auth_headers,
        )

        r = client.delete(
            f'{RECIPE_URL}/collections/{collection_id}', headers=auth_headers
        )
        assert r.status_code == 204
        # Collection gone; recipe survives
        r2 = client.get(f'{RECIPE_URL}/collections', headers=auth_headers)
        assert all(c['id'] != collection_id for c in r2.json()['items'])
        r3 = client.get(f'{RECIPE_URL}/{recipe_id}', headers=auth_headers)
        assert r3.status_code == 200
