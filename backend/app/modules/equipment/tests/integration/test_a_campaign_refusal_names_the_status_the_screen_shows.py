"""A refusal about a campaign's state uses the word its screen uses.

The campaign list calls a completed campaign "Closed"; a sentence saying
"already COMPLETED" names a state the reader has never seen.
"""

from typing import Any
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from app.models.item import Item


def _launched_campaign(
    client: TestClient, headers: dict[str, str], item_id: Any
) -> str:
    client.post(
        '/api/v1/equipment/assignments',
        headers=headers,
        json={
            'item_id': str(item_id),
            'assigned_to_name': 'Alice',
            'assigned_to_email': f'alice-{uuid4().hex[:6]}@example.com',
        },
    ).raise_for_status()
    created = client.post(
        '/api/v1/equipment/campaigns',
        headers=headers,
        json={'name': 'Annual', 'deadline': '2999-01-01T00:00:00+00:00'},
    )
    created.raise_for_status()
    campaign_id: str = created.json()['id']
    client.post(
        f'/api/v1/equipment/campaigns/{campaign_id}/launch', headers=headers
    ).raise_for_status()
    return campaign_id


@pytest.mark.integration
class TestACampaignRefusalNamesTheStatus:
    def test_launching_a_campaign_that_is_not_a_draft_says_active(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        campaign_id = _launched_campaign(client, eq_auth_headers, eq_item.id)

        again = client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch',
            headers=eq_auth_headers,
        )

        assert again.status_code == 400
        assert 'already Active' in again.text
        assert 'ACTIVE' not in again.text

    def test_a_closed_campaign_is_named_closed(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        campaign_id = _launched_campaign(client, eq_auth_headers, eq_item.id)
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/complete',
            headers=eq_auth_headers,
        ).raise_for_status()

        again = client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/complete',
            headers=eq_auth_headers,
        )

        assert again.status_code == 400
        assert 'that is Closed' in again.text
        assert 'COMPLETED' not in again.text
