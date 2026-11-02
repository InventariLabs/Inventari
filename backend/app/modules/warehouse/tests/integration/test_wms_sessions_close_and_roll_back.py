"""Both scanning directions end their session, and cancelling leaves nothing.

Receiving and picking run on the same two tables and differ only in which way
the goods move, but they were fixed one at a time: receiving learned to close
its own session, picking did not, and a document whose own summary said "all
lines are fully executed" could then be neither completed nor cancelled. These
tests ask both directions the same two questions, so a repair to one side
cannot leave the other behind.
"""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import (
    Document,
    DocumentLine,
    WmsPickLine,
    WmsPickSession,
)
from app.modules.warehouse.tests.integration._records import sow as _sow


def _confirm(client: TestClient, headers: dict[str, str], doc_id: str) -> None:
    resp = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert resp.status_code == status.HTTP_200_OK


def _create_in(
    client: TestClient,
    headers: dict[str, str],
    target_location_id: uuid.UUID,
    partner_id: uuid.UUID,
    template_id: uuid.UUID,
    quantity: int = 10,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(target_location_id),
            'lines': [
                {'product_template_id': str(template_id), 'expected_quantity': quantity}
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED
    return cast(str, resp.json()['id'])


def _create_out(
    client: TestClient,
    headers: dict[str, str],
    source_location_id: uuid.UUID,
    target_location_id: uuid.UUID,
    partner_id: uuid.UUID,
    template_id: uuid.UUID,
    item_id: uuid.UUID,
    quantity: int = 5,
) -> str:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner_id),
            'source_location_id': str(source_location_id),
            'target_location_id': str(target_location_id),
            'lines': [
                {
                    'item_id': str(item_id),
                    'product_template_id': str(template_id),
                    'expected_quantity': quantity,
                }
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED
    return cast(str, resp.json()['id'])


def _session(db_session: Session, session_id: str) -> WmsPickSession:
    found = db_session.scalars(
        select(WmsPickSession).where(WmsPickSession.id == uuid.UUID(session_id))
    ).first()
    assert found is not None
    return found


@pytest.mark.integration
class TestTheLastLineEndsTheSession:
    """Whatever resolves the last line closes the session in the database."""

    def test_receiving_the_last_line_closes_the_session(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        doc_id = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=4,
        )
        _confirm(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        scan = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': '4'},
        )
        assert scan.json()['session_complete'] is True

        db_session.expire_all()
        closed = _session(db_session, session_id)
        assert closed.status == 'completed'
        assert closed.completed_at is not None

    def test_picking_the_last_line_closes_the_session(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """The twin of the case above — this is the one that was broken.

        The sheet showed "Picking Complete" and a single Close button, and the
        session stayed `active`: completing the document answered 409
        WMS_SESSION_ACTIVE and starting again answered 400, with no screen in
        between that could reach the session.
        """
        template_id = doc_item.template_id or doc_template.id
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
        )

        doc_id = _create_out(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        scan = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 5},
        )
        assert scan.json()['session_complete'] is True

        db_session.expire_all()
        closed = _session(db_session, session_id)
        assert closed.status == 'completed'
        assert closed.completed_at is not None

        # And the document can now be closed, which is what the picker asked
        # for by scanning the last line.
        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete', headers=doc_auth_headers
        )
        assert complete.status_code == status.HTTP_200_OK

    def test_the_complete_endpoint_answers_the_same_thing_twice(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """The sheet's own Finish button still arrives after the last scan."""
        template_id = doc_item.template_id or doc_template.id
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
        )

        doc_id = _create_out(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            template_id,
            doc_item.id,
        )
        _confirm(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']
        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 5},
        )

        resp = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/complete',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()['status'] == 'completed'


