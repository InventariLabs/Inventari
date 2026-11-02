"""Handing a laptop over is an act the organization log should hold.

Checkout and checkin wrote only to the item's own history. In asset
management "who has the laptop" is the central material responsibility, and
the screen that answers "what happened in this organization" could not
answer it — the journal's own contract says a state-changing act on a record
writes to both ledgers, and this one wrote to one.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.organization import Organization


def _entries(db_session: Session, org_id: UUID) -> list[AuditLog]:
    return list(
        db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == org_id,
                AuditLog.target_type == 'equipment_assignment',
            )
            .order_by(AuditLog.created_at.asc())
        ).all()
    )


@pytest.mark.integration
class TestTheLogSeesAHandover:
    def test_checkout_and_checkin_both_reach_the_log(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_item: Item,
        db_session: Session,
    ) -> None:
        checkout = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Alice'},
        )
        assert checkout.status_code == 201, checkout.text
        assignment_id = checkout.json()['id']

        checkin = client.post(
            f'/api/v1/equipment/assignments/{assignment_id}/checkin',
            headers=eq_auth_headers,
            json={'checkin_condition': 'GOOD'},
        )
        assert checkin.status_code == 200, checkin.text

        db_session.expire_all()
        entries = _entries(db_session, eq_org.id)
        assert len(entries) == 2
        out, back = entries[0].snapshot, entries[1].snapshot
        assert out is not None and back is not None
        assert out['after']['assigned_to'] == 'Alice'
        assert out['name'] == eq_item.name
        assert back['after']['assigned_to'] is None

    def test_the_entry_names_the_unit_and_not_only_the_model(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """A fleet is ten models and sixty units.

        "ThinkPad X1 Carbon" four times over is a row nobody can act on: the
        reader has to go back into the app to work out which of the four the
        entry meant. The serial is what the label on the case says.
        """
        checkout = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={'item_id': str(eq_item.id), 'assigned_to_name': 'Alice'},
        )
        assignment_id = checkout.json()['id']
        client.post(
            f'/api/v1/equipment/assignments/{assignment_id}/checkin',
            headers=eq_auth_headers,
            json={'checkin_condition': 'GOOD'},
        )

        db_session.expire_all()
        for entry in _entries(db_session, eq_org.id):
            assert entry.snapshot is not None
            assert entry.snapshot['name'] == 'ThinkPad X1 Carbon'
            assert entry.snapshot['serial_number'] == 'SN-001'
