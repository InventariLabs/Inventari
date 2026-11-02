"""A campaign created by mistake had nowhere to go.

The API could create, launch, remind and complete — so a campaign addressed
to the wrong people, or with the wrong deadline, stayed in the register
forever and the only way out was to mark it "completed", which says something
that did not happen.

Two ways out, and they are not the same one:

* Before launch there is nothing to preserve — no links went out, no answers
  came back — so a draft is deleted.
* After launch there is. `audit_responses.campaign_id` cascades, so deleting
  a live campaign would take the confirmations with it: `responded_at`, the
  address they came from, and every report of a missing or damaged unit. The
  model has always declared a `CANCELLED` status that nothing ever wrote, and
  responses are already refused for a campaign that is not ACTIVE — so
  cancelling voids the links that are out there the moment it is set, and the
  campaign stays visible as what it was.
"""

from typing import Any
from uuid import uuid4

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.modules.equipment.models import AuditResponse


def _make_deadline(days: int = 30) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def _checkout(client: TestClient, headers: dict[str, str], item_id: Any) -> None:
    response = client.post(
        '/api/v1/equipment/assignments',
        headers=headers,
        json={
            'item_id': str(item_id),
            'assigned_to_name': 'Alice',
            'assigned_to_email': 'alice@example.com',
        },
    )
    response.raise_for_status()


def _campaign(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        '/api/v1/equipment/campaigns',
        headers=headers,
        json={'name': 'Wrong deadline', 'deadline': _make_deadline(14)},
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    campaign_id: str = response.json()['id']
    return campaign_id


@pytest.mark.integration
class TestWithdrawingACampaign:
    def test_a_draft_is_deleted(
        self, client: TestClient, eq_auth_headers: dict[str, str]
    ) -> None:
        campaign_id = _campaign(client, eq_auth_headers)

        deleted = client.delete(
            f'/api/v1/equipment/campaigns/{campaign_id}', headers=eq_auth_headers
        )

        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        listed = client.get('/api/v1/equipment/campaigns', headers=eq_auth_headers)
        assert campaign_id not in {row['id'] for row in listed.json()['items']}

    @pytest.mark.parametrize(
        ('method', 'suffix'), [('delete', ''), ('post', '/cancel'), ('get', '')]
    )
    def test_a_missing_one_answers_with_the_not_found_code(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        method: str,
        suffix: str,
    ) -> None:
        # These answered a bare sentence with no code at all.
        url = f'/api/v1/equipment/campaigns/{uuid4()}{suffix}'

        response = client.request(method, url, headers=eq_auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()['detail']['code'] == 'CAMPAIGN_NOT_FOUND'

    def test_a_launched_one_refuses_deletion(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        # The answers are the only trace an attestation produces, and the FK
        # cascades — so this is a refusal, not a confirmation prompt.
        _checkout(client, eq_auth_headers, eq_item.id)
        campaign_id = _campaign(client, eq_auth_headers)
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch',
            headers=eq_auth_headers,
        ).raise_for_status()

        deleted = client.delete(
            f'/api/v1/equipment/campaigns/{campaign_id}', headers=eq_auth_headers
        )

        assert deleted.status_code == status.HTTP_409_CONFLICT

    def test_a_launched_one_is_cancelled_instead(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        _checkout(client, eq_auth_headers, eq_item.id)
        campaign_id = _campaign(client, eq_auth_headers)
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch',
            headers=eq_auth_headers,
        ).raise_for_status()

        cancelled = client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/cancel',
            headers=eq_auth_headers,
        )

        assert cancelled.status_code == status.HTTP_200_OK
        assert cancelled.json()['status'] == 'CANCELLED'

    def test_cancelling_voids_the_links_that_went_out(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        # The point of cancelling rather than completing: an employee who
        # clicks yesterday's email must not be able to attest to it.
        _checkout(client, eq_auth_headers, eq_item.id)
        campaign_id = _campaign(client, eq_auth_headers)
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch',
            headers=eq_auth_headers,
        ).raise_for_status()
        # The token is deliberately not in the API's response schema — it is
        # the whole authority of the link — so it is read from the row.
        token = db_session.scalars(select(AuditResponse.token)).first()

        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/cancel',
            headers=eq_auth_headers,
        ).raise_for_status()

        confirmed = client.post(f'/public/attestation/{token}/confirm')
        assert confirmed.status_code >= 400

    def test_a_cancelled_one_is_still_there_to_be_read(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        _checkout(client, eq_auth_headers, eq_item.id)
        campaign_id = _campaign(client, eq_auth_headers)
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch',
            headers=eq_auth_headers,
        ).raise_for_status()
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/cancel',
            headers=eq_auth_headers,
        ).raise_for_status()

        detail = client.get(
            f'/api/v1/equipment/campaigns/{campaign_id}', headers=eq_auth_headers
        )

        assert detail.status_code == status.HTTP_200_OK
        assert len(detail.json()['responses']) == 1
