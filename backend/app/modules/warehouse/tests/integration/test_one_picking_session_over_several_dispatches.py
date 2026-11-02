"""One picking session walks several confirmed dispatches, and lets each go on its own.

A picker with three small orders on the board used to walk the warehouse
three times: a session held exactly one document. A session can now be
started over several dispatches at once — one walk, its lines from all of
them in pick-path order — and each dispatch is done with the session the
moment its own lines are answered: it can be completed while the others are
still being picked, and a shortage on one marks that one alone.

The start is all or nothing. A dispatch that cannot be picked refuses the
whole start with a sentence naming it, so nobody is left holding a session
over part of what they chose.
"""

import uuid
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.audit_log import AuditLog
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.models import DocumentLine, WmsPickSession
from app.modules.warehouse.tests.integration._records import sow

_START = '/api/v1/warehouse/picking/start'


def _shelf(
    db: Session, org: Organization, user: User, *, code: str, sequence: int
) -> StorageLocation:
    shelf = StorageLocation(
        name=f'Shelf {code}',
        short_code=code,
        sequence=sequence,
        organization_id=org.id,
        created_by=user.id,
    )
    db.add(shelf)
    db.commit()
    db.refresh(shelf)
    return shelf


def _dispatch(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    shelf: StorageLocation,
    record: Item,
    quantity: int,
    *,
    confirm: bool = True,
) -> dict[str, Any]:
    """A dispatch of *quantity* off *shelf*, confirmed unless told otherwise."""
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner.id),
            'source_location_id': str(shelf.id),
            'lines': [{'item_id': str(record.id), 'expected_quantity': quantity}],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = resp.json()['id']
    if confirm:
        resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(dict[str, Any], resp.json())


def _start(client: TestClient, headers: dict[str, str], *docs: dict[str, Any]) -> Any:
    return client.post(
        _START, headers=headers, json={'document_ids': [d['id'] for d in docs]}
    )


def _sessions_holding(db: Session, doc: dict[str, Any]) -> int:
    """Sessions started with *doc* first — each refusal below lists it first."""
    db.expire_all()
    return cast(
        int,
        db.scalar(
            select(func.count())
            .select_from(WmsPickSession)
            .where(WmsPickSession.document_id == uuid.UUID(doc['id']))
        ),
    )


@pytest.fixture
def product_y(h: ModuleTestHelper, doc_org: Organization) -> ProductTemplate:
    return h.create_template(doc_org, name='Product Y', barcode='4006381333931')


@pytest.fixture
def shelves(
    db_session: Session, doc_org: Organization, doc_user: User
) -> list[StorageLocation]:
    # Alphabetically A, B, C — numbered so the walk is C, A, B.
    return [
        _shelf(db_session, doc_org, doc_user, code='B-01', sequence=30),
        _shelf(db_session, doc_org, doc_user, code='C-01', sequence=10),
        _shelf(db_session, doc_org, doc_user, code='A-01', sequence=20),
    ]


