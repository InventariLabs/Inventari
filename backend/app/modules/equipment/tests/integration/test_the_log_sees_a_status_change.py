"""Taking an asset out of service is a fact about the object.

It is not a note somebody edited: after it, the laptop is not to be issued
to anybody, and the register says so. That belongs beside the handover in
the organization log, and it was written only into the item's own history.

The batch shape is the second half. One row per asset, with a flag saying
it came from a batch -- the shape the core settled on for its own bulk
edits, for the reason it wrote down there: the log is not supposed to depend
on which button somebody pressed. Fifty assets retired at once and fifty
retired one at a time leave the same fifty rows.
"""

from __future__ import annotations

import json
import uuid
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.audit_log import AuditLog
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation

EQUIPMENT_URL = '/api/v1/equipment'


@pytest.fixture
def eq_second_location(
    db_session: Session, eq_org: Organization, eq_storage_location: StorageLocation
) -> StorageLocation:
    location = StorageLocation(
        organization_id=eq_org.id,
        created_by=eq_storage_location.created_by,
        storage_type_id=eq_storage_location.storage_type_id,
        name='Cage Two',
    )
    db_session.add(location)
    db_session.commit()
    db_session.refresh(location)
    return location


@pytest.fixture
def eq_second_item(
    db_session: Session,
    eq_org: Organization,
    eq_storage_location: StorageLocation,
    eq_category: Category,
) -> Item:
    item = Item(
        name='ThinkPad X1 Carbon',
        organization_id=eq_org.id,
        storage_location_id=eq_storage_location.id,
        category_id=eq_category.id,
        quantity=1,
        meta_data={
            'equipment': {'serial_number': 'SN-002', 'equipment_status': 'AVAILABLE'}
        },
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def _entries(db_session: Session, org_id: UUID) -> list[AuditLog]:
    return list(
        db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == org_id,
                AuditLog.target_type == 'equipment_asset',
            )
            .order_by(AuditLog.created_at.asc())
        ).all()
    )


@pytest.mark.integration
class TestTheLogSeesAStatusChange:
    def test_retiring_one_asset_says_which_and_from_what(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_item: Item,
        db_session: Session,
    ) -> None:
        response = client.post(
            f'{EQUIPMENT_URL}/items/{eq_item.id}/retire', headers=eq_auth_headers
        )
        assert response.status_code == 204, response.text

        db_session.expire_all()
        (entry,) = _entries(db_session, eq_org.id)
        assert entry.snapshot is not None
        assert entry.snapshot['serial_number'] == 'SN-001'
        assert entry.snapshot['before'] == {'equipment_status': 'AVAILABLE'}
        assert entry.snapshot['after'] == {'equipment_status': 'RETIRED'}
        # One asset retired on its own is not a batch.
        assert entry.meta_data is None

    def test_a_batch_leaves_one_row_per_asset_and_says_it_was_a_batch(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_item: Item,
        eq_second_item: Item,
        db_session: Session,
    ) -> None:
        response = client.post(
            f'{EQUIPMENT_URL}/items/bulk-retire',
            headers=eq_auth_headers,
            json=[str(eq_item.id), str(eq_second_item.id)],
        )
        assert response.status_code == 200, response.text
        assert response.json()['retired'] == 2

        db_session.expire_all()
        entries = _entries(db_session, eq_org.id)
        assert len(entries) == 2
        serials = {(e.snapshot or {}).get('serial_number') for e in entries}
        assert serials == {'SN-001', 'SN-002'}
        assert all((e.meta_data or {}).get('bulk') is True for e in entries)

    def test_a_status_change_through_the_bulk_route_is_recorded_too(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """The screen sends a single asset down the same route as a batch."""
        response = client.patch(
            f'{EQUIPMENT_URL}/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id)],
                'action': 'change_status',
                'data': {'status': 'MAINTENANCE'},
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()['updated'] == 1

        db_session.expire_all()
        (entry,) = _entries(db_session, eq_org.id)
        assert entry.snapshot is not None
        assert entry.snapshot['after'] == {'equipment_status': 'MAINTENANCE'}
        assert entry.meta_data is None

    def test_an_asset_nobody_touched_leaves_nothing(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """The control: a refused transition must not write an entry."""
        response = client.patch(
            f'{EQUIPMENT_URL}/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(uuid.uuid4())],
                'action': 'change_status',
                'data': {'status': 'MAINTENANCE'},
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()['updated'] == 0

        db_session.expire_all()
        assert _entries(db_session, eq_org.id) == []

    def test_an_assignment_through_the_bulk_route_names_the_holder(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_item: Item,
        db_session: Session,
    ) -> None:
        response = client.patch(
            f'{EQUIPMENT_URL}/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id)],
                'action': 'assign_to',
                'data': {'assigned_to_name': 'Ewa Nowak'},
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()['updated'] == 1

        db_session.expire_all()
        entries = db_session.scalars(
            select(AuditLog).where(
                AuditLog.organization_id == eq_org.id,
                AuditLog.target_type == 'equipment_assignment',
            )
        ).all()
        (entry,) = entries
        assert entry.snapshot is not None
        assert entry.snapshot['after'] == {'assigned_to': 'Ewa Nowak'}

    def test_a_move_through_the_bulk_route_is_recorded_by_the_core(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_item: Item,
        eq_second_location: StorageLocation,
        db_session: Session,
    ) -> None:
        response = client.patch(
            f'{EQUIPMENT_URL}/assets/bulk',
            headers=eq_auth_headers,
            json={
                'item_ids': [str(eq_item.id)],
                'action': 'change_location',
                'data': {'location_id': str(eq_second_location.id)},
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()['updated'] == 1

        db_session.expire_all()
        moved = db_session.scalars(
            select(AuditLog).where(
                AuditLog.organization_id == eq_org.id,
                AuditLog.target_id == eq_item.id,
            )
        ).all()
        assert moved, 'the move left no journal entry'
        assert any(
            str(eq_second_location.id) in json.dumps(m.snapshot, default=str)
            or eq_second_location.name in json.dumps(m.snapshot, default=str)
            for m in moved
        ), [m.snapshot for m in moved]
