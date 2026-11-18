"""A typed count is something only a receipt has.

``expected_is_count`` says the expected quantity is a figure somebody typed to
get a row, so receiving more than it is the true count. The flag was accepted
on any document type, and the shared picking path honoured it without asking
the direction: a dispatch line an API caller had flagged let a picker take
more than was asked for. The flag now survives only on a receipt line, and a
picking session stops at the expected quantity whatever the line carries.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select, update
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


def _create(
    client: TestClient,
    headers: dict[str, str],
    doc_type: str,
    body: dict[str, Any],
    line: dict[str, Any],
) -> dict[str, Any]:
    created = client.post(
        _DOCS,
        headers=headers,
        json={
            'type': doc_type,
            'lines': [{'expected_quantity': 4, 'expected_is_count': True, **line}],
            **body,
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    return cast(dict[str, Any], created.json())


def test_a_receipt_line_keeps_the_flag(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_partner: Partner,
    doc_target_location: StorageLocation,
    doc_template: ProductTemplate,
) -> None:
    doc = _create(
        client,
        doc_auth_headers,
        'IN',
        {
            'partner_id': str(doc_partner.id),
            'target_location_id': str(doc_target_location.id),
        },
        {'product_template_id': str(doc_template.id)},
    )

    assert doc['lines'][0]['expected_is_count'] is True


def test_a_dispatch_line_drops_the_flag(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_partner: Partner,
    doc_source_location: StorageLocation,
    doc_target_location: StorageLocation,
    doc_template: ProductTemplate,
    db_session: Session,
) -> None:
    doc = _create(
        client,
        doc_auth_headers,
        'OUT',
        {
            'partner_id': str(doc_partner.id),
            'source_location_id': str(doc_source_location.id),
            'target_location_id': str(doc_target_location.id),
        },
        {'product_template_id': str(doc_template.id)},
    )

    assert doc['lines'][0]['expected_is_count'] is False
    stored = db_session.scalars(
        select(DocumentLine).where(DocumentLine.document_id == uuid.UUID(doc['id']))
    ).one()
    assert stored.expected_is_count is False


@pytest.fixture
def flagged_pick(
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
    """A picking session over a dispatch line that carries the flag anyway."""
    _sow(
        db_session,
        async_engine_fixture,
        doc_org,
        doc_template,
        doc_source_location.id,
        '20',
    )
    doc = _create(
        client,
        doc_auth_headers,
        'OUT',
        {
            'partner_id': str(doc_partner.id),
            'source_location_id': str(doc_source_location.id),
            'target_location_id': str(doc_target_location.id),
        },
        {
            'item_id': str(doc_item.id),
            'product_template_id': str(doc_item.template_id or doc_template.id),
        },
    )
    # Data written before the flag was refused, or by a caller that bypassed it.
    db_session.execute(
        update(DocumentLine)
        .where(DocumentLine.document_id == uuid.UUID(doc['id']))
        .values(expected_is_count=True)
    )
    db_session.commit()
    confirmed = client.patch(f'{_DOCS}/{doc["id"]}/confirm', headers=doc_auth_headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    session = client.post(
        f'{_DOCS}/{doc["id"]}/picking/start', headers=doc_auth_headers
    )
    assert session.status_code == status.HTTP_201_CREATED, session.text
    return {
        'doc_id': doc['id'],
        'session_id': session.json()['id'],
        'line_id': session.json()['lines'][0]['id'],
        'barcode': doc_template.barcode,
    }


def test_a_pick_over_a_flagged_line_stops_at_the_expected_quantity(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    flagged_pick: dict[str, str],
) -> None:
    scanned = client.post(
        f'{_DOCS}/{flagged_pick["doc_id"]}/picking/{flagged_pick["session_id"]}/scan',
        headers=doc_auth_headers,
        json={'barcode': flagged_pick['barcode'], 'quantity': '6'},
    )

    assert scanned.status_code == status.HTTP_200_OK, scanned.text
    assert scanned.json()['status'] == 'over_quantity'


def test_a_short_pick_above_a_flagged_line_is_refused(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    flagged_pick: dict[str, str],
) -> None:
    resp = client.post(
        f'{_DOCS}/{flagged_pick["doc_id"]}/picking/{flagged_pick["session_id"]}'
        '/short-pick',
        headers=doc_auth_headers,
        json={
            'line_id': flagged_pick['line_id'],
            'picked_quantity': 6,
            'discrepancy_code': 'OTHER',
            'discrepancy_reason': 'Counted',
        },
    )

    assert resp.status_code >= status.HTTP_400_BAD_REQUEST, resp.text
