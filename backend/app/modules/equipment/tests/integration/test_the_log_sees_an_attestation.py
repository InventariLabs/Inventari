"""An attestation puts a question to everybody who holds something.

Launching one sends a link to every assignee in scope; cancelling one voids
every link already sitting in somebody's inbox. Both were acts nothing
outside this module could see -- the campaign screen showed a status, and
the organization log showed nothing at all, so "who asked the whole company
to confirm their kit, and when did we call it off" had no answer.

A campaign deleted before launch is the deletion case: it is a draft, so
there are no answers to preserve, and the record of what was set up goes
with it unless the log keeps it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.organization import Organization

CAMPAIGNS_URL = '/api/v1/equipment/campaigns'


def _entries(db_session: Session, org_id: UUID) -> list[AuditLog]:
    return list(
        db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == org_id,
                AuditLog.target_type == 'equipment_attestation',
            )
            .order_by(AuditLog.created_at.asc())
        ).all()
    )


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
    deadline = (datetime.now(UTC) + timedelta(days=14)).isoformat()
    response = client.post(
        CAMPAIGNS_URL,
        headers=headers,
        json={'name': 'Q3 attestation', 'deadline': deadline},
    )
    assert response.status_code == 201, response.text
    return str(response.json()['id'])


@pytest.mark.integration
class TestTheLogSeesAnAttestation:
    def test_setting_one_up_and_sending_it_out_are_two_entries(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_item: Item,
        db_session: Session,
    ) -> None:
        _checkout(client, eq_auth_headers, eq_item.id)
        campaign_id = _campaign(client, eq_auth_headers)

        launched = client.post(
            f'{CAMPAIGNS_URL}/{campaign_id}/launch', headers=eq_auth_headers
        )
        assert launched.status_code == 200, launched.text

        db_session.expire_all()
        created, sent = _entries(db_session, eq_org.id)
        assert created.action == 'CREATE'
        assert created.snapshot is not None
        assert created.snapshot['name'] == 'Q3 attestation'
        assert created.snapshot['status'] == 'DRAFT'

        assert sent.action == 'UPDATE'
        assert sent.snapshot is not None
        assert sent.snapshot['old_status'] == 'DRAFT'
        assert sent.snapshot['new_status'] == 'ACTIVE'
        # How far it went: an attestation nobody could be reached about is a
        # different event from one that went to everybody.
        assert sent.snapshot['responses_created'] == 1

    def test_calling_it_off_says_what_it_was(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_item: Item,
        db_session: Session,
    ) -> None:
        _checkout(client, eq_auth_headers, eq_item.id)
        campaign_id = _campaign(client, eq_auth_headers)
        client.post(f'{CAMPAIGNS_URL}/{campaign_id}/launch', headers=eq_auth_headers)

        cancelled = client.post(
            f'{CAMPAIGNS_URL}/{campaign_id}/cancel', headers=eq_auth_headers
        )
        assert cancelled.status_code == 200, cancelled.text

        db_session.expire_all()
        entry = _entries(db_session, eq_org.id)[-1]
        assert entry.snapshot is not None
        assert entry.snapshot['old_status'] == 'ACTIVE'
        assert entry.snapshot['new_status'] == 'CANCELLED'

    def test_deleting_a_draft_keeps_what_was_set_up(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        db_session: Session,
    ) -> None:
        campaign_id = _campaign(client, eq_auth_headers)

        deleted = client.delete(
            f'{CAMPAIGNS_URL}/{campaign_id}', headers=eq_auth_headers
        )
        assert deleted.status_code == 204, deleted.text

        db_session.expire_all()
        _created, removed = _entries(db_session, eq_org.id)
        assert removed.action == 'HARD_DELETE'
        assert removed.snapshot is not None
        assert removed.snapshot['name'] == 'Q3 attestation'
        assert removed.snapshot['deadline'] is not None
