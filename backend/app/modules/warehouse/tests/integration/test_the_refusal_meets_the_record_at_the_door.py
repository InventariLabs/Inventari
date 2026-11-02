"""A record standing off the document's source is refused at the entrance.

A dispatch that names a source shelf while the record it takes from stands
on another used to sail through confirmation — the reservation skips a line
that names no card, and a record that predates its card is exactly such a
line — and died mid-flight at completion, confirmed and stuck, quoting a
shelf that had never held the stock. The refusal belongs where the document
is still a draft: confirmation refuses, the record keeps standing where it
stood, and nobody has to dig a document out of CONFIRMED.

These tests hold the gate to two relations: a cardless record whose shelf
disagrees with the document's source never gets past confirmation, and a
cardless record whose shelf the door can resolve on its own (the document
names no source) still completes end to end — the gate refuses the
disagreement, not the shape.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.models.user import User


@pytest.fixture
def gate_org(h: ModuleTestHelper) -> Organization:
    org = h.create_org(
        'Door Gate Org',
        ['core', 'items', 'locations', 'categories', 'warehouse', 'approvals', 'stats'],
    )
    h.set_module_settings(org, 'approvals', {'allow_admin_self_approve': True})
    return org


@pytest.fixture
def gate_user(h: ModuleTestHelper, gate_org: Organization) -> User:
    return h.create_user(gate_org, email='door-gate@example.com')


@pytest.fixture
def gate_headers(h: ModuleTestHelper, gate_user: User) -> dict[str, str]:
    return h.get_auth_headers(gate_user)


@pytest.fixture
def gate_source(
    h: ModuleTestHelper, gate_org: Organization, gate_user: User
) -> StorageLocation:
    storage_type = h.create_storage_type(
        'Gate Warehouse', 'GATE_WAREHOUSE', organization_id=gate_org.id
    )
    return h.create_storage_location(
        gate_org, storage_type, gate_user, name='Gate Source Shelf'
    )


@pytest.fixture
def gate_elsewhere(
    h: ModuleTestHelper, gate_org: Organization, gate_user: User
) -> StorageLocation:
    storage_type = h.create_storage_type(
        'Gate Warehouse', 'GATE_WAREHOUSE', organization_id=gate_org.id
    )
    return h.create_storage_location(
        gate_org, storage_type, gate_user, name='Gate Other Shelf'
    )


@pytest.fixture
def gate_partner(
    h: ModuleTestHelper, gate_org: Organization, gate_user: User
) -> Partner:
    return h.create_partner(gate_org, gate_user, name='Gate Supplies')


def _cardless_record(
    db_session: Session,
    org_id: UUID,
    *,
    name: str,
    location_id: UUID,
    quantity: Decimal,
) -> Item:
    """The shape of anything stocked before the catalogue existed."""
    item = Item(
        name=name,
        organization_id=org_id,
        template_id=None,
        storage_location_id=location_id,
        quantity=quantity,
    )
    db_session.add(item)
    db_session.flush()
    db_session.refresh(item)
    return item


@pytest.mark.integration
class TestTheRefusalMeetsTheRecordAtTheDoor:
    """The disagreement ends at confirmation, with the document still a draft."""

    def test_confirm_refuses_a_record_standing_elsewhere(
        self,
        client: TestClient,
        gate_headers: dict[str, str],
        gate_source: StorageLocation,
        gate_elsewhere: StorageLocation,
        gate_partner: Partner,
        db_session: Session,
        gate_org: Organization,
    ) -> None:
        """A cardless record off the document's source never gets confirmed.

        The shape the finding was measured in: the reservation let the
        confirmation through, the completion refused with a shelf that had
        never held the stock, and the document stayed CONFIRMED with no way
        out. The refusal now lands on confirmation, names both shelves, and
        the document stays a draft the reader can still fix.
        """
        record = _cardless_record(
            db_session,
            gate_org.id,
            name=f'Off Shelf Out {uuid4().hex[:6]}',
            location_id=gate_elsewhere.id,
            quantity=Decimal('4'),
        )
        db_session.commit()

        created = client.post(
            '/api/v1/warehouse/documents',
            headers=gate_headers,
            json={
                'type': 'OUT',
                'partner_id': str(gate_partner.id),
                'source_location_id': str(gate_source.id),
                'target_location_id': str(gate_elsewhere.id),
                'lines': [{'item_id': str(record.id), 'expected_quantity': 2}],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = cast(str, created.json()['id'])

        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=gate_headers
        )
        assert confirm.status_code == status.HTTP_400_BAD_REQUEST, confirm.text
        assert record.name in confirm.text, 'the refusal names the record'
        assert gate_elsewhere.name in confirm.text, 'the refusal names its shelf'
        assert gate_source.name in confirm.text, 'the refusal names the source'

        shown = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=gate_headers
        )
        assert shown.status_code == status.HTTP_200_OK, shown.text
        assert shown.json()['status'] == 'DRAFT', (
            'a refused confirmation leaves the document editable'
        )

        db_session.expire_all()
        standing = db_session.get(Item, record.id)
        assert standing is not None
        assert standing.template_id is None, 'a refused confirmation adopts nothing'
        assert standing.quantity == Decimal('4'), 'a refused confirmation moves nothing'
        assert standing.storage_location_id == gate_elsewhere.id

    def test_a_document_without_a_source_still_takes_the_record_it_stands_on(
        self,
        client: TestClient,
        gate_headers: dict[str, str],
        gate_elsewhere: StorageLocation,
        db_session: Session,
        gate_org: Organization,
    ) -> None:
        """No source named means no disagreement — the door takes from the shelf.

        The gate refuses a disagreement between two named shelves; a
        document that names only the record's own shelf resolves both the
        opening balance and the taking to it, and completes as before.
        """
        record = _cardless_record(
            db_session,
            gate_org.id,
            name=f'No Source Scrap {uuid4().hex[:6]}',
            location_id=gate_elsewhere.id,
            quantity=Decimal('5'),
        )
        db_session.commit()

        created = client.post(
            '/api/v1/warehouse/documents',
            headers=gate_headers,
            json={
                'type': 'SCRAP',
                'reason_code': 'DAMAGED',
                'lines': [{'item_id': str(record.id), 'expected_quantity': 2}],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = cast(str, created.json()['id'])

        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=gate_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=gate_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text

        db_session.expire_all()
        scrapped = db_session.get(Item, record.id)
        assert scrapped is not None and scrapped.template_id is not None, (
            'the scrap bound the record to a card'
        )
        assert scrapped.quantity == Decimal('3'), 'the record lost what left it'
