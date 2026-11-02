"""Marking an asset deployed is the shadow of checking it out, not a choice.

Three doors could set ``equipment_status`` to DEPLOYED: the status menu on
the detail screen, the edit form, and the batch status action. The batch one
already refused; the other two went through the plain item PATCH, which knew
nothing about assignments — so an asset could read "Deployed" with an empty
"checked out to" column, while the dashboard tile counting open assignments
disagreed and nothing in the history explained it.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item


def _status_of(item: Item) -> Any:
    return (item.meta_data or {}).get('equipment', {}).get('equipment_status')


@pytest.mark.integration
class TestManualDeployGuard:
    def test_writing_deployed_without_a_holder_is_refused(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        response = client.put(
            f'/api/v1/items/{eq_item.id}',
            headers=eq_auth_headers,
            json={
                'metadata': {
                    'equipment': {
                        'equipment_status': 'DEPLOYED',
                        'asset_tag': 'AT-1',
                    }
                }
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        db_session.refresh(eq_item)
        assert _status_of(eq_item) == 'AVAILABLE'

    def test_an_asset_already_deployed_stays_editable(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """Rows whose status drifted before the guard must not become stuck."""
        eq_item.meta_data = {
            'equipment': {'equipment_status': 'DEPLOYED', 'asset_tag': 'AT-0'}
        }
        db_session.add(eq_item)
        db_session.commit()

        response = client.put(
            f'/api/v1/items/{eq_item.id}',
            headers=eq_auth_headers,
            json={
                'metadata': {
                    'equipment': {
                        'equipment_status': 'DEPLOYED',
                        'asset_tag': 'AT-2',
                    }
                }
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        db_session.refresh(eq_item)
        assert (eq_item.meta_data or {})['equipment']['asset_tag'] == 'AT-2'

    def test_other_statuses_are_untouched(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        response = client.put(
            f'/api/v1/items/{eq_item.id}',
            headers=eq_auth_headers,
            json={'metadata': {'equipment': {'equipment_status': 'MAINTENANCE'}}},
        )

        assert response.status_code == status.HTTP_200_OK, response.text
        db_session.refresh(eq_item)
        assert _status_of(eq_item) == 'MAINTENANCE'

    def test_writing_available_while_someone_holds_it_is_refused(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """The mirror drift: a status that hides an open assignment."""
        checkout = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Anna Kowalska',
            },
        )
        assert checkout.status_code == status.HTTP_201_CREATED, checkout.text

        response = client.put(
            f'/api/v1/items/{eq_item.id}',
            headers=eq_auth_headers,
            json={'metadata': {'equipment': {'equipment_status': 'AVAILABLE'}}},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        db_session.refresh(eq_item)
        assert _status_of(eq_item) == 'DEPLOYED'

    def test_checkout_still_deploys(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """The one door that may set it: handing the asset to a person."""
        response = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Anna Kowalska',
                'assigned_to_email': 'anna@example.com',
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        db_session.refresh(eq_item)
        assert _status_of(eq_item) == 'DEPLOYED'
