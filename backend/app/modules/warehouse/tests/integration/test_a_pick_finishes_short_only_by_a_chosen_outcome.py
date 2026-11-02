"""A dispatch finishes with a line short only after someone chose that.

A shortfall is a decision: the shortage owes the rest to the customer on a
backorder, any other reason closes the gap. Three doors used to write the
choice for the person — a short pick sent without a reason was stored as a
shortage, a session left by closing its sheet wrote a shortage on every line
it had not finished, and a bodiless completion booked a part-picked line as
it stood. Each now waits for an answer, like the skipped line beside them.
"""

import uuid
from decimal import Decimal
from typing import Any, cast

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
from app.modules.warehouse.models import DocumentLine
from app.modules.warehouse.tests.integration._records import sow as _sow

pytestmark = pytest.mark.integration

_DOCS = '/api/v1/warehouse/documents'


@pytest.fixture
def started(
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
    """A confirmed dispatch of 4 with a picking session open over it."""
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
    return {
        'doc_id': doc_id,
        'session_id': session.json()['id'],
        'line_id': session.json()['lines'][0]['id'],
    }


def _doc_line(db: Session, doc_id: str) -> DocumentLine:
    db.expire_all()
    return db.scalars(
        select(DocumentLine).where(DocumentLine.document_id == uuid.UUID(doc_id))
    ).one()


def _backorders(client: TestClient, headers: dict[str, str], doc_id: str) -> list[Any]:
    listed = client.get(_DOCS, headers=headers).json()
    return [d for d in listed['items'] if d.get('backorder_id') == doc_id]


def test_a_short_pick_with_no_outcome_is_refused_and_records_nothing(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    started: dict[str, str],
    db_session: Session,
) -> None:
    resp = client.post(
        f'{_DOCS}/{started["doc_id"]}/picking/{started["session_id"]}/short-pick',
        headers=doc_auth_headers,
        json={'line_id': started['line_id'], 'picked_quantity': 2},
    )

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text
    line = _doc_line(db_session, started['doc_id'])
    assert line.discrepancy_code is None
    assert line.done_quantity == 0


def test_a_short_pick_with_a_chosen_outcome_is_recorded_as_chosen(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    started: dict[str, str],
    db_session: Session,
) -> None:
    resp = client.post(
        f'{_DOCS}/{started["doc_id"]}/picking/{started["session_id"]}/short-pick',
        headers=doc_auth_headers,
        json={
            'line_id': started['line_id'],
            'picked_quantity': 2,
            'discrepancy_code': 'OTHER',
            'discrepancy_reason': 'Two boxes were damaged',
        },
    )

    assert resp.status_code == status.HTTP_200_OK, resp.text
    line = _doc_line(db_session, started['doc_id'])
    assert line.discrepancy_code == 'OTHER'
    assert line.done_quantity == Decimal('2')


def test_a_short_pick_with_an_unknown_code_is_refused_and_leaves_the_document_readable(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    started: dict[str, str],
    db_session: Session,
) -> None:
    resp = client.post(
        f'{_DOCS}/{started["doc_id"]}/picking/{started["session_id"]}/short-pick',
        headers=doc_auth_headers,
        json={
            'line_id': started['line_id'],
            'picked_quantity': 2,
            'discrepancy_code': 'DAMAGED',
        },
    )

    # Body validation answers 422 everywhere in this API (a translated list of
    # the accepted values), the same as the receiving request's code.
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, resp.text
    assert 'DAMAGE' in resp.text
    assert _doc_line(db_session, started['doc_id']).discrepancy_code is None
    read = client.get(f'{_DOCS}/{started["doc_id"]}', headers=doc_auth_headers)
    assert read.status_code == status.HTTP_200_OK, read.text


def test_leaving_the_sheet_does_not_choose_a_shortage_for_the_unpicked_line(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    started: dict[str, str],
    db_session: Session,
) -> None:
    paused = client.post(
        f'{_DOCS}/{started["doc_id"]}/picking/{started["session_id"]}/pause',
        headers=doc_auth_headers,
    )
    assert paused.status_code == status.HTTP_204_NO_CONTENT, paused.text

    completed = client.patch(
        f'{_DOCS}/{started["doc_id"]}/complete', headers=doc_auth_headers
    )

    assert completed.status_code != status.HTTP_200_OK, completed.text
    assert _doc_line(db_session, started['doc_id']).discrepancy_code is None
    doc = client.get(f'{_DOCS}/{started["doc_id"]}', headers=doc_auth_headers).json()
    assert doc['status'] == 'CONFIRMED'
    assert _backorders(client, doc_auth_headers, started['doc_id']) == []


def test_a_part_picked_line_with_no_reason_is_not_completed_as_it_stands(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    started: dict[str, str],
    db_session: Session,
) -> None:
    client.post(
        f'{_DOCS}/{started["doc_id"]}/picking/{started["session_id"]}/pause',
        headers=doc_auth_headers,
    )
    line = _doc_line(db_session, started['doc_id'])
    line.done_quantity = Decimal('2')
    db_session.commit()

    completed = client.patch(
        f'{_DOCS}/{started["doc_id"]}/complete', headers=doc_auth_headers
    )

    assert completed.status_code != status.HTTP_200_OK, completed.text
    assert _backorders(client, doc_auth_headers, started['doc_id']) == []
