"""Replacing a recipe's cover changes the address the screens load.

The hero card, the cards in lists and the meal plan all load the cover by its
address; with a fixed ``cover.<ext>`` a replaced picture kept the address of
the old one and the page kept showing the old pixels until a reload.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image
from starlette.testclient import TestClient

RECIPE_URL = '/api/v1/recipes'


def _png(colour: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), colour).save(buffer, 'PNG')
    return buffer.getvalue()


def _recipe(client: TestClient, headers: dict[str, str]) -> str:
    r = client.post(
        RECIPE_URL,
        json={
            'name': 'Pizza',
            'description': '',
            'servings': 2,
            'prep_time_minutes': 10,
            'tags': [],
            'is_favorite': False,
            'ingredients': [],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return str(r.json()['id'])


def _upload(
    client: TestClient,
    headers: dict[str, str],
    recipe_id: str,
    colour: tuple[int, int, int],
) -> str:
    r = client.post(
        f'{RECIPE_URL}/{recipe_id}/image',
        files={'image': ('c.png', io.BytesIO(_png(colour)), 'image/png')},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return str(r.json()['image_url'])


@pytest.mark.integration
class TestAReplacedRecipeCoverIsANewAddress:
    def test_a_different_picture_is_served_from_a_different_address(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        recipe_id = _recipe(client, auth_headers)
        first = _upload(client, auth_headers, recipe_id, (255, 0, 0))
        second = _upload(client, auth_headers, recipe_id, (0, 0, 255))

        assert first != second
        assert client.get(second, headers=auth_headers).status_code == 200
        assert client.get(first, headers=auth_headers).status_code == 404
        shown = client.get(f'{RECIPE_URL}/{recipe_id}', headers=auth_headers)
        assert shown.json()['image_url'] == second

    def test_removing_the_cover_removes_the_file_the_row_names(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        recipe_id = _recipe(client, auth_headers)
        url = _upload(client, auth_headers, recipe_id, (1, 2, 3))

        gone = client.delete(f'{RECIPE_URL}/{recipe_id}/image', headers=auth_headers)

        assert gone.status_code == 204, gone.text
        assert client.get(url, headers=auth_headers).status_code == 404
