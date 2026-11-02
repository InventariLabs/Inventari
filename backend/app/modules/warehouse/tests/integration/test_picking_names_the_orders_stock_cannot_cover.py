"""Before a pick walk starts, the dispatches stock cannot cover are named.

A confirmed dispatch reserved its stock, but a count, a scrap or a move since
can leave the shelf with less than the document orders. Picking used to start
over it regardless and the picker found out line by line at the shelf. The
coverage read names each short product with what was ordered and what is
there, so the person starts without those documents or with them anyway.

What the shelf has for a document: its own reservation counts, every other
document's does not, and stock a picker may not take — the quarantine shelf,
a receiving area — is not there at all.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_reservation import StockReservation
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.warehouse.tests.integration._records import sow as _sow

pytestmark = pytest.mark.integration

_DOCS = '/api/v1/warehouse/documents'
_COVERAGE = '/api/v1/warehouse/picking/coverage'


def _dispatch(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    item: Item,
    template: ProductTemplate,
    source: StorageLocation,
    target: StorageLocation,
    quantity: int,
) -> str:
    created = client.post(
        _DOCS,
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner.id),
            'source_location_id': str(source.id),
            'target_location_id': str(target.id),
            'lines': [
                {
                    'item_id': str(item.id),
                    'product_template_id': str(item.template_id or template.id),
                    'expected_quantity': quantity,
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = cast(str, created.json()['id'])
    confirmed = client.patch(f'{_DOCS}/{doc_id}/confirm', headers=headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    return doc_id


def _coverage(
    client: TestClient, headers: dict[str, str], *doc_ids: str
) -> list[dict[str, Any]]:
    resp = client.post(_COVERAGE, headers=headers, json={'document_ids': list(doc_ids)})
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return cast(list[dict[str, Any]], resp.json()['documents'])


def test_a_dispatch_the_shelf_no_longer_covers_is_named_with_what_is_missing(
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
    record = _sow(
        db_session,
        async_engine_fixture,
        doc_org,
        doc_template,
        doc_source_location.id,
        '20',
    )
    covered = _dispatch(
        client,
        doc_auth_headers,
        doc_partner,
        doc_item,
        doc_template,
        doc_source_location,
        doc_target_location,
        4,
    )
    assert _coverage(client, doc_auth_headers, covered) == []

    # The hold was let go, then a count found two where twenty stood.
    db_session.execute(delete(StockReservation))
    record.quantity = Decimal('2')
    db_session.commit()

    named = _coverage(client, doc_auth_headers, covered)

    assert len(named) == 1
    assert named[0]['document_id'] == covered
    assert [(ln['ordered'], ln['available']) for ln in named[0]['lines']] == [
        (4.0, 2.0)
    ]
    assert named[0]['lines'][0]['product_name']


def test_the_documents_own_reservation_is_available_to_it(
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
    # Exactly what the dispatch orders is on the shelf, and the dispatch holds
    # all of it: counted against itself it would read as nothing left.
    _sow(
        db_session,
        async_engine_fixture,
        doc_org,
        doc_template,
        doc_source_location.id,
        '4',
    )
    own = _dispatch(
        client,
        doc_auth_headers,
        doc_partner,
        doc_item,
        doc_template,
        doc_source_location,
        doc_target_location,
        4,
    )

    assert _coverage(client, doc_auth_headers, own) == []


def test_stock_on_the_quarantine_shelf_does_not_cover_a_dispatch(
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
        '10',
    )
    doc_id = _dispatch(
        client,
        doc_auth_headers,
        doc_partner,
        doc_item,
        doc_template,
        doc_source_location,
        doc_target_location,
        4,
    )
    assert _coverage(client, doc_auth_headers, doc_id) == []

    db_session.commit()
    chosen = client.put(
        '/api/v1/warehouse/profile',
        headers=doc_auth_headers,
        json={'quarantine_location_id': str(doc_source_location.id)},
    )
    assert chosen.status_code == status.HTTP_200_OK, chosen.text

    named = _coverage(client, doc_auth_headers, doc_id)

    assert [(ln['ordered'], ln['available']) for ln in named[0]['lines']] == [
        (4.0, 0.0)
    ]


def test_stock_in_a_receiving_area_does_not_cover_a_dispatch(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    doc_item: Item,
    doc_template: ProductTemplate,
    doc_org: Organization,
    h: ModuleTestHelper,
    doc_storage_type: StorageType,
    doc_user: User,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
) -> None:
    warehouse = h.create_storage_location(
        doc_org, doc_storage_type, doc_user, name='Main Warehouse'
    )
    chosen = client.put(
        f'/api/v1/warehouse/putaway/receiving-modes/{warehouse.id}',
        headers=doc_auth_headers,
        json={'two_step': True},
    )
    assert chosen.status_code == status.HTTP_200_OK, chosen.text
    area = UUID(chosen.json()['receiving_location_id'])
    waiting = _sow(db_session, async_engine_fixture, doc_org, doc_template, area, '10')
    # Dispatched from the whole warehouse, the only stock of the product is
    # the delivery that has not been put away yet.
    doc_id = _dispatch(
        client,
        doc_auth_headers,
        doc_partner,
        waiting,
        doc_template,
        warehouse,
        doc_target_location,
        4,
    )

    named = _coverage(client, doc_auth_headers, doc_id)

    assert [(ln['ordered'], ln['available']) for ln in named[0]['lines']] == [
        (4.0, 0.0)
    ]


def test_a_dispatch_a_session_already_holds_is_not_asked_about_again(
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
    # Pressing Pick again over a document an open session holds hands that
    # session back whole: leaving a short document out could not be kept,
    # and its shortfall was named when the session started.
    record = _sow(
        db_session,
        async_engine_fixture,
        doc_org,
        doc_template,
        doc_source_location.id,
        '20',
    )
    args = (
        doc_partner,
        doc_item,
        doc_template,
        doc_source_location,
        doc_target_location,
        4,
    )
    held = _dispatch(client, doc_auth_headers, *args)
    free = _dispatch(client, doc_auth_headers, *args)
    started = client.post(
        '/api/v1/warehouse/picking/start',
        headers=doc_auth_headers,
        json={'document_ids': [held]},
    )
    assert started.status_code == status.HTTP_201_CREATED, started.text

    db_session.execute(delete(StockReservation))
    record.quantity = Decimal('2')
    db_session.commit()

    named = _coverage(client, doc_auth_headers, held, free)

    assert [doc['document_id'] for doc in named] == [free]
