"""To do tells the floor what the document is waiting for, not just that it exists.

The queue used to be one list of confirmed receipts and dispatches with one
button each: *Receive* or *Pick*, whatever had already happened on the floor.
A dispatch picked short and packed still offered *Pick*; a receipt somebody
had already counted offered *Receive* again. Transfers were not in the queue
at all.

The work stage is derived from the rows that already exist — the session, who
holds it, the picked quantities and the packages — never a new document
status. The queue lists receipts on one side and dispatches, transfers
included, on the other; each row carries the stage, the holder's name while a
session is open and the one action that moves the work on. Every count is the
server's own total, so it covers the rows past the first page.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.models import (
    Document,
    DocumentPackage,
    DocumentPackageLine,
    WmsPickLine,
    WmsPickSession,
)

_TODAY = date.today().isoformat()


def _create_document(
    client: TestClient,
    headers: dict[str, str],
    *,
    doc_type: str,
    partner: Partner,
    source: StorageLocation | None,
    target: StorageLocation,
    template: ProductTemplate,
    item_id: UUID | None = None,
    quantity: str = '5',
) -> str:
    line: dict[str, Any] = {
        'product_template_id': str(template.id),
        'expected_quantity': quantity,
    }
    if item_id is not None:
        line['item_id'] = str(item_id)
        line['name'] = template.name
    payload: dict[str, Any] = {
        'type': doc_type,
        'partner_id': str(partner.id),
        'target_location_id': str(target.id),
        'scheduled_date': _TODAY,
        'lines': [line],
    }
    if source is not None:
        payload['source_location_id'] = str(source.id)
    response = client.post('/api/v1/warehouse/documents', headers=headers, json=payload)
    assert response.status_code == status.HTTP_201_CREATED, response.text
    doc_id = cast(str, response.json()['id'])
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    return doc_id


def _finish_session(
    db_session: Session,
    org: Organization,
    user: User,
    doc_id: str,
    *,
    picked: str | None,
    status_word: str = 'completed',
) -> None:
    """A session that is over, with the quantity it recorded."""
    document = db_session.get(Document, UUID(doc_id))
    assert document is not None
    line = document.lines[0]
    session = WmsPickSession(
        organization_id=org.id,
        document_id=document.id,
        assigned_to=user.id,
        status=status_word,
        started_at=datetime.now(),
        completed_at=datetime.now(),
    )
    db_session.add(session)
    db_session.flush()
    amount = Decimal(picked) if picked is not None else Decimal('0')
    db_session.add(
        WmsPickLine(
            session_id=session.id,
            document_line_id=line.id,
            expected_quantity=line.expected_quantity,
            picked_quantity=amount,
            status='picked' if amount > 0 else 'pending',
        )
    )
    line.done_quantity = amount
    db_session.commit()


def _open_session(
    db_session: Session, org: Organization, user: User, doc_id: str
) -> None:
    document = db_session.get(Document, UUID(doc_id))
    assert document is not None
    db_session.add(
        WmsPickSession(
            organization_id=org.id,
            document_id=document.id,
            assigned_to=user.id,
            status='active',
            started_at=datetime.now(),
        )
    )
    db_session.commit()


def _pack(db_session: Session, org: Organization, doc_id: str, quantity: str) -> None:
    document = db_session.get(Document, UUID(doc_id))
    assert document is not None
    package = DocumentPackage(
        organization_id=org.id,
        document_id=document.id,
        number=1,
    )
    db_session.add(package)
    db_session.flush()
    db_session.add(
        DocumentPackageLine(
            document_package_id=package.id,
            document_line_id=document.lines[0].id,
            quantity=Decimal(quantity),
        )
    )
    db_session.commit()


def _empty_package(db_session: Session, org: Organization, doc_id: str) -> None:
    """A box somebody created, with nothing in it."""
    document = db_session.get(Document, UUID(doc_id))
    assert document is not None
    db_session.add(
        DocumentPackage(
            organization_id=org.id,
            document_id=document.id,
            number=1,
        )
    )
    db_session.commit()


def _todo(
    client: TestClient,
    headers: dict[str, str],
    *,
    limit: int = 50,
    inbound_offset: int = 0,
    outbound_offset: int = 0,
) -> dict[str, Any]:
    response = client.get(
        '/api/v1/warehouse/todo',
        headers=headers,
        params={
            'date_to': _TODAY,
            'limit': limit,
            'inbound_offset': inbound_offset,
            'outbound_offset': outbound_offset,
        },
    )
    assert response.status_code == status.HTTP_200_OK, response.text
    return cast(dict[str, Any], response.json())


def _row(todo: dict[str, Any], doc_id: str) -> dict[str, Any]:
    for section in ('inbound', 'outbound'):
        for row in todo[section]['items']:
            if row['id'] == doc_id:
                return cast(dict[str, Any], row)
    raise AssertionError(f'{doc_id} is not in the queue: {todo}')


@pytest.mark.integration
class TestTheTodoQueueShowsTheWorkStage:
    def test_a_confirmed_document_nobody_started_is_to_start(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Any,
    ) -> None:
        doc_id = _create_document(
            client,
            doc_auth_headers,
            doc_type='OUT',
            partner=doc_partner,
            source=doc_source_location,
            target=doc_target_location,
            template=doc_template,
            item_id=doc_stock_item.id,
        )

        row = _row(_todo(client, doc_auth_headers), doc_id)

        assert row['work_stage'] == 'to_start'
        assert row['next_action'] == 'pick'
        assert row['stage_holder_name'] is None

    def test_a_receipt_nobody_started_offers_receive(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        doc_id = _create_document(
            client,
            doc_auth_headers,
            doc_type='IN',
            partner=doc_partner,
            source=None,
            target=doc_target_location,
            template=doc_template,
        )

        row = _row(_todo(client, doc_auth_headers), doc_id)

        assert row['work_stage'] == 'to_start'
        assert row['next_action'] == 'receive'

    def test_an_open_session_names_its_holder_and_offers_resume(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Any,
    ) -> None:
        doc_id = _create_document(
            client,
            doc_auth_headers,
            doc_type='OUT',
            partner=doc_partner,
            source=doc_source_location,
            target=doc_target_location,
            template=doc_template,
            item_id=doc_stock_item.id,
        )
        _open_session(db_session, doc_org, doc_user, doc_id)

        row = _row(_todo(client, doc_auth_headers), doc_id)

        assert row['work_stage'] == 'in_progress'
        assert row['next_action'] == 'resume'
        assert row['stage_holder_name'] == (doc_user.full_name or doc_user.email)

    def test_a_finished_session_with_no_packages_is_picked_with_complete_next(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Any,
    ) -> None:
        """The warehouse that does not pack skips Packed, not Picked."""
        doc_id = _create_document(
            client,
            doc_auth_headers,
            doc_type='OUT',
            partner=doc_partner,
            source=doc_source_location,
            target=doc_target_location,
            template=doc_template,
            item_id=doc_stock_item.id,
        )
        _finish_session(db_session, doc_org, doc_user, doc_id, picked='5')

        row = _row(_todo(client, doc_auth_headers), doc_id)

        assert row['work_stage'] == 'picked'
        assert row['next_action'] == 'complete'

    def test_an_empty_package_does_not_change_the_finished_pick(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Any,
    ) -> None:
        """An empty box is not packing; it must not turn Complete into Pack."""
        doc_id = _create_document(
            client,
            doc_auth_headers,
            doc_type='OUT',
            partner=doc_partner,
            source=doc_source_location,
            target=doc_target_location,
            template=doc_template,
            item_id=doc_stock_item.id,
        )
        _finish_session(db_session, doc_org, doc_user, doc_id, picked='8')

        before = _row(_todo(client, doc_auth_headers), doc_id)
        _empty_package(db_session, doc_org, doc_id)
        after = _row(_todo(client, doc_auth_headers), doc_id)

        assert before['work_stage'] == 'picked'
        assert before['next_action'] == 'complete'
        assert after['work_stage'] == before['work_stage']
        assert after['next_action'] == before['next_action']

    def test_packing_not_yet_covering_the_pick_is_picked_with_pack_next(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Any,
    ) -> None:
        doc_id = _create_document(
            client,
            doc_auth_headers,
            doc_type='OUT',
            partner=doc_partner,
            source=doc_source_location,
            target=doc_target_location,
            template=doc_template,
            item_id=doc_stock_item.id,
        )
        _finish_session(db_session, doc_org, doc_user, doc_id, picked='5')
        _pack(db_session, doc_org, doc_id, '3')

        row = _row(_todo(client, doc_auth_headers), doc_id)

        assert row['work_stage'] == 'picked'
        assert row['next_action'] == 'pack'

    def test_packages_covering_the_picked_quantity_are_packed_and_complete(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Any,
    ) -> None:
        """Eight of ten picked, all eight packed: Packed, not another Pick."""
        doc_id = _create_document(
            client,
            doc_auth_headers,
            doc_type='OUT',
            partner=doc_partner,
            source=doc_source_location,
            target=doc_target_location,
            template=doc_template,
            item_id=doc_stock_item.id,
            quantity='10',
        )
        _finish_session(
            db_session, doc_org, doc_user, doc_id, picked='8', status_word='short_pick'
        )
        _pack(db_session, doc_org, doc_id, '8')

        row = _row(_todo(client, doc_auth_headers), doc_id)

        assert row['work_stage'] == 'packed'
        assert row['next_action'] == 'complete'

    def test_a_dispatch_picked_and_packed_in_full_is_ready_to_hand_over(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Any,
    ) -> None:
        """Nothing short and every piece in a box: only the hand-over is left."""
        doc_id = _create_document(
            client,
            doc_auth_headers,
            doc_type='OUT',
            partner=doc_partner,
            source=doc_source_location,
            target=doc_target_location,
            template=doc_template,
            item_id=doc_stock_item.id,
            quantity='10',
        )
        _finish_session(db_session, doc_org, doc_user, doc_id, picked='10')
        _pack(db_session, doc_org, doc_id, '10')

        row = _row(_todo(client, doc_auth_headers), doc_id)

        assert row['work_stage'] == 'ready'
        assert row['next_action'] == 'complete'

    def test_a_full_pick_that_is_only_half_packed_still_asks_to_pack(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Any,
    ) -> None:
        doc_id = _create_document(
            client,
            doc_auth_headers,
            doc_type='OUT',
            partner=doc_partner,
            source=doc_source_location,
            target=doc_target_location,
            template=doc_template,
            item_id=doc_stock_item.id,
            quantity='10',
        )
        _finish_session(db_session, doc_org, doc_user, doc_id, picked='10')
        _pack(db_session, doc_org, doc_id, '4')

        row = _row(_todo(client, doc_auth_headers), doc_id)

        assert row['work_stage'] == 'picked'
        assert row['next_action'] == 'pack'

    def test_a_full_pick_in_a_warehouse_that_does_not_pack_stays_picked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Any,
    ) -> None:
        """Ready to hand over is a packed state; skipping packing never shows it."""
        doc_id = _create_document(
            client,
            doc_auth_headers,
            doc_type='OUT',
            partner=doc_partner,
            source=doc_source_location,
            target=doc_target_location,
            template=doc_template,
            item_id=doc_stock_item.id,
            quantity='10',
        )
        _finish_session(db_session, doc_org, doc_user, doc_id, picked='10')

        row = _row(_todo(client, doc_auth_headers), doc_id)

        assert row['work_stage'] == 'picked'
        assert row['next_action'] == 'complete'

    def test_a_receipt_received_in_full_is_ready_to_complete(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        full = _create_document(
            client,
            doc_auth_headers,
            doc_type='IN',
            partner=doc_partner,
            source=None,
            target=doc_target_location,
            template=doc_template,
            quantity='10',
        )
        short = _create_document(
            client,
            doc_auth_headers,
            doc_type='IN',
            partner=doc_partner,
            source=None,
            target=doc_target_location,
            template=doc_template,
            quantity='10',
        )
        _finish_session(db_session, doc_org, doc_user, full, picked='10')
        _finish_session(
            db_session,
            doc_org,
            doc_user,
            short,
            picked='6',
            status_word='short_receive',
        )

        todo = _todo(client, doc_auth_headers)

        assert _row(todo, full)['work_stage'] == 'ready'
        assert _row(todo, full)['next_action'] == 'complete'
        assert _row(todo, short)['work_stage'] == 'picked'
        assert _row(todo, short)['next_action'] == 'complete'

    def test_a_transfer_joins_the_outbound_list(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Any,
    ) -> None:
        doc_id = _create_document(
            client,
            doc_auth_headers,
            doc_type='INT',
            partner=doc_partner,
            source=doc_source_location,
            target=doc_target_location,
            template=doc_template,
            item_id=doc_stock_item.id,
        )

        todo = _todo(client, doc_auth_headers)
        row = _row(todo, doc_id)

        assert row['work_stage'] == 'to_start'
        assert row['next_action'] == 'pick'
        assert doc_id not in [r['id'] for r in todo['inbound']['items']]

    def test_each_count_is_the_server_total_beyond_the_first_page(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        for _ in range(3):
            _create_document(
                client,
                doc_auth_headers,
                doc_type='IN',
                partner=doc_partner,
                source=None,
                target=doc_target_location,
                template=doc_template,
            )

        response = client.get(
            '/api/v1/warehouse/todo',
            headers=doc_auth_headers,
            params={'date_to': _TODAY, 'limit': 2},
        )
        assert response.status_code == status.HTTP_200_OK, response.text
        data = response.json()

        assert data['inbound']['total'] == 3
        assert len(data['inbound']['items']) == 2
        listed = client.get(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            params={
                'type': 'IN,INTERNAL_IN',
                'status': 'CONFIRMED',
                'date_to': _TODAY,
                'limit': 1,
            },
        )
        assert listed.status_code == status.HTTP_200_OK, listed.text
        assert listed.json()['total'] == data['inbound']['total']

    def test_each_side_pages_on_its_own_offset_and_keeps_its_stage(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_user: User,
        db_session: Session,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_stock_item: Any,
    ) -> None:
        """The rows past the first page still carry their stage and action."""
        inbound_ids = [
            _create_document(
                client,
                doc_auth_headers,
                doc_type='IN',
                partner=doc_partner,
                source=None,
                target=doc_target_location,
                template=doc_template,
            )
            for _ in range(3)
        ]
        outbound_ids = [
            _create_document(
                client,
                doc_auth_headers,
                doc_type='OUT',
                partner=doc_partner,
                source=doc_source_location,
                target=doc_target_location,
                template=doc_template,
                item_id=doc_stock_item.id,
            )
            for _ in range(3)
        ]
        _finish_session(db_session, doc_org, doc_user, inbound_ids[-1], picked='5')
        _open_session(db_session, doc_org, doc_user, outbound_ids[-1])

        first = _todo(client, doc_auth_headers, limit=2)
        assert [row['id'] for row in first['inbound']['items']] == inbound_ids[:2]
        assert [row['id'] for row in first['outbound']['items']] == outbound_ids[:2]

        second = _todo(
            client,
            doc_auth_headers,
            limit=2,
            inbound_offset=2,
            outbound_offset=2,
        )

        assert [row['id'] for row in second['inbound']['items']] == inbound_ids[2:]
        assert [row['id'] for row in second['outbound']['items']] == outbound_ids[2:]
        assert second['inbound']['total'] == 3
        assert second['outbound']['total'] == 3
        assert second['inbound']['items'][0]['work_stage'] == 'ready'
        assert second['inbound']['items'][0]['next_action'] == 'complete'
        assert second['outbound']['items'][0]['work_stage'] == 'in_progress'
        assert second['outbound']['items'][0]['next_action'] == 'resume'
        assert second['outbound']['items'][0]['stage_holder_name'] == (
            doc_user.full_name or doc_user.email
        )
