"""The flat storages list can name whatever a record is standing in.

The items list resolves each row's LOCATION against the storages it asked
for, and that ask reached only the internal, never-archived slice of the
tree: a record consumed to zero (its location is the virtual Consumed
row) or left behind in an archived one read "Unknown" over a location the
organization knows perfectly well — while the record's own detail screen
named it. The naming ask is not a picker; it must reach everything.
"""

import pytest
from fastapi import status
from starlette.testclient import TestClient


@pytest.mark.integration
class TestTheNamingListReachesTheUnlisted:
    def _list(
        self, client: TestClient, auth_headers: dict, query: str = ''
    ) -> set[str]:
        response = client.get(f'/api/v1/locations{query}', headers=auth_headers)
        assert response.status_code == status.HTTP_200_OK, response.text
        return {s['name'] for s in response.json()['items']}

    def test_usage_all_with_include_archived_names_every_row(
        self, client: TestClient, auth_headers: dict, db_session, test_user
    ) -> None:
        from app.models.storage_location import StorageLocation

        names = (
            'Naming Probe Warehouse',
            'Naming Probe Consumed',
            'Naming Probe Old Shelf',
        )
        rows = [
            StorageLocation(
                organization_id=test_user.organization_id,
                created_by=test_user.id,
                name=names[0],
                usage='internal',
            ),
            # The virtual counterpart a consumed-to-zero record ends up in.
            StorageLocation(
                organization_id=test_user.organization_id,
                created_by=test_user.id,
                name=names[1],
                usage='customer',
            ),
            # Archived rows live in the settings flag, the way the archive
            # endpoint writes them.
            StorageLocation(
                organization_id=test_user.organization_id,
                created_by=test_user.id,
                name=names[2],
                usage='internal',
                settings={'archived': True},
            ),
        ]
        db_session.add_all(rows)
        db_session.commit()

        default = self._list(client, auth_headers)
        assert names[0] in default
        assert names[1] not in default
        assert names[2] not in default

        usage_all = self._list(client, auth_headers, '?usage=all')
        assert names[1] in usage_all
        assert names[2] not in usage_all

        everything = self._list(
            client, auth_headers, '?usage=all&include_archived=true'
        )
        assert names[1] in everything
        assert names[2] in everything
