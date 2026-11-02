"""A module's pre-post check can hold a document until the module lets it go.

The approvals module used to be the only thing that ever parked a document,
and the warehouse called it to do so. The parking is now the document's own
state: a check answers ``'hold'`` at confirmation, the document waits in
PENDING_APPROVAL under that module's name, and only that module releases it,
takes the hold back or sends it to a draft — through ``warehouse_api``, which
any module can call. These tests hold documents with a module of their own,
so they say nothing about approvals and would hold for a second gating
module exactly as they do here.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from app.core.contracts import DocumentToPostDTO
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import Document, DocumentStatus
from app.modules.warehouse.warehouse_api import warehouse_api
from tests.integration._shelf import run_in_async_session

_MODULE = 'quality_holds'


class _QualityHold:
    """A module that wants a quality check before any dispatch moves."""

    def __init__(self) -> None:
        self.hold = True
        self.withdrawn: list[tuple[UUID, UUID | None]] = []

    async def __call__(
        self, db: Any, org_id: UUID, doc: DocumentToPostDTO
    ) -> Literal['hold'] | None:
        return 'hold' if self.hold and doc.stage == 'confirm' else None

    async def on_withdrawn(
        self, db: Any, org_id: UUID, doc_id: UUID, user_id: UUID | None
    ) -> None:
        self.withdrawn.append((doc_id, user_id))


@pytest.fixture
def quality_hold(db_session: Session, doc_org: Organization) -> Iterator[_QualityHold]:
    doc_org.enabled_modules = [*doc_org.enabled_modules, _MODULE]
    db_session.commit()
    check = _QualityHold()
    warehouse_api.register_pre_post_check(
        _MODULE, check, on_withdrawn=check.on_withdrawn
    )
    yield check

    # The registry is process-wide; leave the module with nothing to hold.
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


def _confirm(client: TestClient, headers: dict[str, str], doc_id: str) -> None:
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text


def _document(db_session: Session, doc_id: str) -> Document:
    db_session.expire_all()
    doc = db_session.get(Document, UUID(doc_id))
    assert doc is not None
    return doc


def _shelf_quantity(db_session: Session, item: Item) -> Decimal:
    db_session.expire_all()
    shelf = db_session.get(Item, item.id)
    assert shelf is not None
    return shelf.quantity


@pytest.mark.integration
class TestAModuleCanHoldADocument:
    def test_a_hold_parks_the_confirmed_document_under_the_modules_name(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
        quality_hold: _QualityHold,
    ) -> None:
        doc_id = _draft(
            client, doc_auth_headers, doc_partner, doc_source_location, doc_stock_item
        )
        _confirm(client, doc_auth_headers, doc_id)

        doc = _document(db_session, doc_id)
        assert doc.status == DocumentStatus.PENDING_APPROVAL.value
        assert doc.held_by == _MODULE
        # Confirmed all the same: numbered, with its confirmer on it.
        assert not doc.number.startswith('DRAFT-')
        assert doc.confirmed_by is not None

        completed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert completed.status_code == status.HTTP_409_CONFLICT, completed.text
        assert completed.json()['detail']['code'] == 'APPROVAL_REQUIRED'
        assert _shelf_quantity(db_session, doc_stock_item) == Decimal('100')

    def test_the_holding_module_releases_it_and_the_one_step_post_completes(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
        quality_hold: _QualityHold,
    ) -> None:
        doc_id = _draft(
            client, doc_auth_headers, doc_partner, doc_source_location, doc_stock_item
        )
        posted = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/post', headers=doc_auth_headers
        )
        assert posted.status_code == status.HTTP_200_OK, posted.text
        assert posted.json()['status'] == DocumentStatus.PENDING_APPROVAL.value

        # Somebody else's release is not this hold's: nothing moves.
        async def _foreign(session: AsyncSession) -> None:
            await warehouse_api.release_document_async(
                session, doc_org.id, UUID(doc_id), 'someone_else'
            )

        run_in_async_session(async_engine_fixture, _foreign)
        assert _document(db_session, doc_id).held_by == _MODULE

        async def _release(session: AsyncSession) -> None:
            await warehouse_api.release_document_async(
                session, doc_org.id, UUID(doc_id), _MODULE
            )

        run_in_async_session(async_engine_fixture, _release)
        doc = _document(db_session, doc_id)
        # The one-step press promised the posting too; the release keeps it.
        assert doc.status == DocumentStatus.COMPLETED.value
        assert doc.held_by is None
        assert _shelf_quantity(db_session, doc_stock_item) == Decimal('95')

    def test_a_withdrawn_hold_leaves_it_confirmed_and_free_to_post(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
        quality_hold: _QualityHold,
    ) -> None:
        doc_id = _draft(
            client, doc_auth_headers, doc_partner, doc_source_location, doc_stock_item
        )
        _confirm(client, doc_auth_headers, doc_id)

        async def _withdraw(session: AsyncSession) -> None:
            await warehouse_api.withdraw_hold_async(
                session, doc_org.id, UUID(doc_id), _MODULE
            )

        run_in_async_session(async_engine_fixture, _withdraw)
        doc = _document(db_session, doc_id)
        assert doc.status == DocumentStatus.CONFIRMED.value
        assert doc.held_by is None

        completed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text

    def test_a_refusal_sends_it_back_to_a_draft(
        self,
        client: TestClient,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
        quality_hold: _QualityHold,
    ) -> None:
        doc_id = _draft(
            client, doc_auth_headers, doc_partner, doc_source_location, doc_stock_item
        )
        _confirm(client, doc_auth_headers, doc_id)

        async def _refuse(session: AsyncSession) -> None:
            await warehouse_api.return_to_draft_async(
                session, doc_org.id, UUID(doc_id), _MODULE
            )

        run_in_async_session(async_engine_fixture, _refuse)
        doc = _document(db_session, doc_id)
        assert doc.status == DocumentStatus.DRAFT.value
        assert doc.held_by is None
        assert doc.confirmed_by is None

    def test_a_hold_of_a_module_switched_off_stands_down(
        self,
        client: TestClient,
        db_session: Session,
        doc_org: Organization,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
        quality_hold: _QualityHold,
    ) -> None:
        doc_id = _draft(
            client, doc_auth_headers, doc_partner, doc_source_location, doc_stock_item
        )
        _confirm(client, doc_auth_headers, doc_id)
        doc_org.enabled_modules = [
            name for name in doc_org.enabled_modules if name != _MODULE
        ]
        db_session.commit()

        completed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text
        assert _shelf_quantity(db_session, doc_stock_item) == Decimal('95')

    def test_cancelling_a_held_document_tells_the_module(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
        quality_hold: _QualityHold,
    ) -> None:
        doc_id = _draft(
            client, doc_auth_headers, doc_partner, doc_source_location, doc_stock_item
        )
        _confirm(client, doc_auth_headers, doc_id)

        cancelled = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel', headers=doc_auth_headers
        )
        assert cancelled.status_code == status.HTTP_200_OK, cancelled.text
        assert [doc for doc, _ in quality_hold.withdrawn] == [UUID(doc_id)]
        assert _document(db_session, doc_id).status == DocumentStatus.CANCELLED.value
