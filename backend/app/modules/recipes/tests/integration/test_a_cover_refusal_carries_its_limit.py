"""A cover refusal for size carries the number, not the placeholder.

``image_too_large`` is a shared, parameterized key — the sentence reads
"(max {limit})" until a caller hands it the number. The recipes cover
upload asked for the message without one, so an oversized picture came
back as "(max {limit})", in every language, on an endpoint whose limit
had not moved: five megabytes, said in words on dev and in braces after
the key was parameterized for the other three doors.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from starlette.testclient import TestClient

RECIPE_URL = '/api/v1/recipes'


def _payload(**overrides: Any) -> dict[str, Any]:
    base = {
        'name': 'Pizza Margherita',
        'description': 'Klasyczna pizza',
        'servings': 2,
        'prep_time_minutes': 30,
        'tags': [],
        'is_favorite': False,
        'ingredients': [],
    }
    base.update(overrides)
    return base


@pytest.mark.integration
class TestACoverRefusalCarriesItsLimit:
    def test_an_oversized_cover_names_ten_megabytes(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        created = client.post(RECIPE_URL, json=_payload(), headers=auth_headers)
        recipe_id = created.json()['id']

        response = client.post(
            f'{RECIPE_URL}/{recipe_id}/image',
            headers=auth_headers,
            files={
                'image': (
                    'big.png',
                    b'\x89PNG\r\n\x1a\n' + b'\0' * (10 * 1024 * 1024 + 1),
                    'image/png',
                )
            },
        )

        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        # The shape the other image doors use: a client reads the code, a
        # person reads the message. This door answered with the bare sentence
        # and nothing to match on, while vision, logo and item images all
        # carried FILE_TOO_LARGE.
        detail = response.json()['detail']
        assert detail['code'] == 'FILE_TOO_LARGE', detail
        assert '{limit}' not in detail['message'], detail
        assert '10 MB' in detail['message'], detail

    def test_a_cover_of_the_wrong_type_carries_a_code_too(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        # Same door, same shape: the refusal a client can recognise without
        # matching on the sentence.
        created = client.post(RECIPE_URL, json=_payload(), headers=auth_headers)
        recipe_id = created.json()['id']

        response = client.post(
            f'{RECIPE_URL}/{recipe_id}/image',
            headers=auth_headers,
            files={'image': ('note.txt', b'not an image', 'text/plain')},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        detail = response.json()['detail']
        assert detail['code'] == 'ONLY_IMAGE_FILES_ALLOWED', detail
        assert detail['message'].strip(), detail

    def test_a_cover_inside_the_limit_still_goes_through(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        from io import BytesIO

        from PIL import Image

        created = client.post(RECIPE_URL, json=_payload(), headers=auth_headers)
        recipe_id = created.json()['id']

        buffer = BytesIO()
        Image.new('RGB', (8, 6), (120, 20, 20)).save(buffer, format='PNG')

        response = client.post(
            f'{RECIPE_URL}/{recipe_id}/image',
            headers=auth_headers,
            files={'image': ('ok.png', buffer.getvalue(), 'image/png')},
        )

        assert response.status_code == status.HTTP_200_OK, response.text
