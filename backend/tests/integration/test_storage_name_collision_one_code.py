"""One collision, one status code, whichever endpoint noticed it.

``_check_name_unique`` raised one bare ``ValueError`` and three endpoints
each mapped it their own way: create said 400, update said 409, the
hierarchy builder said 400. Same fact about the world, three answers — so a
client wanting to tell "bad name" from "name taken" could not do it by
status and had to read the English sentence, which is the one thing the copy
gate forbids. AGENTS.md §3 settles it: a duplicate is a 409.
"""

import pytest
from fastapi import status

STORAGES = '/api/v1/locations/'
HIERARCHY = '/api/v1/locations/hierarchy'


def _create(client, auth_headers, name: str, **extra):
    return client.post(STORAGES, headers=auth_headers, json={'name': name, **extra})


@pytest.mark.integration
class TestOneCodeForOneCollision:
    def test_create_says_conflict(self, client, auth_headers) -> None:
        first = _create(client, auth_headers, 'Receiving')
        assert first.status_code == status.HTTP_201_CREATED, first.text

        again = _create(client, auth_headers, 'Receiving')
        assert again.status_code == status.HTTP_409_CONFLICT, again.text
        assert again.json()['detail']['code'] == 'STORAGE_CONFLICT'

    def test_update_says_conflict(self, client, auth_headers) -> None:
        _create(client, auth_headers, 'Cold Storage')
        second = _create(client, auth_headers, 'Dry Goods')

        response = client.put(
            f'{STORAGES}{second.json()["id"]}',
            headers=auth_headers,
            json={'name': 'Cold Storage'},
        )
        assert response.status_code == status.HTTP_409_CONFLICT, response.text
        assert response.json()['detail']['code'] == 'STORAGE_CONFLICT'

    def test_the_hierarchy_builder_says_conflict(self, client, auth_headers) -> None:
        payload = {'steps': [{'name': 'Plant'}, {'name': 'Racks'}, {'name': 'Rack 7'}]}
        first = client.post(HIERARCHY, headers=auth_headers, json=payload)
        assert first.status_code == status.HTTP_201_CREATED, first.text

        again = client.post(HIERARCHY, headers=auth_headers, json=payload)
        assert again.status_code == status.HTTP_409_CONFLICT, again.text
        assert again.json()['detail']['code'] == 'STORAGE_CONFLICT'

    def test_a_short_code_collision_carries_its_own_code(
        self, client, auth_headers
    ) -> None:
        """Distinguishable from a name collision without reading either message."""
        first = _create(client, auth_headers, 'First', short_code='LOC-9')
        assert first.status_code == status.HTTP_201_CREATED, first.text

        again = _create(client, auth_headers, 'Second', short_code='LOC-9')
        assert again.status_code == status.HTTP_409_CONFLICT, again.text
        assert again.json()['detail']['code'] == 'STORAGE_SHORT_CODE_CONFLICT'

    def test_invalid_input_is_still_a_validation_error(
        self, client, auth_headers
    ) -> None:
        """The update endpoint used to call every service refusal a conflict."""
        site = _create(client, auth_headers, 'Site A')
        site_id = site.json()['id']

        response = client.put(
            f'{STORAGES}{site_id}',
            headers=auth_headers,
            json={'parent_id': site_id},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.text
