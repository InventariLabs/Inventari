"""Integration tests for naming an existing step on POST /locations/hierarchy.

The endpoint's contract is "resolve or create each step". By id it resolved;
by name it only ever created, and every ValueError the service raised was
turned into a 404. So somebody furnishing a warehouse who added a second shelf
under a rack they had just named was told the location did not exist -- while
the service was saying the name was taken.
"""

import pytest
from fastapi import status

HIERARCHY = '/api/v1/locations/hierarchy'


@pytest.mark.integration
class TestHierarchyByName:
    """Naming a step that exists means that one."""

    def test_second_leaf_under_the_same_named_path_succeeds(self, client, auth_headers):
        first = client.post(
            HIERARCHY,
            headers=auth_headers,
            json={
                'steps': [
                    {'name': 'Warehouse'},
                    {'name': 'Cold Storage'},
                    {'name': 'Shelf A'},
                ],
            },
        )
        assert first.status_code == status.HTTP_201_CREATED

        second = client.post(
            HIERARCHY,
            headers=auth_headers,
            json={
                'steps': [
                    {'name': 'Warehouse'},
                    {'name': 'Cold Storage'},
                    {'name': 'Shelf B'},
                ],
            },
        )

        assert second.status_code == status.HTTP_201_CREATED
        assert second.json()['name'] == 'Shelf B'

    def test_the_second_leaf_hangs_under_the_same_parent(self, client, auth_headers):
        first = client.post(
            HIERARCHY,
            headers=auth_headers,
            json={
                'steps': [
                    {'name': 'Depot'},
                    {'name': 'Receiving'},
                    {'name': 'Bay 1'},
                ],
            },
        )
        second = client.post(
            HIERARCHY,
            headers=auth_headers,
            json={
                'steps': [
                    {'name': 'Depot'},
                    {'name': 'Receiving'},
                    {'name': 'Bay 2'},
                ],
            },
        )

        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_201_CREATED
        # One parent, not two carrying the same name.
        assert first.json()['parent_id'] == second.json()['parent_id']

    def test_naming_the_same_location_twice_is_a_business_error_not_a_404(
        self, client, auth_headers
    ):
        client.post(
            HIERARCHY,
            headers=auth_headers,
            json={
                'steps': [
                    {'name': 'Plant'},
                    {'name': 'Dry Goods'},
                    {'name': 'Rack 1'},
                ],
            },
        )

        again = client.post(
            HIERARCHY,
            headers=auth_headers,
            json={
                'steps': [
                    {'name': 'Plant'},
                    {'name': 'Dry Goods'},
                    {'name': 'Rack 1'},
                ],
            },
        )

        assert again.status_code == status.HTTP_409_CONFLICT
        # The reason has to be the collision, not an invented missing record.
        assert 'Rack 1' in again.text
        assert 'STORAGE_NOT_FOUND' not in again.text

    def test_a_parent_id_that_does_not_exist_is_still_a_404(self, client, auth_headers):
        missing = '00000000-0000-0000-0000-000000000000'

        response = client.post(
            HIERARCHY,
            headers=auth_headers,
            json={'parent_id': missing, 'steps': [{'name': 'Orphan Shelf'}]},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_a_step_id_that_does_not_exist_is_still_a_404(self, client, auth_headers):
        missing = '00000000-0000-0000-0000-000000000000'

        response = client.post(
            HIERARCHY,
            headers=auth_headers,
            json={'steps': [{'id': missing}, {'name': 'Orphan Shelf'}]},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_reusing_a_named_parent_with_a_new_child(self, client, auth_headers):
        first = client.post(
            HIERARCHY,
            headers=auth_headers,
            json={
                'steps': [
                    {'name': 'Campus'},
                    {'name': 'Building A'},
                    {'name': 'Room 1'},
                ],
            },
        )
        second = client.post(
            HIERARCHY,
            headers=auth_headers,
            json={
                'steps': [
                    {'name': 'Campus'},
                    {'name': 'Building B'},
                    {'name': 'Room 2'},
                ],
            },
        )

        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_201_CREATED
        # Different children under one parent, so the parents differ.
        assert first.json()['parent_id'] != second.json()['parent_id']

    def test_a_chain_of_five_resolves_every_step_by_name(self, client, auth_headers):
        """The old ceiling was three; a named path of five has to walk.

        Resolving only the shallow names would create a second root or hang
        the fifth step on the wrong parent. The full path spells the chain
        out where the parent id alone names only its last link.
        """
        first = client.post(
            HIERARCHY,
            headers=auth_headers,
            json={
                'steps': [
                    {'name': 'Harbor'},
                    {'name': 'Shed 1'},
                    {'name': 'Rack 2'},
                    {'name': 'Bin 3'},
                    {'name': 'Tray 4'},
                ],
            },
        )
        assert first.status_code == status.HTTP_201_CREATED

        second = client.post(
            HIERARCHY,
            headers=auth_headers,
            json={
                'steps': [
                    {'name': 'Harbor'},
                    {'name': 'Shed 1'},
                    {'name': 'Rack 2'},
                    {'name': 'Bin 3'},
                    {'name': 'Tray 5'},
                ],
            },
        )
        assert second.status_code == status.HTTP_201_CREATED

        listed = client.get('/api/v1/locations', headers=auth_headers).json()['items']
        by_name = {row['name']: row for row in listed}
        assert by_name['Tray 5']['full_path'] == (
            'Harbor › Shed 1 › Rack 2 › Bin 3 › Tray 5'
        )
        assert by_name['Tray 4']['parent_id'] == by_name['Tray 5']['parent_id']
