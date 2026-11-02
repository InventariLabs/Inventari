"""A refusal on the public attestation page reads as a sentence.

The public confirm endpoint maps the service's ValueErrors to i18n keys —
including ``campaign_closed`` and ``assignment_already_returned``, which
existed nowhere: no TypedDict entry, no catalog row. ``get_error_message``
answers an unknown key with the key itself, and the toast shows it raw —
on the one page whose reader is a stranger to the organisation, holding
the equipment.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.item import Item
from app.modules.equipment.models import AuditResponse, EquipmentAssignment


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
        json={'name': 'Spring attestation', 'deadline': _make_deadline(14)},
    )
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return str(response.json()['id'])


def _token_out_of_the_row(db_session: Session) -> str:
    """The token is the link's whole authority, so it is not in the API's
    response schema — it is read from the row."""
    token = db_session.scalars(select(AuditResponse.token)).first()
    assert token
    return str(token)


def _assert_sentence(envelope: dict[str, str], code: str) -> str:
    """What a reader gets instead of an identifier: words, spaces, an end.

    The identifier travels beside it as the code, the catalogue key upper-cased.
    """
    assert envelope['code'] == code, envelope
    detail = envelope['message']
    assert '{' not in detail, detail
    assert '_' not in detail, detail
    assert detail != detail.strip('_') or ' ' in detail, detail
    assert detail.endswith('.'), detail
    return detail


@pytest.mark.integration
class TestAPublicRefusalReadsAsASentence:
    def test_confirming_after_the_campaign_was_cancelled_names_the_cause(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        _checkout(client, eq_auth_headers, eq_item.id)
        campaign_id = _campaign(client, eq_auth_headers)
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch',
            headers=eq_auth_headers,
        ).raise_for_status()
        token = _token_out_of_the_row(db_session)
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/cancel',
            headers=eq_auth_headers,
        ).raise_for_status()

        refused = client.post(f'/public/attestation/{token}/confirm')

        assert refused.status_code == status.HTTP_409_CONFLICT
        detail = _assert_sentence(refused.json()['detail'], 'CAMPAIGN_CLOSED')
        assert 'closed' in detail.lower()

    def test_confirming_twice_says_the_return_was_already_recorded(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        _checkout(client, eq_auth_headers, eq_item.id)
        campaign_id = _campaign(client, eq_auth_headers)
        client.post(
            f'/api/v1/equipment/campaigns/{campaign_id}/launch',
            headers=eq_auth_headers,
        ).raise_for_status()
        token = _token_out_of_the_row(db_session)
        first = client.post(f'/public/attestation/{token}/confirm')
        assert first.status_code == status.HTTP_200_OK, first.text

        # The holder brings the equipment back through the app itself; the
        # link still in their inbox must then say so, not take a second
        # answer for a return nobody made.
        assignment = (
            db_session.query(EquipmentAssignment)
            .filter(EquipmentAssignment.item_id == eq_item.id)
            .first()
        )
        assert assignment is not None
        assignment.checked_in_at = datetime.now(UTC)
        db_session.commit()

        second = client.post(f'/public/attestation/{token}/confirm')
        assert second.status_code == status.HTTP_409_CONFLICT
        detail = _assert_sentence(
            second.json()['detail'], 'ASSIGNMENT_ALREADY_RETURNED'
        )
        assert 'already' in detail.lower()

    def test_a_reason_with_no_mapping_still_answers_through_the_catalogue(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The fallback is the door a future service reason would leave by:
        it must log the token for the developer and answer with a catalogue
        sentence — never put the token itself on the public page."""

        async def refuse(*args: Any, **kwargs: Any) -> Any:
            raise ValueError('brand_new_reason')

        monkeypatch.setattr(
            'app.modules.equipment.router_public.confirm_response', refuse
        )

        with caplog.at_level(logging.WARNING):
            refused = client.post('/public/attestation/any-token/confirm')

        assert refused.status_code == status.HTTP_400_BAD_REQUEST
        detail = _assert_sentence(refused.json()['detail'], 'ATTESTATION_REFUSED')
        assert 'brand_new_reason' not in detail
        assert any(
            'brand_new_reason' in record.getMessage() for record in caplog.records
        ), caplog.records
