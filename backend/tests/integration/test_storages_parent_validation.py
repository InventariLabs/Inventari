"""
Integration tests for storage location parent validation.

Verified against the live API on 2026-08-14: `parent_id` was written from the
request without any checks — a cycle, a self-parent and a cross-organization
parent all passed with 200 OK. These tests pin the fixed contract:

- parent is a descendant of the edited node        -> 409 STORAGE_CYCLE
- parent is the edited node itself                 -> 400
- parent belongs to another organization / missing -> 404
- a valid re-parent still succeeds                 -> 200
"""

import pytest
from fastapi import status


@pytest.mark.integration
class TestStorageParentValidation:
    """Tests for parent_id validation on storage create/update."""

    def _make_storage(self, db_session, user, name, parent_id=None):
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            organization_id=user.organization_id,
            created_by=user.id,
            name=name,
            parent_id=parent_id,
        )
        db_session.add(storage)
        db_session.commit()
        db_session.refresh(storage)
        return storage

    def test_update_parent_to_descendant_returns_409(
        self, client, auth_headers, db_session, test_user
    ):
        """Reparenting a node under its own descendant must be rejected (cycle)."""
        site = self._make_storage(db_session, test_user, 'Site')
        zone = self._make_storage(db_session, test_user, 'Zone', parent_id=site.id)

        response = client.put(
            f'/api/v1/locations/{site.id}',
            headers=auth_headers,
            json={'parent_id': str(zone.id)},
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        detail = response.json()['detail']
        assert detail['code'] == 'STORAGE_CYCLE'

    def test_update_parent_to_self_returns_400(
        self, client, auth_headers, db_session, test_user
    ):
        """A storage location cannot become its own parent."""
        site = self._make_storage(db_session, test_user, 'Site')

        response = client.put(
            f'/api/v1/locations/{site.id}',
            headers=auth_headers,
            json={'parent_id': str(site.id)},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_parent_cross_org_returns_404(
        self, client, auth_headers, db_session, test_user
    ):
        """A parent belonging to another organization must not be accepted."""
        from app.models.organization import Organization
        from app.models.storage_location import StorageLocation

        other_org = Organization(name='Other Organization', enabled_modules=[])
        db_session.add(other_org)
        db_session.commit()
        db_session.refresh(other_org)

        foreign = StorageLocation(
            organization_id=other_org.id,
            created_by=test_user.id,
            name='Foreign storage',
        )
        db_session.add(foreign)
        db_session.commit()

        site = self._make_storage(db_session, test_user, 'Site')

        response = client.put(
            f'/api/v1/locations/{site.id}',
            headers=auth_headers,
            json={'parent_id': str(foreign.id)},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_parent_missing_returns_404(
        self, client, auth_headers, db_session, test_user
    ):
        """A parent that does not exist at all must be rejected with 404."""
        from uuid import uuid4

        site = self._make_storage(db_session, test_user, 'Site')

        response = client.put(
            f'/api/v1/locations/{site.id}',
            headers=auth_headers,
            json={'parent_id': str(uuid4())},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_with_cross_org_parent_returns_404(
        self, client, auth_headers, db_session, test_user
    ):
        """Creating a location under another organization's parent is rejected."""
        from app.models.organization import Organization
        from app.models.storage_location import StorageLocation

        other_org = Organization(name='Other Organization', enabled_modules=[])
        db_session.add(other_org)
        db_session.commit()
        db_session.refresh(other_org)

        foreign = StorageLocation(
            organization_id=other_org.id,
            created_by=test_user.id,
            name='Foreign storage',
        )
        db_session.add(foreign)
        db_session.commit()

        response = client.post(
            '/api/v1/locations',
            headers=auth_headers,
            json={'name': 'New location', 'parent_id': str(foreign.id)},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_valid_reparent_still_returns_200(
        self, client, auth_headers, db_session, test_user
    ):
        """Control case: moving a node under another valid root still works."""
        site_a = self._make_storage(db_session, test_user, 'Site A')
        site_b = self._make_storage(db_session, test_user, 'Site B')
        zone = self._make_storage(db_session, test_user, 'Zone', parent_id=site_a.id)

        response = client.put(
            f'/api/v1/locations/{zone.id}',
            headers=auth_headers,
            json={'parent_id': str(site_b.id)},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['parent_id'] == str(site_b.id)
