"""A scanning session can be handed to another person with its scans.

One person picks half a dispatch and goes home; a colleague finishes it. The
only road used to be releasing the session, which is a cancel and throws the
holder's scans away. Taking over moves the session itself: the scans stay, the
new holder continues from them, the previous holder's screen is refused with
the new holder's name, and both names are in the audit log.
"""

import uuid
from typing import cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import WmsPickLine, WmsPickSession


def _confirmed_in(
    client: TestClient,
    headers: dict[str, str],
    target: StorageLocation,
    partner: Partner,
    template: ProductTemplate,
    quantity: int = 10,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(target.id),
            'lines': [
                {'product_template_id': str(template.id), 'expected_quantity': quantity}
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    return doc_id


def _confirmed_out(
    client: TestClient,
    headers: dict[str, str],
    source: StorageLocation,
    target: StorageLocation,
    partner: Partner,
    template: ProductTemplate,
    item: Item,
    quantity: int = 5,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner.id),
            'source_location_id': str(source.id),
            'target_location_id': str(target.id),
            'lines': [
                {
                    'item_id': str(item.id),
                    'product_template_id': str(template.id),
                    'expected_quantity': quantity,
                }
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    return doc_id


def _handover_entries(db_session: Session, doc_id: str) -> list[AuditLog]:
    db_session.expire_all()
    return [
        entry
        for entry in db_session.scalars(
            select(AuditLog).where(AuditLog.target_id == uuid.UUID(doc_id))
        ).all()
        if (entry.snapshot or {}).get('wms_session_handed_over_to')
    ]


@pytest.mark.integration
class TestReceivingSessionTakeover:
    def test_colleague_takes_over_and_continues_from_the_scans(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _confirmed_in(
            client,
            doc_auth_headers,
            doc_target_location,
            doc_partner,
            doc_template,
        )
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        assert start.status_code == status.HTTP_201_CREATED, start.text
        session_id = start.json()['id']
        scan = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 4},
        )
        assert scan.status_code == status.HTTP_200_OK, scan.text

        colleague = h.create_user(doc_org, email='colleague@example.com')
        colleague_headers = h.get_auth_headers(colleague)
        base = f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}'

        taken = client.post(f'{base}/take-over', headers=colleague_headers)
        assert taken.status_code == status.HTTP_200_OK, taken.text
        assert taken.json()['id'] == session_id
        assert taken.json()['assigned_to'] == str(colleague.id)

        # The scans went with the session: the colleague carries on from 4.
        more = client.post(
            f'{base}/scan',
            headers=colleague_headers,
            json={'barcode': doc_template.barcode, 'quantity': 3},
        )
        assert more.status_code == status.HTTP_200_OK, more.text
        db_session.expire_all()
        line = db_session.scalars(
            select(WmsPickLine).where(WmsPickLine.session_id == uuid.UUID(session_id))
        ).one()
        assert line.picked_quantity == 7

        # The previous holder's screen is refused, and the refusal names who
        # holds the session now.
        previous = client.post(
            f'{base}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 1},
        )
        assert previous.status_code == status.HTTP_409_CONFLICT
        detail = previous.json()['detail']
        assert detail['code'] == 'SESSION_HELD_BY_OTHER_USER'
        assert detail['held_by'] == 'Colleague'
        # The sentence a stale screen shows is the handover one, not the
        # start refusal: it has to say its scans stop now.
        assert detail['message'] == (
            'This session is now held by Colleague; '
            'scans are no longer accepted from here.'
        )

        # The previous holder's still-open screen keeps a Cancel session
        # button; pressing it must not cancel the colleague's session, or
        # the scans the handover just kept are thrown away.
        stale_cancel = client.post(f'{base}/cancel', headers=doc_auth_headers)
        assert stale_cancel.status_code == status.HTTP_409_CONFLICT
        stale_detail = stale_cancel.json()['detail']
        assert stale_detail['code'] == 'SESSION_HELD_BY_OTHER_USER'
        assert stale_detail['held_by'] == 'Colleague'

        db_session.expire_all()
        still_active = db_session.get(WmsPickSession, uuid.UUID(session_id))
        assert still_active is not None
        assert still_active.status == 'active'
        line = db_session.scalars(
            select(WmsPickLine).where(WmsPickLine.session_id == uuid.UUID(session_id))
        ).one()
        assert line.picked_quantity == 7

        entries = _handover_entries(db_session, doc_id)
        assert len(entries) == 1
        snapshot = entries[0].snapshot or {}
        assert snapshot['wms_session_id'] == session_id
        assert snapshot['wms_session_handed_over_to'] == 'Colleague'
        assert snapshot['wms_session_handed_over_from']
        assert entries[0].user_id == colleague.id

    def test_taking_over_ones_own_session_changes_nothing(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _confirmed_in(
            client,
            doc_auth_headers,
            doc_target_location,
            doc_partner,
            doc_template,
        )
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']
        again = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/take-over',
            headers=doc_auth_headers,
        )
        assert again.status_code == status.HTTP_200_OK, again.text
        assert _handover_entries(db_session, doc_id) == []

    def test_a_session_under_another_document_is_not_found(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _confirmed_in(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        other_id = _confirmed_in(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        session_id = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        ).json()['id']
        colleague = h.create_user(doc_org, email='colleague2@example.com')
        resp = client.post(
            f'/api/v1/warehouse/documents/{other_id}/receiving/{session_id}/take-over',
            headers=h.get_auth_headers(colleague),
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_a_closed_session_cannot_be_taken_over(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _confirmed_in(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        session_id = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        ).json()['id']
        cancel = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/cancel',
            headers=doc_auth_headers,
        )
        assert cancel.status_code == status.HTTP_204_NO_CONTENT
        colleague = h.create_user(doc_org, email='colleague3@example.com')
        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/take-over',
            headers=h.get_auth_headers(colleague),
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()['detail']['message'] == (
            'The active session was not found. It may have been completed or cancelled.'
        )


@pytest.mark.integration
class TestPickingSessionTakeover:
    def test_colleague_takes_over_a_picking_session_with_its_scans(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        stocked = client.post(
            '/api/v1/items',
            headers=doc_auth_headers,
            json={
                'name': doc_template.name,
                'barcode': doc_template.barcode,
                'location_id': str(doc_source_location.id),
                'quantity': 20,
            },
        )
        assert stocked.status_code == status.HTTP_201_CREATED, stocked.text
        item = db_session.get(Item, uuid.UUID(stocked.json()['id']))
        assert item is not None
        doc_id = _confirmed_out(
            client,
            doc_auth_headers,
            doc_source_location,
            doc_target_location,
            doc_partner,
            doc_template,
            item,
        )
        session_id = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        ).json()['id']
        base = f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}'
        first = client.post(
            f'{base}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 2},
        )
        assert first.status_code == status.HTTP_200_OK, first.text

        colleague = h.create_user(doc_org, email='picker-two@example.com')
        colleague_headers = h.get_auth_headers(colleague)
        taken = client.post(f'{base}/take-over', headers=colleague_headers)
        assert taken.status_code == status.HTTP_200_OK, taken.text
        assert taken.json()['assigned_to'] == str(colleague.id)

        rest = client.post(
            f'{base}/scan',
            headers=colleague_headers,
            json={'barcode': doc_template.barcode, 'quantity': 2},
        )
        assert rest.status_code == status.HTTP_200_OK, rest.text
        assert rest.json()['picked_quantity'] == 4

        refused = client.post(
            f'{base}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 1},
        )
        assert refused.status_code == status.HTTP_409_CONFLICT
        detail = refused.json()['detail']
        assert detail['held_by'] == 'Picker-Two'
        # The sentence a stale screen shows is the handover one, not the
        # start refusal: it has to say its scans stop now.
        assert detail['message'] == (
            'This session is now held by Picker-Two; '
            'scans are no longer accepted from here.'
        )

        # The previous holder's still-open screen keeps a Cancel session
        # button; pressing it must not cancel the colleague's session, or
        # the scans the handover just kept are thrown away.
        stale_cancel = client.post(f'{base}/cancel', headers=doc_auth_headers)
        assert stale_cancel.status_code == status.HTTP_409_CONFLICT
        assert stale_cancel.json()['detail']['held_by'] == 'Picker-Two'

        db_session.expire_all()
        session = db_session.get(WmsPickSession, uuid.UUID(session_id))
        assert session is not None
        assert session.assigned_to == colleague.id
        assert session.status == 'active'
        line = db_session.scalars(
            select(WmsPickLine).where(WmsPickLine.session_id == uuid.UUID(session_id))
        ).one()
        assert line.picked_quantity == 4

        # The colleague's session still works after the stale cancel.
        final = client.post(
            f'{base}/scan',
            headers=colleague_headers,
            json={'barcode': doc_template.barcode, 'quantity': 1},
        )
        assert final.status_code == status.HTTP_200_OK, final.text
        assert final.json()['picked_quantity'] == 5

        assert len(_handover_entries(db_session, doc_id)) == 1
