"""An archived asset stays readable where the app links to it.

The archive is a soft delete: the row remains in the register with the
Restore and Purge actions under it, and assignment history keeps linking to
its card. Every reader on that card resolved the item through the live-only
``get_async``, so archiving turned the whole card into "Asset not found" and
emptied the history row's name. Reads answer for archived assets; writes
keep refusing — the tests below pin the read side, the existing suite pins
the refusals.
"""

import pytest
from fastapi import status
from starlette.testclient import TestClient

from app.models.item import Item


def _archive(client: TestClient, headers: dict[str, str], item: Item) -> None:
    response = client.delete(f'/api/v1/items/{item.id}', headers=headers)
    assert response.status_code == status.HTTP_204_NO_CONTENT, response.text


@pytest.mark.integration
class TestAnArchivedAssetAnswersItsCard:
    def test_the_card_read_serves_the_record_with_the_archived_flag(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """The card names the archive in the ask and gets the record back.

        Without the ask the read keeps its archive-pointing 404 (the core
        suite pins that); with it, the page can render ``is_deleted`` and
        the Restore/Purge branch that was unreachable before."""
        _archive(client, eq_auth_headers, eq_item)

        response = client.get(
            f'/api/v1/items/{eq_item.id}?include_archived=true',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        body = response.json()
        assert body['id'] == str(eq_item.id)
        assert body['name'] == eq_item.name
        assert body['is_deleted'] is True

    def test_the_timeline_of_an_archived_asset_still_answers(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        _archive(client, eq_auth_headers, eq_item)

        response = client.get(
            f'/api/v1/equipment/assets/{eq_item.id}/timeline',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK, response.text

    def test_the_valuation_of_an_archived_asset_still_answers(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        _archive(client, eq_auth_headers, eq_item)

        response = client.get(
            f'/api/v1/equipment/{eq_item.id}/valuation',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['item_name'] == eq_item.name

    def test_the_attachments_of_an_archived_asset_still_answer(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        _archive(client, eq_auth_headers, eq_item)

        response = client.get(
            f'/api/v1/equipment/{eq_item.id}/attachments',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['items'] == []

    def test_the_maintenance_log_of_an_archived_asset_still_answers(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        _archive(client, eq_auth_headers, eq_item)

        response = client.get(
            f'/api/v1/equipment/maintenance/item/{eq_item.id}',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['items'] == []

    def test_the_approval_status_of_an_archived_asset_still_answers(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        _archive(client, eq_auth_headers, eq_item)

        response = client.get(
            f'/api/v1/equipment/{eq_item.id}/approval-status',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        assert response.json()['has_workflow'] is False


@pytest.mark.integration
class TestMyAssetsHistoryKeepsTheArchivedName:
    def test_the_history_row_still_names_the_archived_asset(
        self, client: TestClient, eq_auth_headers: dict[str, str], eq_item: Item
    ) -> None:
        """The past row links to the card and must say what it links to.

        The name came from the live-only read, so archiving left an empty
        link behind — a dead end with no label. History is the record of
        what was, and an archived asset was there."""
        checkout = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Equipment User',
                'assigned_to_email': 'equipment@example.com',
            },
        )
        assert checkout.status_code == status.HTTP_201_CREATED, checkout.text
        assignment_id = checkout.json()['id']

        checkin = client.post(
            f'/api/v1/equipment/assignments/{assignment_id}/checkin',
            headers=eq_auth_headers,
            json={'checkin_condition': 'GOOD'},
        )
        assert checkin.status_code == status.HTTP_200_OK, checkin.text

        _archive(client, eq_auth_headers, eq_item)

        response = client.get(
            '/api/v1/equipment/my-assets/history',
            headers=eq_auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        rows = response.json()['items']
        assert len(rows) == 1
        assert rows[0]['item_id'] == str(eq_item.id)
        assert rows[0]['item_name'] == eq_item.name