@pytest.mark.integration
class TestCancellingLeavesNothingBehind:
    def test_cancelling_receiving_takes_back_a_partial_scan(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """A part-scanned line stays `pending`, and used to survive the cancel.

        The document then showed a receipt of 5 of 12.5 that no finished
        session had made, and the session that wrote it no longer existed to
        be asked about it.
        """
        doc_id = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=10,
        )
        _confirm(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']

        scan = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': '4'},
        )
        assert scan.json()['session_complete'] is False

        db_session.expire_all()
        partial = db_session.scalars(
            select(WmsPickLine).where(WmsPickLine.session_id == uuid.UUID(session_id))
        ).first()
        assert partial is not None
        assert partial.status == 'pending'
        assert partial.picked_quantity == Decimal('4')

        cancel = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/cancel',
            headers=doc_auth_headers,
        )
        assert cancel.status_code in (
            status.HTTP_200_OK,
            status.HTTP_204_NO_CONTENT,
        )

        db_session.expire_all()
        assert _session(db_session, session_id).status == 'cancelled'

        line = db_session.scalars(
            select(WmsPickLine).where(WmsPickLine.id == partial.id)
        ).first()
        assert line is not None
        assert line.picked_quantity == Decimal('0')

        doc_line = db_session.scalars(
            select(DocumentLine).where(DocumentLine.id == line.document_line_id)
        ).first()
        assert doc_line is not None
        assert doc_line.done_quantity == Decimal('0')

    def test_cancelling_receiving_clears_a_skipped_line(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """Skipping a receipt line writes no code, and cancelling leaves it so.

        The old rollback only looked at lines marked picked or short, so a
        skipped line kept its "Skipped during picking" on a document no
        session had ever finished. A skip puts the line off on either side,
        so cancelling has nothing to clear and the line goes back to pending.
        """
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                # Two lines, so that skipping one leaves the session in progress.
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 5,
                    },
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 3,
                    },
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED
        doc_id = resp.json()['id']
        _confirm(client, doc_auth_headers, doc_id)

        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']
        pick_line = db_session.scalars(
            select(WmsPickLine).where(WmsPickLine.session_id == uuid.UUID(session_id))
        ).first()
        assert pick_line is not None
        doc_line_id = pick_line.document_line_id

        skip = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/skip',
            headers=doc_auth_headers,
            params={'line_id': str(pick_line.id)},
        )
        assert skip.status_code == status.HTTP_200_OK

        db_session.expire_all()
        skipped = db_session.scalars(
            select(DocumentLine).where(DocumentLine.id == doc_line_id)
        ).first()
        assert skipped is not None
        assert skipped.discrepancy_code is None

        cancel = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/cancel',
            headers=doc_auth_headers,
        )
        assert cancel.status_code in (
            status.HTTP_200_OK,
            status.HTTP_204_NO_CONTENT,
        )

        db_session.expire_all()
        assert _session(db_session, session_id).status == 'cancelled'
        cleared = db_session.scalars(
            select(DocumentLine).where(DocumentLine.id == doc_line_id)
        ).first()
        assert cleared is not None
        assert cleared.discrepancy_code is None
        assert cleared.discrepancy_reason is None
        assert cleared.done_quantity == Decimal('0')


@pytest.mark.integration
class TestReopeningAFinishedScan:
    """A session that ended over a document nobody completed comes back.

    The summary that books the document can be left by the back arrow or a
    closed tab, and the next start used to open a new session at 0 of N over
    lines the document already read as done — inviting every line to be
    scanned again, while the only way to book was the manual panel.
    """

    def test_receiving_hands_back_the_finished_session(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=4,
        )
        _confirm(client, doc_auth_headers, doc_id)
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']
        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': '4'},
        )

        again = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )

        assert again.status_code == status.HTTP_201_CREATED
        body = again.json()
        assert body['id'] == session_id
        assert body['status'] == 'completed'
        assert body['received_lines'] == 1
        assert body['pending_lines'] == 0

    def test_picking_hands_back_the_finished_session(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
        )
        doc_id = _create_out(
            client,
            doc_auth_headers,
            doc_source_location.id,
            doc_target_location.id,
            doc_partner.id,
            doc_item.template_id or doc_template.id,
            doc_item.id,
        )
        _confirm(client, doc_auth_headers, doc_id)
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']
        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 5},
        )

        again = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )

        assert again.status_code == status.HTTP_201_CREATED
        body = again.json()
        assert body['id'] == session_id
        assert body['status'] == 'completed'
        assert all(line['status'] == 'picked' for line in body['lines'])

    def test_a_cancelled_session_is_not_handed_back(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """Cancelling put the scans back, so the next start counts afresh."""
        doc_id = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
        )
        _confirm(client, doc_auth_headers, doc_id)
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']
        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/cancel',
            headers=doc_auth_headers,
        )

        again = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )

        assert again.json()['id'] != session_id
        assert again.json()['status'] == 'active'

    def test_a_session_from_before_the_confirmation_is_not_handed_back(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """A document sent back to draft and confirmed again starts over.

        Its lines may have changed in between, so the session that finished
        over the earlier confirmation is not the count of this one.
        """
        doc_id = _create_in(
            client,
            doc_auth_headers,
            doc_target_location.id,
            doc_partner.id,
            doc_template.id,
            quantity=4,
        )
        _confirm(client, doc_auth_headers, doc_id)
        start = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )
        session_id = start.json()['id']
        client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/{session_id}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': '4'},
        )
        finished = _session(db_session, session_id)
        doc = db_session.get(Document, uuid.UUID(doc_id))
        assert doc is not None and finished.started_at is not None
        doc.confirmed_at = finished.started_at + timedelta(minutes=5)
        db_session.commit()

        again = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/receiving/start',
            headers=doc_auth_headers,
        )

        assert again.json()['id'] != session_id
        assert again.json()['status'] == 'active'
