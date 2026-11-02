"""The public GET says the link is closed before the visitor clicks.

The page used to learn about a closed link only by clicking: the GET
answered PENDING while the equipment had long been returned or the
campaign cancelled, so the buttons stayed on offer and every press
returned the same 409. The GET now carries the closure reason — the same
vocabulary the refusals use — while the stored status stays untouched: a
read does not write, and a confirmed answer is still a confirmed answer.
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


def _make_deadline(days: int = 30) -> str:
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


def _launched_link(
    client: TestClient, headers: dict[str, str], db_session: Session
) -> tuple[str, str]:
    """A campaign with one response, launched — returns (token, campaign id)."""
    response = client.post(
        '/api/v1/equipment/campaigns',
        headers=headers,
        json={'name': 'Spring attestation', 'deadline': _make_deadline(14)},
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    campaign_id = str(response.json()['id'])
    client.post(
        f'/api/v1/equipment/campaigns/{campaign_id}/launch',
        headers=headers,
    ).raise_for_status()
    token = db_session.scalars(select(AuditResponse.token)).first()
    assert token
    return str(token), campaign_id


def _public_link(client: TestClient, token: str) -> dict[str, Any]:
    response = client.get(f'/public/attestation/{token}')
    assert response.status_code == status.HTTP_200_OK, response.text
    return dict(response.json())


@pytest.mark.integration
class TestAClosedLinkSaysSoBeforeTheClick:
    def test_an_open_link_carries_no_closed_reason(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        _checkout(client, eq_auth_headers, eq_item.id)
        token, _ = _launched_link(client, eq_auth_headers, db_session)

        body = _public_link(client, token)

        assert body['status'] == 'PENDING'
        assert body['closed_reason'] is None

    def test_a_returned_assignment_closes_the_link_before_the_click(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        _checkout(client, eq_auth_headers, eq_item.id)
        token, _ = _launched_link(client, eq_auth_headers, db_session)
        # The holder brings the equipment back through the app; the link
        # still in their inbox has to say so without being clicked.
        assignment = (
            db_session.query(EquipmentAssignment)
            .filter(EquipmentAssignment.item_id == eq_item.id)
            .first()
        )
        assert assignment is not None
        assignment.checked_in_at = datetime.now(UTC)
        db_session.commit()

        body = _public_link(client, token)

        # Additive: no answer was ever given, so the status stays PENDING —
        # the closure is told separately from the response's own state.
        assert body['status'] == 'PENDING'
        assert body['closed_reason'] == 'assignment_already_returned'

    def test_a_cancelled_campaign_closes_the_link_before_the_click(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        _checkout(client, eq_auth_headers, eq_item.id)
        token, campaign_id = _launched_link(client, eq_auth_headers, db_session)
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/cancel',
            headers=eq_auth_headers,
        ).raise_for_status()

        body = _public_link(client, token)

        assert body['status'] == 'PENDING'
        assert body['closed_reason'] == 'campaign_closed'

    def test_an_expired_token_closes_the_link_before_the_click(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        _checkout(client, eq_auth_headers, eq_item.id)
        token, _ = _launched_link(client, eq_auth_headers, db_session)
        row = db_session.scalars(select(AuditResponse)).first()
        assert row is not None
        row.token_expires_at = datetime.now(UTC) - timedelta(hours=1)
        db_session.commit()

        body = _public_link(client, token)

        assert body['status'] == 'PENDING'
        assert body['closed_reason'] == 'expired'

    def test_the_answer_a_confirmed_link_keeps_wins_over_the_closure(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        # Confirmed first, campaign closed afterwards: the reader already
        # answered, and that answer — not the closure — is what they need
        # to see. The closure still rides along for whoever asks.
        _checkout(client, eq_auth_headers, eq_item.id)
        token, campaign_id = _launched_link(client, eq_auth_headers, db_session)
        confirmed = client.post(f'/public/attestation/{token}/confirm')
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/cancel',
            headers=eq_auth_headers,
        ).raise_for_status()

        body = _public_link(client, token)

        assert body['status'] == 'CONFIRMED'
        assert body['closed_reason'] == 'campaign_closed'
