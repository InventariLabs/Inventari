"""A module's pre-post check can stop a document from posting.

A customer-specific module registers a check through ``warehouse_api``; the
posting asks it, inside its own transaction, before the document is confirmed
and again before its stock moves. A refusal reaches the reader in the
module's own words and leaves nothing behind; a module switched off for the
organization is not asked at all.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.contracts import DocumentToPostDTO
from app.core.interceptors import InterceptorError
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.stock_reservation import StockReservation
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import Document, DocumentStatus
from app.modules.warehouse.warehouse_api import warehouse_api

_MODULE = 'cert_checks'


class _CertificateCheck:
    """A module that wants a certificate for every lot it sees posted."""

    def __init__(self) -> None:
        self.refuse_at: set[str] = set()
        self.seen: list[DocumentToPostDTO] = []

    async def __call__(self, db: Any, org_id: UUID, doc: DocumentToPostDTO) -> None:
        self.seen.append(doc)
        if doc.stage in self.refuse_at:
            raise InterceptorError(
                'Missing certificate for lot PL-2210',
                error_code='CERTIFICATE_MISSING',
            )


@pytest.fixture
def certificate_check(
    db_session: Session, doc_org: Organization
) -> Iterator[_CertificateCheck]:
    doc_org.enabled_modules = [*doc_org.enabled_modules, _MODULE]
    db_session.commit()
    check = _CertificateCheck()
    warehouse_api.register_pre_post_check(_MODULE, check)
    yield check

    # The registry is process-wide; leave the module with nothing to refuse.
    async def _passes(db: Any, org_id: UUID, doc: DocumentToPostDTO) -> None:
        return None

    warehouse_api.register_pre_post_check(_MODULE, _passes)


def _draft(
    client: TestClient,
    headers: dict[str, str],
    partner: Partner,
    shelf: StorageLocation,
    item: Item,
) -> str:
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner.id),
            'source_location_id': str(shelf.id),
            'lines': [
                {
                    'item_id': str(item.id),
                    'product_template_id': str(item.template_id),
                    'expected_quantity': 5,
                    'unit_price': '10.00',
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    return cast(str, created.json()['id'])


def _shelf_quantity(db_session: Session, item: Item) -> Decimal:
    db_session.expire_all()
    shelf = db_session.get(Item, item.id)
    assert shelf is not None
    return shelf.quantity


def _reservations(db_session: Session, doc_id: str) -> int:
    return (
        db_session.scalar(
            select(func.count())
            .select_from(StockReservation)
            .where(StockReservation.document_id == UUID(doc_id))
        )
        or 0
    )


@pytest.mark.integration
class TestAModuleCanStopAPosting:
    def test_a_refused_one_step_post_says_why_and_writes_nothing(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
        certificate_check: _CertificateCheck,
    ) -> None:
        certificate_check.refuse_at = {'post'}
        doc_id = _draft(
            client, doc_auth_headers, doc_partner, doc_source_location, doc_stock_item
        )

        posted = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/post', headers=doc_auth_headers
        )

        assert posted.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT, posted.text
        detail = posted.json()['detail']
        assert detail['code'] == 'CERTIFICATE_MISSING'
        assert detail['message'] == 'Missing certificate for lot PL-2210'
        # Confirmation ran in the same transaction and went with it: still the
        # draft it was, with no number drawn and nothing reserved or moved.
        db_session.expire_all()
        doc = db_session.get(Document, UUID(doc_id))
        assert doc is not None
        assert doc.status == DocumentStatus.DRAFT.value
        assert doc.number.startswith('DRAFT-')
        assert _reservations(db_session, doc_id) == 0
        assert _shelf_quantity(db_session, doc_stock_item) == Decimal('100')

    def test_a_refused_confirmation_leaves_the_draft_a_draft(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
        certificate_check: _CertificateCheck,
    ) -> None:
        certificate_check.refuse_at = {'confirm'}
        doc_id = _draft(
            client, doc_auth_headers, doc_partner, doc_source_location, doc_stock_item
        )

        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )

        assert confirmed.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert confirmed.json()['detail']['code'] == 'CERTIFICATE_MISSING'
        db_session.expire_all()
        doc = db_session.get(Document, UUID(doc_id))
        assert doc is not None
        assert doc.status == DocumentStatus.DRAFT.value
        assert doc.number.startswith('DRAFT-')
        assert _reservations(db_session, doc_id) == 0

    def test_a_refused_completion_moves_no_stock(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
        certificate_check: _CertificateCheck,
    ) -> None:
        certificate_check.refuse_at = {'post'}
        doc_id = _draft(
            client, doc_auth_headers, doc_partner, doc_source_location, doc_stock_item
        )
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text

        completed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        assert completed.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert completed.json()['detail']['code'] == 'CERTIFICATE_MISSING'
        db_session.expire_all()
        doc = db_session.get(Document, UUID(doc_id))
        assert doc is not None
        assert doc.status == DocumentStatus.CONFIRMED.value
        assert _shelf_quantity(db_session, doc_stock_item) == Decimal('100')

    def test_a_passing_check_sees_the_document_and_lets_it_post(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
        certificate_check: _CertificateCheck,
    ) -> None:
        doc_id = _draft(
            client, doc_auth_headers, doc_partner, doc_source_location, doc_stock_item
        )

        posted = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/post', headers=doc_auth_headers
        )

        assert posted.status_code == status.HTTP_200_OK, posted.text
        assert posted.json()['status'] == DocumentStatus.COMPLETED.value
        assert _shelf_quantity(db_session, doc_stock_item) == Decimal('95')
        assert [seen.stage for seen in certificate_check.seen] == ['confirm', 'post']
        asked = certificate_check.seen[-1]
        assert asked.id == UUID(doc_id)
        assert asked.type == 'OUT'
        assert asked.partner_id == doc_partner.id
        assert asked.source_location_id == doc_source_location.id
        [line] = asked.lines
        assert line.item_id == doc_stock_item.id
        assert line.product_template_id == doc_stock_item.template_id
        assert line.expected_quantity == Decimal('5')
        # By the time the stock moves, the line says what is being posted.
        assert line.done_quantity == Decimal('5')

    def test_a_disabled_modules_check_is_not_asked(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
        certificate_check: _CertificateCheck,
    ) -> None:
        certificate_check.refuse_at = {'confirm', 'post'}
        doc_org.enabled_modules = [
            name for name in doc_org.enabled_modules if name != _MODULE
        ]
        db_session.commit()
        doc_id = _draft(
            client, doc_auth_headers, doc_partner, doc_source_location, doc_stock_item
        )

        posted = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/post', headers=doc_auth_headers
        )

        assert posted.status_code == status.HTTP_200_OK, posted.text
        assert certificate_check.seen == []
        assert _shelf_quantity(db_session, doc_stock_item) == Decimal('95')