@pytest.mark.integration
class TestStartingOverSeveralDispatches:
    def test_three_dispatches_make_one_session_walked_in_pick_path_order(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
        shelves: list[StorageLocation],
    ) -> None:
        docs = []
        for shelf in shelves:
            record = sow(
                db_session, async_engine_fixture, doc_org, doc_template, shelf.id, 10
            )
            docs.append(
                _dispatch(client, doc_auth_headers, doc_partner, shelf, record, 1)
            )

        resp = _start(client, doc_auth_headers, *docs)

        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        body = resp.json()
        assert body['document_id'] == docs[0]['id']
        # The walk follows the shelves' numbers: C-01, A-01, B-01.
        assert [ln['document_number'] for ln in body['lines']] == [
            docs[1]['number'],
            docs[2]['number'],
            docs[0]['number'],
        ]
        assert [ln['document_id'] for ln in body['lines']] == [
            docs[1]['id'],
            docs[2]['id'],
            docs[0]['id'],
        ]
        # Progress per document, in the order they were chosen.
        assert [
            (d['document_number'], d['status'], d['total_lines'], d['pending_lines'])
            for d in body['documents']
        ] == [(doc['number'], 'picking', 1, 1) for doc in docs]
        assert body['total_lines'] == 3

        # One session, reached through any of its documents.
        for doc in docs:
            listed = client.get(
                f'/api/v1/warehouse/documents/{doc["id"]}/picking',
                headers=doc_auth_headers,
            )
            assert [s['id'] for s in listed.json()['items']] == [body['id']]
            got = client.get(
                f'/api/v1/warehouse/documents/{doc["id"]}/picking/{body["id"]}',
                headers=doc_auth_headers,
            )
            assert got.status_code == status.HTTP_200_OK

        # Opening is journaled on every document the session picks.
        entries = db_session.scalars(
            select(AuditLog).where(
                AuditLog.target_id.in_([uuid.UUID(d['id']) for d in docs])
            )
        ).all()
        opened = [
            e for e in entries if (e.snapshot or {}).get('wms_session_id') == body['id']
        ]
        assert sorted(str(e.target_id) for e in opened) == sorted(d['id'] for d in docs)
        assert (opened[0].snapshot or {})['picked_together'] == [
            d['number'] for d in docs
        ]

    def test_a_draft_refuses_the_whole_start_and_is_named(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
        shelves: list[StorageLocation],
    ) -> None:
        record = sow(
            db_session, async_engine_fixture, doc_org, doc_template, shelves[0].id, 10
        )
        ready = _dispatch(client, doc_auth_headers, doc_partner, shelves[0], record, 1)
        draft = _dispatch(
            client,
            doc_auth_headers,
            doc_partner,
            shelves[0],
            record,
            1,
            confirm=False,
        )

        resp = _start(client, doc_auth_headers, ready, draft)

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert draft['number'] in resp.text
        assert 'not confirmed' in resp.text
        assert _sessions_holding(db_session, ready) == 0

    def test_a_dispatch_already_in_a_session_refuses_the_whole_start(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
        shelves: list[StorageLocation],
    ) -> None:
        record = sow(
            db_session, async_engine_fixture, doc_org, doc_template, shelves[0].id, 10
        )
        ready = _dispatch(client, doc_auth_headers, doc_partner, shelves[0], record, 1)
        busy = _dispatch(client, doc_auth_headers, doc_partner, shelves[0], record, 1)
        held = client.post(
            f'/api/v1/warehouse/documents/{busy["id"]}/picking/start',
            headers=doc_auth_headers,
        )
        assert held.status_code == status.HTTP_201_CREATED

        # The caller's own session counts too: a document is picked in one
        # session at a time.
        resp = _start(client, doc_auth_headers, ready, busy)

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert busy['number'] in resp.text
        assert cast(str, doc_user.full_name) in resp.text
        assert _sessions_holding(db_session, ready) == 0

    def test_a_session_left_open_midway_is_handed_back_over_the_same_dispatches(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_template: ProductTemplate,
        two_dispatches: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    ) -> None:
        """The sheet closed mid-way leaves the session open; starting again walks on.

        The register offers the start over the same dispatches once the sheet
        is gone, and the single-document start had always answered it with the
        session already open — the multi-document start refused it instead,
        so the scans recorded there were reachable from nowhere in the list.
        """
        a, b, session = two_dispatches
        sid = session['id']
        scan = client.post(
            f'/api/v1/warehouse/documents/{a["id"]}/picking/{sid}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 1},
        )
        assert scan.status_code == status.HTTP_200_OK, scan.text
        # What the sheet's own close sends: the scans stay, nothing is put back.
        closed = client.post(
            f'/api/v1/warehouse/documents/{a["id"]}/picking/{sid}/pause',
            headers=doc_auth_headers,
        )
        assert closed.status_code == status.HTTP_204_NO_CONTENT, closed.text

        again = _start(client, doc_auth_headers, a, b)

        assert again.status_code == status.HTTP_201_CREATED, again.text
        assert again.json()['id'] == sid
        # One session over them, not a second beside it, and the scan kept.
        db_session.expire_all()
        assert db_session.scalar(select(func.count()).select_from(WmsPickSession)) == 1
        assert (
            sum(float(line['picked_quantity']) for line in again.json()['lines']) == 1.0
        )

    def test_another_organizations_document_refuses_the_whole_start(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
        shelves: list[StorageLocation],
    ) -> None:
        record = sow(
            db_session, async_engine_fixture, doc_org, doc_template, shelves[0].id, 10
        )
        ready = _dispatch(client, doc_auth_headers, doc_partner, shelves[0], record, 1)

        other_org = h.create_org(
            'Other Org', ['core', 'items', 'locations', 'warehouse']
        )
        other_user = h.create_user(other_org, email='other@example.com')
        other_headers = h.get_auth_headers(other_user)
        other_shelf = _shelf(db_session, other_org, other_user, code='X-01', sequence=1)
        other_template = h.create_template(other_org, name='Theirs', barcode=None)
        other_record = sow(
            db_session,
            async_engine_fixture,
            other_org,
            other_template,
            other_shelf.id,
            10,
        )
        other_partner = h.create_partner(other_org, other_user, name='Their Client')
        theirs = _dispatch(
            client, other_headers, other_partner, other_shelf, other_record, 1
        )

        resp = _start(client, doc_auth_headers, ready, theirs)

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert theirs['id'] in resp.text
        # Nothing of theirs is told: not the number, not the status.
        assert theirs['number'] not in resp.text
        assert _sessions_holding(db_session, ready) == 0

    def test_a_document_that_is_not_a_dispatch_refuses_the_whole_start(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_template: ProductTemplate,
        shelves: list[StorageLocation],
    ) -> None:
        record = sow(
            db_session, async_engine_fixture, doc_org, doc_template, shelves[0].id, 10
        )
        ready = _dispatch(client, doc_auth_headers, doc_partner, shelves[0], record, 1)
        # A transfer is pickable on its own, but it is not a dispatch.
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INT',
                'source_location_id': str(shelves[0].id),
                'target_location_id': str(shelves[1].id),
                'lines': [{'item_id': str(record.id), 'expected_quantity': 1}],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        transfer_id = resp.json()['id']
        resp = client.patch(
            f'/api/v1/warehouse/documents/{transfer_id}/confirm',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        transfer = resp.json()

        resp = _start(client, doc_auth_headers, ready, transfer)

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
        assert transfer['number'] in resp.text
        assert 'not a dispatch' in resp.text
        assert _sessions_holding(db_session, ready) == 0


@pytest.fixture
def two_dispatches(
    client: TestClient,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    doc_org: Organization,
    doc_auth_headers: dict[str, str],
    doc_partner: Partner,
    doc_template: ProductTemplate,
    product_y: ProductTemplate,
    shelves: list[StorageLocation],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """A: 2 of X off one shelf; B: 3 of Y off another; one session over both."""
    x = sow(db_session, async_engine_fixture, doc_org, doc_template, shelves[0].id, 10)
    y = sow(db_session, async_engine_fixture, doc_org, product_y, shelves[1].id, 10)
    a = _dispatch(client, doc_auth_headers, doc_partner, shelves[0], x, 2)
    b = _dispatch(client, doc_auth_headers, doc_partner, shelves[1], y, 3)
    resp = _start(client, doc_auth_headers, a, b)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return a, b, resp.json()


def _journaled(
    db: Session, session_id: str, *docs: dict[str, Any]
) -> list[tuple[str, str, uuid.UUID | None]]:
    """The session's journal entries on *docs*: (status, number, who), sorted."""
    db.expire_all()
    entries = db.scalars(
        select(AuditLog).where(
            AuditLog.target_id.in_([uuid.UUID(d['id']) for d in docs])
        )
    ).all()
    snapshots = [(e.snapshot or {}, e.user_id) for e in entries]
    return sorted(
        (snap['wms_session_status'], snap['number'], who)
        for snap, who in snapshots
        if snap.get('wms_session_id') == session_id
    )


def _line_of(session: dict[str, Any], doc: dict[str, Any]) -> str:
    return next(
        cast(str, ln['id']) for ln in session['lines'] if ln['document_id'] == doc['id']
    )


@pytest.mark.integration
class TestEachDispatchResolvesOnItsOwn:
    def test_a_fully_picked_dispatch_completes_while_its_partner_comes_up_short(
        self,
        client: TestClient,
        db_session: Session,
        doc_user: User,
        doc_auth_headers: dict[str, str],
        doc_template: ProductTemplate,
        two_dispatches: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    ) -> None:
        a, b, session = two_dispatches
        sid = session['id']
        base = f'/api/v1/warehouse/documents/{a["id"]}/picking/{sid}'

        scan = client.post(
            f'{base}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 2},
        )
        assert scan.status_code == status.HTTP_200_OK, scan.text
        assert scan.json()['session_complete'] is False

        state = client.get(base, headers=doc_auth_headers).json()
        assert state['status'] == 'active'
        assert [(d['document_id'], d['status']) for d in state['documents']] == [
            (a['id'], 'all_picked'),
            (b['id'], 'picking'),
        ]

        # B still has a pending line: the session holds it.
        held = client.patch(
            f'/api/v1/warehouse/documents/{b["id"]}/complete', headers=doc_auth_headers
        )
        assert held.status_code == status.HTTP_409_CONFLICT, held.text

        # A is done with the session and completes through the usual door.
        done = client.patch(
            f'/api/v1/warehouse/documents/{a["id"]}/complete', headers=doc_auth_headers
        )
        assert done.status_code == status.HTTP_200_OK, done.text
        assert done.json()['status'] == 'COMPLETED'

        # B comes up short — through B's own route to the same session.
        short = client.post(
            f'/api/v1/warehouse/documents/{b["id"]}/picking/{sid}/short-pick',
            headers=doc_auth_headers,
            json={
                'line_id': _line_of(session, b),
                'picked_quantity': 1,
                'discrepancy_code': 'SHORTAGE',
            },
        )
        assert short.status_code == status.HTTP_200_OK, short.text
        assert short.json()['session_complete'] is True

        state = client.get(base, headers=doc_auth_headers).json()
        assert state['status'] == 'short_pick'
        # Opened and closed, each on both documents.
        assert _journaled(db_session, sid, a, b) == sorted(
            (st, doc['number'], doc_user.id)
            for st in ('active', 'short_pick')
            for doc in (a, b)
        )
        assert [(d['status'], d['document_status']) for d in state['documents']] == [
            ('all_picked', 'COMPLETED'),
            ('short', 'CONFIRMED'),
        ]

        finished = client.patch(
            f'/api/v1/warehouse/documents/{b["id"]}/complete', headers=doc_auth_headers
        )
        assert finished.status_code == status.HTTP_200_OK, finished.text
        lines = finished.json()['lines']
        assert [float(ln['done_quantity']) for ln in lines] == [1.0]

    def test_a_dispatch_with_a_skipped_line_is_not_reported_as_picked(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_template: ProductTemplate,
        two_dispatches: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    ) -> None:
        a, b, session = two_dispatches
        base = f'/api/v1/warehouse/documents/{a["id"]}/picking/{session["id"]}'

        scan = client.post(
            f'{base}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 2},
        )
        assert scan.status_code == status.HTTP_200_OK, scan.text
        skip = client.post(
            f'{base}/skip',
            headers=doc_auth_headers,
            params={'line_id': _line_of(session, b)},
        )
        assert skip.status_code == status.HTTP_200_OK, skip.text
        assert skip.json()['session_complete'] is True

        state = client.get(base, headers=doc_auth_headers).json()
        assert [(d['document_id'], d['status']) for d in state['documents']] == [
            (a['id'], 'all_picked'),
            (b['id'], 'short'),
        ]

    def test_undo_and_skip_work_on_the_lines_of_either_dispatch(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_template: ProductTemplate,
        product_y: ProductTemplate,
        two_dispatches: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    ) -> None:
        a, b, session = two_dispatches
        sid = session['id']
        via_a = f'/api/v1/warehouse/documents/{a["id"]}/picking/{sid}'
        via_b = f'/api/v1/warehouse/documents/{b["id"]}/picking/{sid}'

        for barcode, qty in ((doc_template.barcode, 2), (product_y.barcode, 1)):
            resp = client.post(
                f'{via_a}/scan',
                headers=doc_auth_headers,
                json={'barcode': barcode, 'quantity': qty},
            )
            assert resp.status_code == status.HTTP_200_OK, resp.text

        undo_a = client.post(
            f'{via_b}/undo',
            headers=doc_auth_headers,
            params={'line_id': _line_of(session, a)},
        )
        assert undo_a.status_code == status.HTTP_200_OK, undo_a.text
        undo_b = client.post(
            f'{via_a}/undo',
            headers=doc_auth_headers,
            params={'line_id': _line_of(session, b)},
        )
        assert undo_b.status_code == status.HTTP_200_OK, undo_b.text
        db_session.expire_all()
        assert [
            line.done_quantity
            for line in db_session.scalars(
                select(DocumentLine).where(
                    DocumentLine.document_id.in_(
                        [uuid.UUID(a['id']), uuid.UUID(b['id'])]
                    )
                )
            ).all()
        ] == [Decimal('0'), Decimal('0')]

        skip_b = client.post(
            f'{via_a}/skip',
            headers=doc_auth_headers,
            params={'line_id': _line_of(session, b)},
        )
        assert skip_b.status_code == status.HTTP_200_OK, skip_b.text
        skip_a = client.post(
            f'{via_b}/skip',
            headers=doc_auth_headers,
            params={'line_id': _line_of(session, a)},
        )
        assert skip_a.status_code == status.HTTP_200_OK, skip_a.text
        assert skip_a.json()['session_complete'] is True

    def test_a_completed_dispatchs_lines_are_out_of_the_sessions_reach(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_template: ProductTemplate,
        product_y: ProductTemplate,
        two_dispatches: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    ) -> None:
        a, b, session = two_dispatches
        sid = session['id']
        base = f'/api/v1/warehouse/documents/{b["id"]}/picking/{sid}'
        client.post(
            f'{base}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 2},
        )
        done = client.patch(
            f'/api/v1/warehouse/documents/{a["id"]}/complete', headers=doc_auth_headers
        )
        assert done.status_code == status.HTTP_200_OK, done.text

        # Undoing a line of a completed document would rewrite it.
        undo = client.post(
            f'{base}/undo',
            headers=doc_auth_headers,
            params={'line_id': _line_of(session, a)},
        )
        assert undo.status_code == status.HTTP_400_BAD_REQUEST, undo.text
        short = client.post(
            f'{base}/short-pick',
            headers=doc_auth_headers,
            json={
                'line_id': _line_of(session, a),
                'picked_quantity': 1,
                'discrepancy_code': 'SHORTAGE',
            },
        )
        assert short.status_code == status.HTTP_400_BAD_REQUEST, short.text

        # B is still picked: a scan answers to its own document, which is
        # open, not to the session's first, which is completed.
        scan = client.post(
            f'{base}/scan',
            headers=doc_auth_headers,
            json={'barcode': product_y.barcode, 'quantity': 1},
        )
        assert scan.json()['status'] == 'picked', scan.text

        # Cancelling releases B and leaves A's record as it was completed.
        cancel = client.post(f'{base}/cancel', headers=doc_auth_headers)
        assert cancel.status_code == status.HTTP_204_NO_CONTENT, cancel.text
        db_session.expire_all()
        a_line = db_session.scalar(
            select(DocumentLine).where(DocumentLine.document_id == uuid.UUID(a['id']))
        )
        assert a_line is not None and a_line.done_quantity == Decimal('2')

    def test_cancel_releases_every_dispatch(
        self,
        client: TestClient,
        h: ModuleTestHelper,
        db_session: Session,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_template: ProductTemplate,
        two_dispatches: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    ) -> None:
        a, b, session = two_dispatches
        sid = session['id']
        client.post(
            f'/api/v1/warehouse/documents/{a["id"]}/picking/{sid}/scan',
            headers=doc_auth_headers,
            json={'barcode': doc_template.barcode, 'quantity': 1},
        )

        # A colleague releases it — release is the door anyone may open, and
        # the journal names who did.
        colleague = h.create_user(doc_org, email='colleague@example.com')
        cancel = client.post(
            f'/api/v1/warehouse/documents/{b["id"]}/picking/{sid}/release',
            headers=h.get_auth_headers(colleague),
        )
        assert cancel.status_code == status.HTTP_204_NO_CONTENT, cancel.text
        assert [
            e for e in _journaled(db_session, sid, a, b) if e[0] == 'cancelled'
        ] == sorted(('cancelled', doc['number'], colleague.id) for doc in (a, b))

        db_session.expire_all()
        assert all(
            line.done_quantity == Decimal('0')
            for line in db_session.scalars(
                select(DocumentLine).where(
                    DocumentLine.document_id.in_(
                        [uuid.UUID(a['id']), uuid.UUID(b['id'])]
                    )
                )
            ).all()
        )
        again = _start(client, doc_auth_headers, b, a)
        assert again.status_code == status.HTTP_201_CREATED, again.text
        assert again.json()['id'] != sid

    def test_a_single_start_on_a_listed_dispatch_hands_back_the_session(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        two_dispatches: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    ) -> None:
        _, b, session = two_dispatches
        resp = client.post(
            f'/api/v1/warehouse/documents/{b["id"]}/picking/start',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        assert resp.json()['id'] == session['id']
        assert len(resp.json()['documents']) == 2
