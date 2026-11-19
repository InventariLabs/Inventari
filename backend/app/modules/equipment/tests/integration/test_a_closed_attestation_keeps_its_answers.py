"""A closed attestation keeps each asset's recorded answer.

A return after the campaign closed is a custody move, not a new answer: the
detail of a completed campaign still carries what was confirmed or reported.
On a live campaign an asset returned before it was answered is flagged as
returned, while one already answered keeps its answer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.modules.equipment.models import AuditResponse, EquipmentAssignment


def _launched(
    client: TestClient, headers: dict[str, str], db_session: Session, item: Item
) -> tuple[str, str]:
    client.post(
        '/api/v1/equipment/assignments',
        headers=headers,
        json={
            'item_id': str(item.id),
            'assigned_to_name': 'Alice',
            'assigned_to_email': 'alice@example.com',
        },
    ).raise_for_status()
    created = client.post(
        '/api/v1/equipment/campaigns',
        headers=headers,
        json={
            'name': 'Q4 check',
            'deadline': (datetime.now(UTC) + timedelta(days=14)).isoformat(),
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    campaign_id = str(created.json()['id'])
    client.post(
        f'/api/v1/equipment/campaigns/{campaign_id}/launch', headers=headers
    ).raise_for_status()
    token = db_session.scalars(select(AuditResponse.token)).first()
    assert token
    return str(token), campaign_id


def _return_asset(db_session: Session, item: Item) -> None:
    assignment = (
        db_session.query(EquipmentAssignment)
        .filter(EquipmentAssignment.item_id == item.id)
        .first()
    )
    assert assignment is not None
    assignment.checked_in_at = datetime.now(UTC)
    db_session.commit()


def _only_item(
    client: TestClient, headers: dict[str, str], campaign_id: str
) -> dict[str, Any]:
    detail = client.get(f'/api/v1/equipment/campaigns/{campaign_id}', headers=headers)
    assert detail.status_code == status.HTTP_200_OK, detail.text
    (row,) = detail.json()['responses']
    (item,) = row['items']
    return dict(item)


@pytest.mark.integration
class TestAClosedAttestationKeepsItsAnswers:
    def test_a_return_after_the_close_leaves_a_confirmed_answer_unflagged(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        token, campaign_id = _launched(client, eq_auth_headers, db_session, eq_item)
        assert client.post(f'/public/attestation/{token}/confirm').status_code == 200
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/complete',
            headers=eq_auth_headers,
        ).raise_for_status()
        _return_asset(db_session, eq_item)

        item = _only_item(client, eq_auth_headers, campaign_id)

        assert item['status'] == 'CONFIRMED'
        assert item['returned'] is False

    def test_a_return_after_the_close_leaves_an_unanswered_item_awaiting(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        _, campaign_id = _launched(client, eq_auth_headers, db_session, eq_item)
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/complete',
            headers=eq_auth_headers,
        ).raise_for_status()
        _return_asset(db_session, eq_item)

        item = _only_item(client, eq_auth_headers, campaign_id)

        assert item['status'] == 'PENDING'
        assert item['returned'] is False

    def test_a_return_after_the_close_does_not_move_the_stats(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        _, campaign_id = _launched(client, eq_auth_headers, db_session, eq_item)
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/complete',
            headers=eq_auth_headers,
        ).raise_for_status()
        _return_asset(db_session, eq_item)

        detail = client.get(
            f'/api/v1/equipment/campaigns/{campaign_id}', headers=eq_auth_headers
        ).json()

        assert detail['stats']['pending'] == 1
        assert detail['stats']['returned'] == 0

    def test_a_live_campaign_flags_an_unanswered_returned_item(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        _, campaign_id = _launched(client, eq_auth_headers, db_session, eq_item)
        _return_asset(db_session, eq_item)

        item = _only_item(client, eq_auth_headers, campaign_id)

        assert item['status'] == 'PENDING'
        assert item['returned'] is True

    def test_a_live_campaign_keeps_the_answer_of_a_returned_item(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        token, campaign_id = _launched(client, eq_auth_headers, db_session, eq_item)
        assert client.post(f'/public/attestation/{token}/confirm').status_code == 200
        _return_asset(db_session, eq_item)

        item = _only_item(client, eq_auth_headers, campaign_id)

        assert item['status'] == 'CONFIRMED'
        assert item['returned'] is False
