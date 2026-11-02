"""A repair booked against an asset is an act, so the log holds it.

Maintenance wrote to the item's own history and stopped there. That answers
"what happened to this laptop"; it does not answer "which machines keep
going back to the shop, and what have they cost us" -- a question that is
about the fleet rather than about any one unit, and the only screen that
could answer it is the organization log.

Deleting a maintenance log is the sharper case: the row that would have
explained the repair is the one being removed, which is why every
irreversible deletion earns an entry regardless of what it was about.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.organization import Organization

MAINTENANCE_URL = '/api/v1/equipment/maintenance'


def _entries(db_session: Session, org_id: UUID) -> list[AuditLog]:
    return list(
        db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == org_id,
                AuditLog.target_type == 'equipment_maintenance',
            )
            .order_by(AuditLog.created_at.asc())
        ).all()
    )


def _book_repair(
    client: TestClient, headers: dict[str, str], item: Item, **overrides: object
) -> str:
    payload: dict[str, object] = {
        'item_id': str(item.id),
        'maintenance_type': 'REPAIR',
        'title': 'Replaced the keyboard',
        'cost': '249.99',
        'currency': 'PLN',
        'performed_at': str(date.today()),
    }
    payload.update(overrides)
    response = client.post(MAINTENANCE_URL, headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return str(response.json()['id'])


@pytest.mark.integration
class TestTheLogSeesARepair:
    def test_booking_a_repair_names_the_asset_and_the_cost(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_item: Item,
        db_session: Session,
    ) -> None:
        _book_repair(client, eq_auth_headers, eq_item)

        db_session.expire_all()
        (entry,) = _entries(db_session, eq_org.id)
        assert entry.action == 'CREATE'
        assert entry.snapshot is not None
        assert entry.snapshot['name'] == 'ThinkPad X1 Carbon'
        assert entry.snapshot['serial_number'] == 'SN-001'
        # The row is about the repair, so the asset reaches the page as a
        # reference: the id rides with the name it had at write time, or the
        # screen prints "Produkt: <uuid>" for a reader with no way back.
        assert entry.snapshot['item_id'] == str(eq_item.id)
        assert entry.snapshot['item_name'] == 'ThinkPad X1 Carbon'
        assert entry.snapshot['title'] == 'Replaced the keyboard'
        assert entry.snapshot['cost'] == '249.99'
        assert entry.snapshot['currency'] == 'PLN'

    def test_an_edit_says_only_what_moved(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_item: Item,
        db_session: Session,
    ) -> None:
        """A row that prints every field the form posted hides the one change."""
        log_id = _book_repair(client, eq_auth_headers, eq_item)

        response = client.put(
            f'{MAINTENANCE_URL}/{log_id}',
            headers=eq_auth_headers,
            json={'cost': '399.00'},
        )
        assert response.status_code == 200, response.text

        db_session.expire_all()
        _created, edited = _entries(db_session, eq_org.id)
        assert edited.action == 'UPDATE'
        assert edited.snapshot is not None
        assert edited.snapshot['before'] == {'cost': '249.99'}
        assert edited.snapshot['after'] == {'cost': '399.00'}
        assert edited.snapshot['serial_number'] == 'SN-001'

    def test_an_edit_that_changes_nothing_writes_nothing(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_item: Item,
        db_session: Session,
    ) -> None:
        log_id = _book_repair(client, eq_auth_headers, eq_item)

        response = client.put(
            f'{MAINTENANCE_URL}/{log_id}',
            headers=eq_auth_headers,
            json={'cost': '249.99'},
        )
        assert response.status_code == 200, response.text

        db_session.expire_all()
        assert len(_entries(db_session, eq_org.id)) == 1

    def test_deleting_the_repair_keeps_the_account_of_it(
        self,
        client: TestClient,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_item: Item,
        db_session: Session,
    ) -> None:
        log_id = _book_repair(client, eq_auth_headers, eq_item)

        response = client.delete(f'{MAINTENANCE_URL}/{log_id}', headers=eq_auth_headers)
        assert response.status_code == 204, response.text

        db_session.expire_all()
        _created, removed = _entries(db_session, eq_org.id)
        assert removed.action == 'HARD_DELETE'
        assert removed.snapshot is not None
        # Everything the deleted row said, because the row itself is gone.
        assert removed.snapshot['title'] == 'Replaced the keyboard'
        assert removed.snapshot['cost'] == '249.99'
        assert removed.snapshot['name'] == 'ThinkPad X1 Carbon'
