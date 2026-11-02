"""A correction lands where the original happened, not where its document asked.

A correction rewrites what the original did, so it happens where the
original happened. The code read the *correction document's* location — which
the correction service copies from the original document, and a document's
target is not always where its goods went: the receipt door lands them with the
record it tops up and says so in ``executed_location_id``. A correction of such
a delivery put stock onto a shelf the delivery never touched, and the
reconciliation report then named drift nobody caused — the records standing on
the record's shelf read more than that shelf's ledger.

These tests hold the pair the report compares — records against the movement
ledger, per (card, location) — on both sides of the correction, for a cardless
record and its carded twin, and read the report itself for silence.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.models.document import Document, DocumentLine
from app.modules.warehouse.tests.integration._records import (
    sow as _sow,
)


@pytest.fixture
def landing_org(h: ModuleTestHelper) -> Organization:
    org = h.create_org(
        'Correction Landing Org',
        ['core', 'items', 'locations', 'categories', 'warehouse', 'approvals', 'stats'],
    )
    h.set_module_settings(org, 'approvals', {'allow_admin_self_approve': True})
    return org


@pytest.fixture
def landing_user(h: ModuleTestHelper, landing_org: Organization) -> User:
    return h.create_user(landing_org, email='correction-landing@example.com')


@pytest.fixture
def landing_headers(h: ModuleTestHelper, landing_user: User) -> dict[str, str]:
    return h.get_auth_headers(landing_user)


def _shelf(
    h: ModuleTestHelper,
    org: Organization,
    user: User,
    *,
    type_code: str,
    name: str,
) -> StorageLocation:
    storage_type = h.create_storage_type(
        f'{name} type', type_code, organization_id=org.id
    )
    return h.create_storage_location(org, storage_type, user, name=name)


@pytest.fixture
def home_shelf(
    h: ModuleTestHelper, landing_org: Organization, landing_user: User
) -> StorageLocation:
    """The shelf the record stands on — and where its goods really are."""
    return _shelf(
        h,
        landing_org,
        landing_user,
        type_code='LANDING_HOME',
        name='Landing Home Shelf',
    )


@pytest.fixture
def asked_shelf(
    h: ModuleTestHelper, landing_org: Organization, landing_user: User
) -> StorageLocation:
    """The shelf the receipt's document asked for, which it never landed on."""
    return _shelf(
        h,
        landing_org,
        landing_user,
        type_code='LANDING_ASKED',
        name='Landing Asked Shelf',
    )


def _cardless_record(
    db_session: Session,
    org_id: UUID,
    *,
    name: str,
    location_id: UUID,
    quantity: Decimal,
) -> Item:
    item = Item(
        name=name,
        organization_id=org_id,
        template_id=None,
        storage_location_id=location_id,
        quantity=quantity,
    )
    db_session.add(item)
    db_session.flush()
    db_session.refresh(item)
    return item


def _carded_record(
    db_session: Session,
    engine: AsyncEngine,
    org_id: UUID,
    *,
    name: str,
    location_id: UUID,
    quantity: Decimal,
) -> Item:
    template = ProductTemplate(name=name, organization_id=org_id)
    db_session.add(template)
    db_session.flush()
    return _sow(db_session, engine, org_id, template, location_id, quantity)


def _seed_the_delivery(
    db_session: Session,
    org_id: UUID,
    user_id: UUID,
    *,
    item: Item,
    asked_location_id: UUID,
    landed_location_id: UUID,
    quantity: Decimal,
) -> Document:
    """The delivery a correction leans on, seeded as the receipt door left it.

    ``asked_location_id`` is the document's target; ``landed_location_id`` is
    where the goods went, which the receipt door writes into the line when the
    delivery lands with the record instead of at the document's target (see
    ``test_receipt_line_target``). The record is seeded cardless on purpose —
    that is the shape the two doors under test must adopt — and the carded twin
    is pointed at a card of its own.
    """
    doc = Document(
        organization_id=org_id,
        type='IN',
        number=f'IN/LAND/{uuid4().hex[:8]}',
        status='COMPLETED',
        target_location_id=asked_location_id,
        created_by=user_id,
    )
    db_session.add(doc)
    db_session.flush()
    db_session.add(
        DocumentLine(
            document_id=doc.id,
            item_id=item.id,
            product_template_id=item.template_id,
            quantity=quantity,
            expected_quantity=quantity,
            done_quantity=quantity,
            line_number=1,
            executed_location_id=landed_location_id,
        )
    )
    db_session.flush()
    return doc


