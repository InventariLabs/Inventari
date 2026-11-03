"""Integration tests for storage archival.

Archiving hides a location from lists, trees and pickers while keeping it
in history. "Move content and close" relocates items (including those in
descendant locations) to a chosen target in the same operation.
"""

import pytest
from fastapi import status


@pytest.mark.integration
class TestStorageArchive:
    """POST /locations/{id}/archive."""

    def _make(self, db_session, user, name, parent_id=None):
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            organization_id=user.organization_id,
            created_by=user.id,
            name=name,
            parent_id=parent_id,
            usage='internal',
        )
        db_session.add(storage)
        db_session.commit()
        db_session.refresh(storage)
        return storage

    def _add_item(self, db_session, user, storage_id, name):
        from app.models.item import Item

        item = Item(
            organization_id=user.organization_id,
            storage_location_id=storage_id,
            name=name,
            quantity=1,
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)
        return item

    def _archive(self, client, auth_headers, storage_id, move_items_to=None):
        return client.post(
            f'/api/v1/locations/{storage_id}/archive',
            headers=auth_headers,
            json={} if move_items_to is None else {'move_items_to': str(move_items_to)},
        )

    def test_archive_empty_storage_hides_it(
        self, client, auth_headers, db_session, test_user
    ):
        storage = self._make(db_session, test_user, 'To Archive')

        response = self._archive(client, auth_headers, storage.id)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['settings']['archived'] is True
        listing = client.get('/api/v1/locations', headers=auth_headers).json()['items']
        assert not any(s['id'] == str(storage.id) for s in listing)
        tree = client.get('/api/v1/locations/tree', headers=auth_headers).json()
        assert not any(n['id'] == str(storage.id) for n in tree)

    def test_archive_with_items_requires_target(
        self, client, auth_headers, db_session, test_user
    ):
        storage = self._make(db_session, test_user, 'Occupied')
        self._add_item(db_session, test_user, storage.id, 'Widget')

        response = self._archive(client, auth_headers, storage.id)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        detail = client.get(
            f'/api/v1/locations/{storage.id}', headers=auth_headers
        ).json()
        assert (detail['settings'] or {}).get('archived') is not True

    def test_archive_moves_items_to_target(
        self, client, auth_headers, db_session, test_user
    ):
        source = self._make(db_session, test_user, 'Source')
        target = self._make(db_session, test_user, 'Target')
        item = self._add_item(db_session, test_user, source.id, 'Widget')

        response = self._archive(
            client, auth_headers, source.id, move_items_to=target.id
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()['settings']['archived'] is True
        items = client.get(
            f'/api/v1/locations/{target.id}/items', headers=auth_headers
        ).json()['items']
        assert any(i['id'] == str(item.id) for i in items)

    def test_archive_moves_items_from_descendant_locations(
        self, client, auth_headers, db_session, test_user
    ):
        """Closing a zone relocates items sitting in its child locations."""
        site = self._make(db_session, test_user, 'Site')
        zone = self._make(db_session, test_user, 'Zone', parent_id=site.id)
        location = self._make(
            db_session,
            test_user,
            'Location',
            parent_id=zone.id,
        )
        target = self._make(db_session, test_user, 'Target')
        item = self._add_item(db_session, test_user, location.id, 'Widget')

        response = self._archive(client, auth_headers, zone.id, move_items_to=target.id)

        assert response.status_code == status.HTTP_200_OK
        items = client.get(
            f'/api/v1/locations/{target.id}/items', headers=auth_headers
        ).json()['items']
        assert any(i['id'] == str(item.id) for i in items)

    def test_archive_unknown_target_returns_404(
        self, client, auth_headers, db_session, test_user
    ):
        from uuid import uuid4

        storage = self._make(db_session, test_user, 'Source')

        response = self._archive(
            client, auth_headers, storage.id, move_items_to=uuid4()
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_archive_self_target_returns_400(
        self, client, auth_headers, db_session, test_user
    ):
        storage = self._make(db_session, test_user, 'Source')

        response = self._archive(
            client, auth_headers, storage.id, move_items_to=storage.id
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_archive_descendant_target_returns_400(
        self, client, auth_headers, db_session, test_user
    ):
        """Moving items into a descendant of the archived node is rejected."""
        zone = self._make(db_session, test_user, 'Zone')
        child = self._make(db_session, test_user, 'Child shelf', parent_id=zone.id)
        self._add_item(db_session, test_user, zone.id, 'Milk')

        response = self._archive(client, auth_headers, zone.id, move_items_to=child.id)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_archived_storage_still_reachable_in_detail(
        self, client, auth_headers, db_session, test_user
    ):
        storage = self._make(db_session, test_user, 'Archived Detail')
        assert (
            self._archive(client, auth_headers, storage.id).status_code
            == status.HTTP_200_OK
        )

        detail = client.get(f'/api/v1/locations/{storage.id}', headers=auth_headers)

        assert detail.status_code == status.HTTP_200_OK


@pytest.mark.integration
class TestStorageUnarchive:
    """POST /locations/{id}/unarchive — the way back.

    Archiving is where the app sends anyone who may not delete a location,
    so it cannot be a one-way door: the only known way back used to be an
    UPDATE against the database.
    """

    def _make(self, db_session, user, name, parent_id=None):
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            organization_id=user.organization_id,
            created_by=user.id,
            name=name,
            parent_id=parent_id,
            usage='internal',
        )
        db_session.add(storage)
        db_session.commit()
        db_session.refresh(storage)
        return storage

    def _archive(self, client, auth_headers, storage_id):
        return client.post(
            f'/api/v1/locations/{storage_id}/archive', headers=auth_headers, json={}
        )

    def test_a_restored_location_is_back_in_the_listing(
        self, client, auth_headers, db_session, test_user
    ):
        storage = self._make(db_session, test_user, 'Fridge')
        self._archive(client, auth_headers, storage.id)

        response = client.post(
            f'/api/v1/locations/{storage.id}/unarchive', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        listing = client.get('/api/v1/locations', headers=auth_headers).json()['items']
        assert any(s['id'] == str(storage.id) for s in listing)

    def test_the_archived_listing_holds_what_the_tree_no_longer_shows(
        self, client, auth_headers, db_session, test_user
    ):
        storage = self._make(db_session, test_user, 'Seasonal cold room')
        self._archive(client, auth_headers, storage.id)

        archived = client.get(
            '/api/v1/locations/archived', headers=auth_headers
        ).json()['items']

        assert [s['name'] for s in archived] == ['Seasonal cold room']

    def test_the_archived_listing_carries_the_path_that_tells_same_names_apart(
        self, client, auth_headers, db_session, test_user
    ):
        """Two "Shelf 1" rows are told apart by where they stood.

        The listing answered the name alone, so restoring one of two
        identically named locations was a guess — the path is this
        application's identity for a location, and the archive was the one
        screen that dropped it.
        """
        server_room = self._make(db_session, test_user, 'Server Room')
        workshop = self._make(db_session, test_user, 'IT Workshop')
        first = self._make(db_session, test_user, 'Shelf 1', parent_id=server_room.id)
        second = self._make(db_session, test_user, 'Shelf 1', parent_id=workshop.id)
        self._archive(client, auth_headers, first.id)
        self._archive(client, auth_headers, second.id)

        archived = client.get(
            '/api/v1/locations/archived', headers=auth_headers
        ).json()['items']

        assert sorted(s['full_path'] for s in archived) == [
            'IT Workshop › Shelf 1',
            'Server Room › Shelf 1',
        ]

    def test_the_archived_listing_carries_the_date_the_journal_recorded(
        self, client, auth_headers, db_session, test_user
    ):
        """The moment a location left the lists, from the organization journal.

        Archiving writes no date column of its own (the flag is settings), so
        the SOFT_DELETE storage entry is where that date lives — and the
        listing showed neither path nor date.
        """
        from datetime import datetime

        from app.models.audit_log import AuditLog

        storage = self._make(db_session, test_user, 'Seasonal cold room')
        self._archive(client, auth_headers, storage.id)

        archived = client.get(
            '/api/v1/locations/archived', headers=auth_headers
        ).json()['items']

        entry = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.target_id == storage.id,
                AuditLog.action == 'SOFT_DELETE',
            )
            .one()
        )
        assert archived[0]['archived_at'] is not None
        assert datetime.fromisoformat(archived[0]['archived_at']) == entry.created_at

    def test_the_archived_listing_follows_the_module_data_policy(
        self, client, auth_headers, db_session, test_user
    ):
        """exclude_module_contexts scopes the archive like the active tab.

        The pair of tabs describes one population: without the flag the
        archive listed module-owned rows the active tab hides, and a restore
        of one was confirmed on the screen that can never show it.
        """
        module_storage = self._make(db_session, test_user, 'Patch Panel')
        module_storage.context_tag = 'equipment'
        db_session.commit()
        own = self._make(db_session, test_user, 'Spare Shelf')
        self._archive(client, auth_headers, module_storage.id)
        self._archive(client, auth_headers, own.id)

        scoped = client.get(
            '/api/v1/locations/archived?exclude_module_contexts=true',
            headers=auth_headers,
        ).json()['items']

        assert [s['name'] for s in scoped] == ['Spare Shelf']

        # No flag, no filter: the archive stays the place that reaches what a
        # module left behind — the policy is the organization's, not the
        # endpoint's.
        full = client.get('/api/v1/locations/archived', headers=auth_headers).json()[
            'items'
        ]
        assert {s['name'] for s in full} == {'Patch Panel', 'Spare Shelf'}

    def test_restoring_under_an_archived_parent_is_refused(
        self, client, auth_headers, db_session, test_user
    ):
        zone = self._make(db_session, test_user, 'Zone')
        shelf = self._make(db_session, test_user, 'Shelf', parent_id=zone.id)
        self._archive(client, auth_headers, shelf.id)
        self._archive(client, auth_headers, zone.id)

        response = client.post(
            f'/api/v1/locations/{shelf.id}/unarchive', headers=auth_headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_restoring_a_location_that_was_not_archived_is_harmless(
        self, client, auth_headers, db_session, test_user
    ):
        storage = self._make(db_session, test_user, 'Never archived')

        response = client.post(
            f'/api/v1/locations/{storage.id}/unarchive', headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK
        assert not (response.json()['settings'] or {}).get('archived')


@pytest.mark.integration
class TestAnArchivedLocationTakesNoNewProducts:
    """The screen offered "Add product" and the server said 201.

    The product then showed up in the list with an "Unknown" location, and
    could not be moved back to where it came from.
    """

    def _make_archived(self, client, auth_headers, db_session, user, name):
        from app.models.storage_location import StorageLocation

        storage = StorageLocation(
            organization_id=user.organization_id,
            created_by=user.id,
            name=name,
            usage='internal',
        )
        db_session.add(storage)
        db_session.commit()
        db_session.refresh(storage)
        client.post(
            f'/api/v1/locations/{storage.id}/archive', headers=auth_headers, json={}
        )
        return storage

    def test_creating_an_item_there_is_refused(
        self, client, auth_headers, db_session, test_user
    ):
        storage = self._make_archived(
            client, auth_headers, db_session, test_user, 'Closed shelf'
        )

        response = client.post(
            '/api/v1/items',
            headers=auth_headers,
            json={
                'name': 'Latecomer',
                'quantity': 1,
                'location_id': str(storage.id),
            },
        )

        assert response.status_code in (400, 422)
