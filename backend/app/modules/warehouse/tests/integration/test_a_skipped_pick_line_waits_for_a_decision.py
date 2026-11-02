"""A skipped picking line is put off, not declared short.

Skip tells the picker the line "will not be picked in this session". It used
to write SHORTAGE on the document line at once, and skipping the last open
line closed the session in the same request: the summary that followed had no
way back, and closing it completed the dispatch with the line short and a
backorder draft for it — an outcome nobody chose.

A skip now records nothing on the document. The summary can take it back,
which opens the finished session again, or answer the line as a short pick of
nothing under the code the person chose: Shortage owes the rest to the
customer on a backorder, Other closes the gap. Until one of those happens,
completing the dispatch is refused like any other line nobody answered for.
"""

import uuid
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.models import DocumentLine
from app.modules.warehouse.tests.integration._records import sow as _sow

pytestmark = pytest.mark.integration

_DOCS = '/api/v1/warehouse/documents'


@pytest.fixture
def skipped(
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
) -> dict[str, str]:
    """A one-line dispatch whose only line, the last one open, was skipped."""
    _sow(
        db_session,
        async_engine_fixture,
        doc_org,
        doc_template,
        doc_source_location.id,
        '20',
    )
    created = client.post(
        _DOCS,
        headers=doc_auth_headers,
        json={
            'type': 'OUT',
            'partner_id': str(doc_partner.id),
            'source_location_id': str(doc_source_location.id),
            'target_location_id': str(doc_target_location.id),
            'lines': [
                {
                    'item_id': str(doc_item.id),
                    'product_template_id': str(doc_item.template_id or doc_template.id),
                    'expected_quantity': 4,
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = cast(str, created.json()['id'])
    confirmed = client.patch(f'{_DOCS}/{doc_id}/confirm', headers=doc_auth_headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    session = client.post(f'{_DOCS}/{doc_id}/picking/start', headers=doc_auth_headers)
    assert session.status_code == status.HTTP_201_CREATED, session.text
    session_id = session.json()['id']
    line_id = session.json()['lines'][0]['id']
    skip = client.post(
        f'{_DOCS}/{doc_id}/picking/{session_id}/skip',
        headers=doc_auth_headers,
        params={'line_id': line_id},
    )
    assert skip.status_code == status.HTTP_200_OK, skip.text
    assert skip.json()['session_complete'] is True
    return {'doc_id': doc_id, 'session_id': session_id, 'line_id': line_id}


def _doc_line(db: Session, doc_id: str) -> DocumentLine:
    db.expire_all()
    return db.scalars(
        select(DocumentLine).where(DocumentLine.document_id == uuid.UUID(doc_id))
    ).one()


def _backorders(client: TestClient, headers: dict[str, str], doc_id: str) -> list[Any]:
    listed = client.get(_DOCS, headers=headers).json()
    # The list carries rows; a backorder's lines are on the document itself.
    return [
        client.get(f'{_DOCS}/{d["id"]}', headers=headers).json()
        for d in listed['items']
        if d.get('backorder_id') == doc_id
    ]


def _answer_short(
    client: TestClient, headers: dict[str, str], skipped: dict[str, str], code: str
) -> None:
    resp = client.post(
        f'{_DOCS}/{skipped["doc_id"]}/picking/{skipped["session_id"]}/short-pick',
        headers=headers,
        json={
            'line_id': skipped['line_id'],
            'picked_quantity': 0,
            'discrepancy_code': code,
        },
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    assert resp.json()['status'] == 'short_pick_confirmed'
    assert resp.json()['session_complete'] is True


def test_a_skip_writes_no_shortage_and_completion_waits_for_an_answer(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    skipped: dict[str, str],
    db_session: Session,
) -> None:
    line = _doc_line(db_session, skipped['doc_id'])
    assert line.discrepancy_code is None
    assert line.done_quantity == 0

    # What closing the summary sends: no body, the session's record stands.
    completed = client.patch(
        f'{_DOCS}/{skipped["doc_id"]}/complete', headers=doc_auth_headers
    )

    assert completed.status_code != status.HTTP_200_OK, completed.text
    doc = client.get(f'{_DOCS}/{skipped["doc_id"]}', headers=doc_auth_headers).json()
    assert doc['status'] == 'CONFIRMED'
    assert _backorders(client, doc_auth_headers, skipped['doc_id']) == []


def test_the_skip_of_the_last_line_can_be_taken_back(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    skipped: dict[str, str],
) -> None:
    undo = client.post(
        f'{_DOCS}/{skipped["doc_id"]}/picking/{skipped["session_id"]}/undo',
        headers=doc_auth_headers,
        params={'line_id': skipped['line_id']},
    )
    assert undo.status_code == status.HTTP_200_OK, undo.text

    session = client.get(
        f'{_DOCS}/{skipped["doc_id"]}/picking/{skipped["session_id"]}',
        headers=doc_auth_headers,
    ).json()
    assert session['status'] == 'active'
    assert session['completed_at'] is None
    assert session['lines'][0]['status'] == 'pending'


def _session_entries(db: Session, doc_id: str) -> list[AuditLog]:
    """The document's entries that say what its picking session now is."""
    db.expire_all()
    rows = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.target_type == 'document',
            AuditLog.target_id == uuid.UUID(doc_id),
        )
        .order_by(AuditLog.created_at.asc())
    ).all()
    return [row for row in rows if 'wms_session_status' in (row.snapshot or {})]


def test_taking_the_skip_back_reaches_the_log(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    skipped: dict[str, str],
    doc_user: User,
    db_session: Session,
) -> None:
    """The skip closed the session and the log said so; opening it again is
    said too, or the last word on the dispatch is a session that is not over."""
    closed = _session_entries(db_session, skipped['doc_id'])
    assert closed[-1].snapshot is not None
    assert closed[-1].snapshot['wms_session_status'] != 'active'

    undo = client.post(
        f'{_DOCS}/{skipped["doc_id"]}/picking/{skipped["session_id"]}/undo',
        headers=doc_auth_headers,
        params={'line_id': skipped['line_id']},
    )
    assert undo.status_code == status.HTTP_200_OK, undo.text

    entries = _session_entries(db_session, skipped['doc_id'])
    assert len(entries) == len(closed) + 1
    assert entries[-1].snapshot is not None
    assert entries[-1].snapshot['wms_session_status'] == 'active'
    assert entries[-1].user_id == doc_user.id


def test_closing_the_gap_completes_without_a_backorder(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    skipped: dict[str, str],
    db_session: Session,
) -> None:
    _answer_short(client, doc_auth_headers, skipped, 'OTHER')

    completed = client.patch(
        f'{_DOCS}/{skipped["doc_id"]}/complete', headers=doc_auth_headers
    )

    assert completed.status_code == status.HTTP_200_OK, completed.text
    assert completed.json().get('generated_backorder_id') is None
    assert _doc_line(db_session, skipped['doc_id']).discrepancy_code == 'OTHER'
    assert _backorders(client, doc_auth_headers, skipped['doc_id']) == []


def test_a_shortage_chosen_on_the_summary_raises_the_backorder(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    skipped: dict[str, str],
) -> None:
    _answer_short(client, doc_auth_headers, skipped, 'SHORTAGE')

    completed = client.patch(
        f'{_DOCS}/{skipped["doc_id"]}/complete', headers=doc_auth_headers
    )

    assert completed.status_code == status.HTTP_200_OK, completed.text
    assert len(_backorders(client, doc_auth_headers, skipped['doc_id'])) == 1
