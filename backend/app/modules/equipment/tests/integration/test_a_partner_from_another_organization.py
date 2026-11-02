"""Who the laptop went to, and who serviced it, are references like any other.

Both are partner ids arriving in a payload, and both were written straight
onto the row. Four lines above the assignment write there is already a guard
doing exactly the right thing for ``checkout_location_id``, with a comment
explaining that a foreign key is not tenant-scoped -- and the field beside it
had none. Same function, two rules.

Nothing of the stranger's data comes back out: the screens show the name of a
partner the reader's own organisation cannot resolve. What is left behind is a
reference to a row somebody else may delete, inside a record meant to answer
"who has it" for years.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.user import User
from app.modules.equipment.models import (
    EquipmentAssignment,
    EquipmentMaintenanceLog,
)


@pytest.fixture
def their_partner_id(h: ModuleTestHelper) -> str:
    """A partner that exists, and belongs to somebody else."""
    theirs = h.create_org('Strangers Inc', ['core', 'items', 'locations'])
    their_user = h.create_user(theirs, email='stranger@example.com')
    partner = h.create_partner(theirs, their_user, name='Their Service Desk')
    return str(partner.id)


@pytest.mark.integration
class TestHandingAnAssetOver:
    def test_an_assignee_from_another_organization_is_refused(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        their_partner_id: str,
    ) -> None:
        response = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Alice',
                'assignee_partner_id': their_partner_id,
            },
        )
        assert response.status_code == 400, response.text

    def test_the_asset_was_not_handed_over(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        their_partner_id: str,
        db_session: Session,
    ) -> None:
        client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Alice',
                'assignee_partner_id': their_partner_id,
            },
        )
        db_session.expire_all()
        rows = db_session.scalars(
            select(EquipmentAssignment).where(EquipmentAssignment.item_id == eq_item.id)
        ).all()
        assert not rows

    def test_our_own_partner_still_goes_through(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        h: ModuleTestHelper,
        eq_org: Organization,
        eq_user: User,
    ) -> None:
        partner = h.create_partner(eq_org, eq_user, name='Our Service Desk')
        response = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': 'Alice',
                'assignee_partner_id': str(partner.id),
            },
        )
        assert response.status_code == 201, response.text


@pytest.mark.integration
class TestRecordingAService:
    def _payload(self, item: Item, partner_id: str | None) -> dict[str, str]:
        payload: dict[str, str] = {
            'item_id': str(item.id),
            'maintenance_type': 'REPAIR',
            'title': 'Fan replacement',
            'performed_at': '2026-08-30',
        }
        if partner_id is not None:
            payload['service_partner_id'] = partner_id
        return payload

    def test_a_service_partner_from_another_organization_is_refused(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        their_partner_id: str,
    ) -> None:
        response = client.post(
            '/api/v1/equipment/maintenance',
            headers=eq_auth_headers,
            json=self._payload(eq_item, their_partner_id),
        )
        assert response.status_code == 400, response.text

    def test_nothing_was_written(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        their_partner_id: str,
        db_session: Session,
    ) -> None:
        client.post(
            '/api/v1/equipment/maintenance',
            headers=eq_auth_headers,
            json=self._payload(eq_item, their_partner_id),
        )
        db_session.expire_all()
        rows = db_session.scalars(
            select(EquipmentMaintenanceLog).where(
                EquipmentMaintenanceLog.item_id == eq_item.id
            )
        ).all()
        assert not rows

    def test_our_own_partner_still_goes_through(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        h: ModuleTestHelper,
        eq_org: Organization,
        eq_user: User,
    ) -> None:
        partner = h.create_partner(eq_org, eq_user, name='Our Service Desk')
        response = client.post(
            '/api/v1/equipment/maintenance',
            headers=eq_auth_headers,
            json=self._payload(eq_item, str(partner.id)),
        )
        assert response.status_code == 201, response.text


@pytest.mark.integration
class TestEditingAServiceRecord:
    def test_moving_the_partner_to_another_organization_is_refused(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        their_partner_id: str,
    ) -> None:
        created = client.post(
            '/api/v1/equipment/maintenance',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'maintenance_type': 'REPAIR',
                'title': 'Fan replacement',
                'performed_at': '2026-08-30',
            },
        )
        assert created.status_code == 201, created.text
        log_id = created.json()['id']

        response = client.put(
            f'/api/v1/equipment/maintenance/{log_id}',
            headers=eq_auth_headers,
            json={'service_partner_id': their_partner_id},
        )
        assert response.status_code == 400, response.text

        after = client.get(
            f'/api/v1/equipment/maintenance/item/{eq_item.id}',
            headers=eq_auth_headers,
        )
        assert after.json()['items'][0]['service_partner_id'] is None
