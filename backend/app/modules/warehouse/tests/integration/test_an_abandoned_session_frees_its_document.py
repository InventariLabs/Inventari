"""A scanning session nobody is working in no longer blocks its document.

Closing the picking or receiving sheet used to leave the session open and
held: the document refused completion until someone resumed the session or
discarded every scan in it. Now closing the sheet pauses the session, and a
session left untouched for the organization's idle time counts the same: the
scans stay, anyone who starts the document continues them, and completing the
document books what was scanned.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import WmsPickLine, WmsPickSession

from .test_wms_session_takeover import _confirmed_in, _confirmed_out


def _session(db_session: Session, session_id: str) -> WmsPickSession:
    db_session.expire_all()
    session = db_session.get(WmsPickSession, uuid.UUID(session_id))
    assert session is not None
    return session


def _receive_four_of_ten(
    client: TestClient,
    headers: dict[str, str],
    target: StorageLocation,
    partner: Partner,
    template: ProductTemplate,
) -> tuple[str, str]:
    doc_id = _confirmed_in(client, headers, target, partner, template)
    start = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/receiving/start', headers=headers
    )
    assert start.status_code == status.HTTP_201_CREATED, start.text
    session_id = cast(str, start.json()['id'])
    scan = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
        headers=headers,
        json={'barcode': template.barcode, 'quantity': 4},
    )
    assert scan.status_code == status.HTTP_200_OK, scan.text
    return doc_id, session_id


def _complete_with_the_scans(
    client: TestClient, headers: dict[str, str], doc_id: str
) -> Any:
    """Complete the way the document page does: each line at what it shows."""
    doc = client.get(f'/api/v1/warehouse/documents/{doc_id}', headers=headers).json()
    lines = [
        {
            'line_id': line['id'],
            'done_quantity': float(line['done_quantity']),
            'discrepancy_code': 'SHORTAGE',
        }
        for line in doc['lines']
    ]
    return client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'lines': lines},
    )


@pytest.mark.integration
class TestClosingTheSheetPausesTheSession:
    def test_a_paused_receipt_completes_with_what_was_scanned(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id, session_id = _receive_four_of_ten(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )

        paused = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/pause',
            headers=doc_auth_headers,
        )
        assert paused.status_code == status.HTTP_204_NO_CONTENT, paused.text
        assert _session(db_session, session_id).status == 'paused'

        complete = _complete_with_the_scans(client, doc_auth_headers, doc_id)
        assert complete.status_code == status.HTTP_200_OK, complete.text
        body = complete.json()
        assert body['status'] == 'COMPLETED'
        assert float(body['lines'][0]['done_quantity']) == 4

        closed = _session(db_session, session_id)
        assert closed.status == 'short_receive'
        line = db_session.scalars(
            select(WmsPickLine).where(WmsPickLine.session_id == closed.id)
        ).one()
        assert line.status == 'short'
        assert line.picked_quantity == 4

    def test_a_paused_receipt_completes_without_answering_its_lines_again(
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
        """The scans are the answers: one line scanned in part, one never.

        Completing with no body is the document page's one-step finish. The
        untouched line is a shortage of everything, as a skip would say, and
        not a line nobody answered for.
        """
        other = h.create_template(doc_org, name='Untouched', barcode='5901234123464')
        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 10,
                    },
                    {'product_template_id': str(other.id), 'expected_quantity': 10},
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = created.json()['id']
        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm.status_code == status.HTTP_200_OK, confirm.text
        session_id = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        ).json()['id']
        base = f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}'
        scan = client.post(
            f'{base}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 4},
        )
        assert scan.status_code == status.HTTP_200_OK, scan.text
        paused = client.post(f'{base}/pause', headers=doc_auth_headers)
        assert paused.status_code == status.HTTP_204_NO_CONTENT, paused.text

        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete', headers=doc_auth_headers
        )
        assert complete.status_code == status.HTTP_200_OK, complete.text
        lines = {line['product_template_id']: line for line in complete.json()['lines']}
        scanned, untouched = lines[str(doc_template.id)], lines[str(other.id)]
        assert float(scanned['done_quantity']) == 4
        assert scanned['discrepancy_code'] == 'SHORTAGE'
        assert float(untouched['done_quantity']) == 0
        assert untouched['discrepancy_code'] == 'SHORTAGE'
        assert _session(db_session, session_id).status == 'short_receive'

    def test_a_colleague_continues_a_paused_picking_from_its_scans(
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
        scan = client.post(
            f'{base}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 2},
        )
        assert scan.status_code == status.HTTP_200_OK, scan.text
        assert (
            client.post(f'{base}/pause', headers=doc_auth_headers).status_code
            == status.HTTP_204_NO_CONTENT
        )

        colleague = h.create_user(doc_org, email='second-picker@example.com')
        colleague_headers = h.get_auth_headers(colleague)
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=colleague_headers,
        )
        assert start.status_code == status.HTTP_201_CREATED, start.text
        assert start.json()['id'] == session_id
        assert start.json()['assigned_to'] == str(colleague.id)
        assert start.json()['status'] == 'active'
        assert start.json()['lines'][0]['picked_quantity'] == 2

        rest = client.post(
            f'{base}/scan',
            headers=colleague_headers,
            json={'barcode': doc_template.barcode, 'quantity': 3},
        )
        assert rest.status_code == status.HTTP_200_OK, rest.text
        assert rest.json()['session_complete'] is True

    def test_only_the_holder_pauses_the_session(
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
        doc_id, session_id = _receive_four_of_ten(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        colleague = h.create_user(doc_org, email='bystander@example.com')
        refused = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/pause',
            headers=h.get_auth_headers(colleague),
        )
        assert refused.status_code == status.HTTP_409_CONFLICT
        assert refused.json()['detail']['code'] == 'SESSION_HELD_BY_OTHER_USER'
        assert _session(db_session, session_id).status == 'active'


@pytest.mark.integration
class TestAnIdleSessionIsReleased:
    def _idle_for(self, db_session: Session, session_id: str, minutes: int) -> None:
        session = _session(db_session, session_id)
        session.last_activity_at = datetime.now(UTC) - timedelta(minutes=minutes)
        db_session.commit()

    def test_a_session_in_use_still_holds_the_document(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id, _ = _receive_four_of_ten(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        complete = _complete_with_the_scans(client, doc_auth_headers, doc_id)
        assert complete.status_code == status.HTTP_409_CONFLICT, complete.text

    def test_a_session_idle_past_the_default_is_released(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id, session_id = _receive_four_of_ten(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        self._idle_for(db_session, session_id, 31)

        complete = _complete_with_the_scans(client, doc_auth_headers, doc_id)
        assert complete.status_code == status.HTTP_200_OK, complete.text
        assert float(complete.json()['lines'][0]['done_quantity']) == 4
        assert _session(db_session, session_id).status == 'short_receive'

    def test_the_idle_time_is_the_organizations_setting(
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
        h.set_module_settings(doc_org, 'warehouse', {'scan_session_idle_minutes': 60})
        doc_id, session_id = _receive_four_of_ten(
            client, doc_auth_headers, doc_target_location, doc_partner, doc_template
        )
        self._idle_for(db_session, session_id, 31)
        held = _complete_with_the_scans(client, doc_auth_headers, doc_id)
        assert held.status_code == status.HTTP_409_CONFLICT, held.text

        self._idle_for(db_session, session_id, 61)
        released = _complete_with_the_scans(client, doc_auth_headers, doc_id)
        assert released.status_code == status.HTTP_200_OK, released.text
