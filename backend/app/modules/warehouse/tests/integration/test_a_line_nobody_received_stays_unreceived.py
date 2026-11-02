"""Completing without a body must not undo what the warehouse recorded.

Completing with no execution data filled every line with its expected
quantity and cleared the discrepancy on any line that reached it. A line a
picker or receiver had deliberately skipped — recorded as nought received —
was therefore signed off as delivered in full, no backorder was raised for it,
and the goods that never arrived were on the books as if they had.

A line already carrying a discrepancy code is an answer somebody gave. The
default is for lines nobody has answered for, and it stays that way. A skip
is not that answer on either side: it writes no code, and a completion that
meets the skipped line unanswered is refused, with ``complete_as_planned``
too. Answering it as a short receive of nothing is what raises the backorder.

The same rule ran three ways: the panel demands a code for a partial, the
scanning session left it optional, and completing with no body demanded
nothing at all. A short receive with nobody naming a reason now records the
same SHORTAGE a skip does, so a partial execution is explained wherever it
was entered.
"""

from decimal import Decimal
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import DocumentLine

pytestmark = pytest.mark.integration


def _confirmed_document(
    client: TestClient,
    headers: dict[str, str],
    *,
    location: StorageLocation,
    partner: Partner,
    item: Item,
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner.id),
            'target_location_id': str(location.id),
            'lines': [{'item_id': str(item.id), 'expected_quantity': '10'}],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc: dict[str, Any] = resp.json()
    client.patch(f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=headers)
    return doc


def _receiving_session(
    client: TestClient, headers: dict[str, str], doc_id: str
) -> dict[str, Any]:
    resp = client.post(
        f'/api/v1/warehouse/documents/{doc_id}/receiving/start', headers=headers
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    session: dict[str, Any] = resp.json()
    return session


def _doc_line(db: Session, doc_id: str) -> DocumentLine:
    db.expire_all()
    line = db.scalars(
        select(DocumentLine).where(DocumentLine.document_id == doc_id)
    ).one()
    return line


def _backorders(client: TestClient, headers: dict[str, str], doc_id: str) -> list[Any]:
    listed = client.get('/api/v1/warehouse/documents', headers=headers).json()
    # The list carries rows; a backorder's lines are on the document itself.
    return [
        client.get(f'/api/v1/warehouse/documents/{d["id"]}', headers=headers).json()
        for d in listed['items']
        if d.get('backorder_id') == doc_id
    ]


def _skip_the_only_line(
    client: TestClient, headers: dict[str, str], doc: dict[str, Any]
) -> dict[str, Any]:
    session = _receiving_session(client, headers, doc['id'])
    skipped = client.post(
        f'/api/v1/warehouse/documents/{doc["id"]}/receiving/{session["id"]}/skip',
        headers=headers,
        params={'line_id': session['lines'][0]['id']},
    )
    assert skipped.status_code == status.HTTP_200_OK, skipped.text
    return session


def test_a_skipped_line_is_not_signed_off_as_delivered(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    doc_item: Item,
    db_session: Session,
) -> None:
    doc = _confirmed_document(
        client,
        doc_auth_headers,
        location=doc_target_location,
        partner=doc_partner,
        item=doc_item,
    )
    _skip_the_only_line(client, doc_auth_headers, doc)

    line = _doc_line(db_session, doc['id'])
    assert line.discrepancy_code is None

    for body in (None, {'complete_as_planned': True}):
        completed = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/complete',
            headers=doc_auth_headers,
            json=body,
        )
        assert completed.status_code == status.HTTP_400_BAD_REQUEST, completed.text
        assert '1' in completed.json()['detail']['message']

    line = _doc_line(db_session, doc['id'])
    assert line.done_quantity == Decimal('0')
    assert _backorders(client, doc_auth_headers, doc['id']) == []


def test_a_skipped_line_answered_as_short_raises_a_backorder(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    doc_item: Item,
    db_session: Session,
) -> None:
    """The goods are still owed once somebody says so."""
    doc = _confirmed_document(
        client,
        doc_auth_headers,
        location=doc_target_location,
        partner=doc_partner,
        item=doc_item,
    )
    session = _skip_the_only_line(client, doc_auth_headers, doc)
    answered = client.post(
        f'/api/v1/warehouse/documents/{doc["id"]}/receiving/{session["id"]}/short-receive',
        headers=doc_auth_headers,
        json={
            'line_id': session['lines'][0]['id'],
            'received_quantity': '0',
            'discrepancy_code': 'SHORTAGE',
        },
    )
    assert answered.status_code == status.HTTP_200_OK, answered.text

    completed = client.patch(
        f'/api/v1/warehouse/documents/{doc["id"]}/complete',
        headers=doc_auth_headers,
        json={'complete_as_planned': True},
    )
    assert completed.status_code == status.HTTP_200_OK, completed.text
    assert _doc_line(db_session, doc['id']).discrepancy_code == 'SHORTAGE'
    assert len(_backorders(client, doc_auth_headers, doc['id'])) == 1


def test_a_body_that_answers_the_skipped_line_completes(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    doc_item: Item,
    db_session: Session,
) -> None:
    """A completion that names the line and its reason is the answer itself."""
    doc = _confirmed_document(
        client,
        doc_auth_headers,
        location=doc_target_location,
        partner=doc_partner,
        item=doc_item,
    )
    _skip_the_only_line(client, doc_auth_headers, doc)

    completed = client.patch(
        f'/api/v1/warehouse/documents/{doc["id"]}/complete',
        headers=doc_auth_headers,
        json={
            'lines': [
                {
                    'line_id': doc['lines'][0]['id'],
                    'done_quantity': '0',
                    'discrepancy_code': 'OTHER',
                }
            ]
        },
    )
    assert completed.status_code == status.HTTP_200_OK, completed.text
    assert _doc_line(db_session, doc['id']).discrepancy_code == 'OTHER'


def test_a_line_nobody_touched_still_defaults_to_delivered(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    doc_item: Item,
    db_session: Session,
) -> None:
    """The control: no session, no body, so the document arrived in full."""
    doc = _confirmed_document(
        client,
        doc_auth_headers,
        location=doc_target_location,
        partner=doc_partner,
        item=doc_item,
    )

    completed = client.patch(
        f'/api/v1/warehouse/documents/{doc["id"]}/complete',
        headers=doc_auth_headers,
        json={'complete_as_planned': True},
    )
    assert completed.status_code == status.HTTP_200_OK, completed.text

    line = _doc_line(db_session, doc['id'])
    assert line.done_quantity == Decimal('10')
    assert line.discrepancy_code is None
    assert _backorders(client, doc_auth_headers, doc['id']) == []


def test_a_short_receive_without_a_reason_is_still_explained(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    doc_item: Item,
    db_session: Session,
) -> None:
    """One rule for a partial: it says why, whichever screen entered it."""
    doc = _confirmed_document(
        client,
        doc_auth_headers,
        location=doc_target_location,
        partner=doc_partner,
        item=doc_item,
    )
    session = _receiving_session(client, doc_auth_headers, doc['id'])
    short = client.post(
        f'/api/v1/warehouse/documents/{doc["id"]}/receiving/{session["id"]}/short-receive',
        headers=doc_auth_headers,
        json={'line_id': session['lines'][0]['id'], 'received_quantity': '4'},
    )
    assert short.status_code == status.HTTP_200_OK, short.text

    line = _doc_line(db_session, doc['id'])
    assert line.done_quantity == Decimal('4')
    assert line.discrepancy_code == 'SHORTAGE'