def _moved_quantity(
    db_session: Session, org_id: UUID, template_id: UUID, location_id: UUID
) -> Decimal:
    """What the done movements of *template_id* net to on *location_id*."""
    into = db_session.scalar(
        select(func.sum(StockMove.quantity)).where(
            StockMove.organization_id == org_id,
            StockMove.product_template_id == template_id,
            StockMove.to_location_id == location_id,
            StockMove.state == 'done',
        )
    )
    out_of = db_session.scalar(
        select(func.sum(StockMove.quantity)).where(
            StockMove.organization_id == org_id,
            StockMove.product_template_id == template_id,
            StockMove.from_location_id == location_id,
            StockMove.state == 'done',
        )
    )
    return Decimal(into or 0) - Decimal(out_of or 0)


def _record_quantity(
    db_session: Session, org_id: UUID, template_id: UUID, location_id: UUID
) -> Decimal:
    total = db_session.scalar(
        select(func.sum(Item.quantity)).where(
            Item.organization_id == org_id,
            Item.template_id == template_id,
            Item.storage_location_id == location_id,
            Item.is_deleted.is_(False),
        )
    )
    return Decimal(total or 0)


def _the_register_agrees(
    db_session: Session,
    org_id: UUID,
    template_id: UUID,
    locations: list[UUID],
) -> None:
    """One statement, every location the door touched: records == movements."""
    db_session.expire_all()
    for location_id in locations:
        records = _record_quantity(db_session, org_id, template_id, location_id)
        moved = _moved_quantity(db_session, org_id, template_id, location_id)
        assert records == moved, (
            f'the records at {location_id} read {records} where the ledger '
            f'nets to {moved}'
        )


def _run_correction(
    client: TestClient,
    headers: dict[str, str],
    *,
    original: Document,
    quantity_delta: int,
) -> tuple[int, str, str]:
    resp = client.post(
        '/api/v1/warehouse/corrections',
        headers=headers,
        json={
            'corrects_document_id': str(original.id),
            'reason_code': 'DATA_ENTRY_ERROR',
            'lines': [{'original_line_number': 1, 'quantity_delta': quantity_delta}],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    assert confirm.status_code == status.HTTP_200_OK, confirm.text
    complete = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    return complete.status_code, doc_id, complete.text


def _door_moves(db_session: Session, org_id: UUID, doc_id: str) -> list[StockMove]:
    """The movements the door itself wrote — not the ledger's whole history."""
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(StockMove).where(
                StockMove.organization_id == org_id,
                StockMove.reference_type == 'document',
                StockMove.reference_id == UUID(doc_id),
            )
        )
    )


