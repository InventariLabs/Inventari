"""List overdue assignments endpoint.

The endpoint was missing: ``OverdueAssignmentItem`` /
``OverdueAssignmentListResponse`` were declared in the schemas, but no
service function or router wired them. ``GET /equipment/assignments/overdue``
now returns those assignments whose ``expected_return_at`` is in the past
and have not yet been checked in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.storage_location import StorageLocation


def _checkout(
    client: TestClient,
    headers: dict[str, str],
    item_id: str,
    *,
    name: str = 'Alice',
    expected_return_at: str | None = None,
) -> str:
    payload: dict[str, object] = {
        'item_id': item_id,
        'assigned_to_name': name,
    }
    if expected_return_at is not None:
        payload['expected_return_at'] = expected_return_at
    resp = client.post(
        '/api/v1/equipment/assignments',
        headers=headers,
        json=payload,
    )
    resp.raise_for_status()
    return str(resp.json()['id'])


def _force_expected_return(
    db_session: Session, assignment_id: str, when: datetime
) -> None:
    from app.modules.equipment.models import EquipmentAssignment

    a = (
        db_session.query(EquipmentAssignment)
        .filter(EquipmentAssignment.id == assignment_id)
        .one()
    )
    a.expected_return_at = when
    db_session.commit()


@pytest.mark.integration
class TestOverdueAssignmentsEndpoint:
    """Overdue assignments are returned with ``days_overdue``."""

    def test_no_overdue_when_nothing_is_past_due(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
    ) -> None:
        _checkout(client, eq_auth_headers, str(eq_item.id))

        resp = client.get(
            '/api/v1/equipment/assignments/overdue', headers=eq_auth_headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body['total'] == 0
        assert body['items'] == []

    def test_overdue_assignment_is_listed_with_days_overdue(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        assignment_id = _checkout(client, eq_auth_headers, str(eq_item.id))
        seven_days_ago = datetime.now(UTC) - timedelta(days=7)
        _force_expected_return(db_session, assignment_id, seven_days_ago)

        resp = client.get(
            '/api/v1/equipment/assignments/overdue', headers=eq_auth_headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body['total'] == 1
        assert len(body['items']) == 1

        item = body['items'][0]
        assert item['assignment_id'] == assignment_id
        assert item['item_id'] == str(eq_item.id)
        assert item['days_overdue'] >= 7
        assert item['holder_name'] == 'Alice'
        assert item['holder_kind'] == 'person'

    def test_a_deployed_asset_names_the_place_it_stands_in(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        eq_storage_location: StorageLocation,
    ) -> None:
        """A deployment can carry a planned return date too, and the row
        still answers "who or what holds it" — with the place, and with
        the kind that tells the reader to word it as one."""
        three_days_ago = datetime.now(UTC) - timedelta(days=3)
        resp = client.post(
            '/api/v1/equipment/assignments',
            headers=eq_auth_headers,
            json={
                'item_id': str(eq_item.id),
                'assigned_to_name': '',
                'checkout_location_id': str(eq_storage_location.id),
                'expected_return_at': three_days_ago.isoformat(),
            },
        )
        assert resp.status_code == 201, resp.text

        listing = client.get(
            '/api/v1/equipment/assignments/overdue', headers=eq_auth_headers
        )
        assert listing.status_code == 200, listing.text
        item = listing.json()['items'][0]
        assert item['holder_name'] == 'Server Room A'
        assert item['holder_kind'] == 'location'
        assert item['assigned_to_email'] is None

    def test_checkedin_assignment_is_excluded(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """A returned assignment, even past its expected_return_at, is excluded."""
        assignment_id = _checkout(client, eq_auth_headers, str(eq_item.id))
        seven_days_ago = datetime.now(UTC) - timedelta(days=7)
        _force_expected_return(db_session, assignment_id, seven_days_ago)

        # Check it back in.
        resp = client.post(
            f'/api/v1/equipment/assignments/{assignment_id}/checkin',
            headers=eq_auth_headers,
            json={'checkin_condition': 'GOOD'},
        )
        resp.raise_for_status()

        resp = client.get(
            '/api/v1/equipment/assignments/overdue', headers=eq_auth_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()['total'] == 0

    def test_pagination_limit_offset(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        # Create two overdue + one on-time assignments.
        on_time_id = _checkout(client, eq_auth_headers, str(eq_item.id), name='OnTime')

        # Two more overdue on the same item is impossible (one active
        # assignment per item). Use two new items.
        from app.core.testing import ModuleTestHelper
        from app.models.category import Category
        from app.models.item import Item as ItemModel

        h = ModuleTestHelper(db_session)
        cat = db_session.query(Category).filter(Category.code == 'LAPTOP').one()
        h.create_storage_type('IT Storage 3', 'IT_STORAGE_3')
        ids: list[str] = []
        for i in range(2):
            other = ItemModel(
                name=f'Laptop-{i}',
                organization_id=eq_item.organization_id,
                storage_location_id=eq_item.storage_location_id,
                category_id=cat.id,
                quantity=1,
                meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
            )
            db_session.add(other)
            db_session.commit()
            db_session.refresh(other)
            ids.append(_checkout(client, eq_auth_headers, str(other.id)))
        # Mark all three as overdue (one on-time + two overdue).
        eight_days_ago = datetime.now(UTC) - timedelta(days=8)
        for aid in [on_time_id] + ids:
            _force_expected_return(db_session, aid, eight_days_ago)

        # Default limit=50 returns all 3.
        resp = client.get(
            '/api/v1/equipment/assignments/overdue', headers=eq_auth_headers
        )
        body = resp.json()
        assert resp.status_code == 200
        assert body['total'] == 3

        # limit=2 -> has_more True
        resp = client.get(
            '/api/v1/equipment/assignments/overdue?limit=2',
            headers=eq_auth_headers,
        )
        body = resp.json()
        assert body['total'] == 3
        assert len(body['items']) == 2
        assert body['has_more'] is True

        # limit=2&offset=2 -> the last one
        resp = client.get(
            '/api/v1/equipment/assignments/overdue?limit=2&offset=2',
            headers=eq_auth_headers,
        )
        body = resp.json()
        assert body['total'] == 3
        assert len(body['items']) == 1
        assert body['has_more'] is False

    def test_limit_validation(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
    ) -> None:
        assert (
            client.get(
                '/api/v1/equipment/assignments/overdue?limit=0',
                headers=eq_auth_headers,
            ).status_code
            == 422
        )

    def test_cross_org_isolation(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """An org-A overdue assignment must not appear under an org-B caller's session."""
        from app.core.testing import ModuleTestHelper
        from app.models.category import Category
        from app.models.item import Item as ItemModel

        h = ModuleTestHelper(db_session)
        other_org = h.create_org(
            'Other Equipment Org',
            ['core', 'items', 'locations', 'categories', 'equipment'],
        )
        other_user = h.create_user(other_org, email='overdue-other@test.com')
        other_st = h.create_storage_type('IT Other', 'IT_OTHER')
        other_loc = h.create_storage_location(
            other_org, other_st, other_user, name='Other Loc'
        )
        cat = Category(
            name='Other Laptop',
            code='OTHER_LAPTOP',
            context_tag='equipment',
            organization_id=None,
            field_definitions=[],
        )
        db_session.add(cat)
        db_session.commit()
        db_session.refresh(cat)
        other_item = ItemModel(
            name='Foreign Laptop',
            organization_id=other_org.id,
            storage_location_id=other_loc.id,
            category_id=cat.id,
            quantity=1,
            meta_data={'equipment': {'equipment_status': 'AVAILABLE'}},
        )
        db_session.add(other_item)
        db_session.commit()
        db_session.refresh(other_item)

        other_auth = h.get_auth_headers(other_user)
        _checkout(client, other_auth, str(other_item.id), name='Bob')
        from app.modules.equipment.models import EquipmentAssignment

        a = (
            db_session.query(EquipmentAssignment)
            .filter(EquipmentAssignment.item_id == other_item.id)
            .one()
        )
        a.expected_return_at = datetime.now(UTC) - timedelta(days=3)
        db_session.commit()

        # Switch back to the eq_auth_headers caller's perspective.
        resp = client.get(
            '/api/v1/equipment/assignments/overdue', headers=eq_auth_headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # The other org's overdue row must not leak.
        for item in body['items']:
            assert uuid4() != uuid4() or item['item_id'] != str(other_item.id)
            assert item['item_id'] != str(other_item.id)
