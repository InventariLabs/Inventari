"""What a location is for is the system's business, not the caller's.

``usage`` decides whether a location counts towards stock. The API used to
take it on create, on update and through the hierarchy builder, and the edit
sheet offered the seven Odoo-style values as a picker — so flipping a shelf
of twelve products to "Scrap" removed them from stock, reports, purchase
suggestions and scan lookup, removed the shelf from the tree it was reached
from, and wrote nothing anywhere. These tests pin the door shut on both
sides: the picker is gone from the app, and the API refuses the change.
"""

import pytest
from fastapi import status


@pytest.mark.integration
class TestStorageUsage:
    """Usage on the storage endpoints — assigned, never accepted."""

    def test_create_ignores_a_usage_it_was_handed(self, client, auth_headers):
        """A caller can ask for a virtual location; it gets a real one."""
        response = client.post(
            '/api/v1/locations',
            headers=auth_headers,
            json={'name': 'Receiving Dock', 'usage': 'customer'},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['usage'] == 'internal'

    def test_hierarchy_creates_a_real_place(self, client, auth_headers):
        response = client.post(
            '/api/v1/locations/hierarchy',
            headers=auth_headers,
            json={
                'steps': [
                    {'name': 'Usage Site'},
                    {'name': 'Usage Zone'},
                    {'name': 'In Transit'},
                ],
                'usage': 'inventory',
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['usage'] == 'internal'

    def test_update_refuses_to_change_it(
        self, client, auth_headers, db_session, test_user
    ):
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            name='Scrap Bin',
            usage='internal',
        )
        db_session.add(storage)
        db_session.commit()

        response = client.put(
            f'/api/v1/locations/{storage.id}',
            headers=auth_headers,
            json={'usage': 'customer'},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()['detail']['field'] == 'usage'
        db_session.refresh(storage)
        assert storage.usage == 'internal'

    def test_update_still_takes_a_payload_that_echoes_the_current_usage(
        self, client, auth_headers, db_session, test_user
    ):
        """Only the *change* is refused — a round-tripped object still saves."""
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            name='Echoing Shelf',
            usage='internal',
        )
        db_session.add(storage)
        db_session.commit()

        response = client.put(
            f'/api/v1/locations/{storage.id}',
            headers=auth_headers,
            json={'name': 'Echoing Shelf II', 'usage': 'internal'},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['name'] == 'Echoing Shelf II'

    def test_the_dropped_odoo_roles_are_not_a_way_in(self, client, auth_headers):
        """``supplier``/``transit``/``scrap`` no longer exist anywhere."""
        from app.models.storage_location import LocationUsage

        assert {u.value for u in LocationUsage} == {
            'internal',
            'customer',
            'inventory',
            'production',
        }

        response = client.post(
            '/api/v1/locations',
            headers=auth_headers,
            json={'name': 'Bad Usage', 'usage': 'scrap'},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()['usage'] == 'internal'


@pytest.mark.integration
class TestStorageTypeUpdate:
    """storage_type_id is editable via PUT."""

    def test_update_storage_type(
        self, client, auth_headers, db_session, test_user, test_storage_type
    ):
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            organization_id=test_user.organization_id,
            created_by=test_user.id,
            name='Typed Storage',
            usage='internal',
        )
        db_session.add(storage)
        db_session.commit()

        response = client.put(
            f'/api/v1/locations/{storage.id}',
            headers=auth_headers,
            json={'location_type_id': str(test_storage_type.id)},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['location_type_id'] == str(test_storage_type.id)