@pytest.mark.integration
class TestTheCorrectionLandsWhereTheOriginalLanded:
    """The correction rewrites the delivery where the delivery happened."""

    def test_a_cardless_record_corrected_up_lands_on_its_own_shelf(
        self,
        client: TestClient,
        landing_headers: dict[str, str],
        home_shelf: StorageLocation,
        asked_shelf: StorageLocation,
        db_session: Session,
        landing_org: Organization,
        landing_user: User,
    ) -> None:
        record = _cardless_record(
            db_session,
            landing_org.id,
            name='Landing Probe',
            location_id=home_shelf.id,
            quantity=Decimal('10'),
        )
        db_session.commit()
        delivery = _seed_the_delivery(
            db_session,
            landing_org.id,
            landing_user.id,
            item=record,
            asked_location_id=asked_shelf.id,
            landed_location_id=home_shelf.id,
            quantity=Decimal('10'),
        )
        db_session.commit()

        complete_status, doc_id, body = _run_correction(
            client, landing_headers, original=delivery, quantity_delta=2
        )
        assert complete_status == status.HTTP_200_OK, body

        db_session.expire_all()
        db_session.refresh(record)
        template_id = record.template_id
        assert template_id is not None, 'the correction adopted the record a card'

        # The report's pair, on the record's shelf and on the shelf the
        # document asked for: the correction moved nothing to the second one.
        _the_register_agrees(
            db_session, landing_org.id, template_id, [home_shelf.id, asked_shelf.id]
        )
        assert _record_quantity(
            db_session, landing_org.id, template_id, home_shelf.id
        ) == Decimal('12')

        moves = _door_moves(db_session, landing_org.id, doc_id)
        assert len(moves) == 1
        assert moves[0].to_location_id == home_shelf.id, (
            'the correction landed where the delivery happened'
        )
        assert moves[0].from_location_id is None

        report = client.get('/api/v1/stats/reconciliation', headers=landing_headers)
        assert report.status_code == status.HTTP_200_OK, report.text
        figures = report.json()
        assert figures['quant_move_drift_count'] == 0, figures
        assert Decimal(str(figures['quant_move_drift_total'])) == 0, figures

    def test_a_carded_twin_leaves_the_same_trace(
        self,
        client: TestClient,
        landing_headers: dict[str, str],
        home_shelf: StorageLocation,
        asked_shelf: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        landing_org: Organization,
        landing_user: User,
    ) -> None:
        """The same pair of lines, differing in nothing but the card."""
        record = _carded_record(
            db_session,
            async_engine_fixture,
            landing_org.id,
            name='Landing Twin',
            location_id=home_shelf.id,
            quantity=Decimal('10'),
        )
        db_session.commit()
        delivery = _seed_the_delivery(
            db_session,
            landing_org.id,
            landing_user.id,
            item=record,
            asked_location_id=asked_shelf.id,
            landed_location_id=home_shelf.id,
            quantity=Decimal('10'),
        )
        db_session.commit()

        complete_status, doc_id, body = _run_correction(
            client, landing_headers, original=delivery, quantity_delta=2
        )
        assert complete_status == status.HTTP_200_OK, body

        db_session.expire_all()
        assert record.template_id is not None
        _the_register_agrees(
            db_session,
            landing_org.id,
            record.template_id,
            [home_shelf.id, asked_shelf.id],
        )
        assert _record_quantity(
            db_session, landing_org.id, record.template_id, home_shelf.id
        ) == Decimal('12')

        moves = _door_moves(db_session, landing_org.id, doc_id)
        assert len(moves) == 1
        assert moves[0].to_location_id == home_shelf.id

        report = client.get('/api/v1/stats/reconciliation', headers=landing_headers)
        figures = report.json()
        assert figures['quant_move_drift_count'] == 0, figures
        assert Decimal(str(figures['quant_move_drift_total'])) == 0, figures

    def test_a_correction_taking_stock_back_finds_it_where_it_landed(
        self,
        client: TestClient,
        landing_headers: dict[str, str],
        home_shelf: StorageLocation,
        asked_shelf: StorageLocation,
        db_session: Session,
        landing_org: Organization,
        landing_user: User,
    ) -> None:
        """The other direction: the stock being taken back sits on the record's shelf."""
        record = _cardless_record(
            db_session,
            landing_org.id,
            name='Landing Takeback',
            location_id=home_shelf.id,
            quantity=Decimal('10'),
        )
        db_session.commit()
        delivery = _seed_the_delivery(
            db_session,
            landing_org.id,
            landing_user.id,
            item=record,
            asked_location_id=asked_shelf.id,
            landed_location_id=home_shelf.id,
            quantity=Decimal('10'),
        )
        db_session.commit()

        complete_status, doc_id, body = _run_correction(
            client, landing_headers, original=delivery, quantity_delta=-2
        )
        assert complete_status == status.HTTP_200_OK, body

        db_session.expire_all()
        db_session.refresh(record)
        assert record.template_id is not None
        _the_register_agrees(
            db_session,
            landing_org.id,
            record.template_id,
            [home_shelf.id, asked_shelf.id],
        )
        assert _record_quantity(
            db_session, landing_org.id, record.template_id, home_shelf.id
        ) == Decimal('8')

        moves = _door_moves(db_session, landing_org.id, doc_id)
        assert len(moves) == 1
        assert moves[0].from_location_id == home_shelf.id

        report = client.get('/api/v1/stats/reconciliation', headers=landing_headers)
        figures = report.json()
        assert figures['quant_move_drift_count'] == 0, figures
        assert Decimal(str(figures['quant_move_drift_total'])) == 0, figures
