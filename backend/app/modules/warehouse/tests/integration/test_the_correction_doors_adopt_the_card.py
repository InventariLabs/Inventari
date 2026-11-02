"""The correction doors adopt a cardless record the way every other door does.

Two doors were still gating their ledger writes on ``stock_template_id`` —
the one id a record that predates its card does not have: ``execute_adjustment``
and ``execute_correction`` moved the count off the record while the register
read empty, and the location card said ``Nothing has moved through here``
underneath the quantity it was showing. The class was named and closed for
the receipt first, then for the outbound doors, which also settle what adoption
means: the record joins the ledger with an opening balance, not with a hole.

These tests hold both doors to the same relation the other doors are held to:
for every (card, location) the records and the movement ledger net to the same
number, the door writes its own movement, and two lines that differ in nothing but the
presence of a card leave the same trace behind them.
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
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.models.document import Document, DocumentLine
from app.modules.warehouse.tests.integration._records import (
    sow as _sow,
)


@pytest.fixture
def ledger_org(h: ModuleTestHelper) -> Organization:
    org = h.create_org(
        'Cardless Correction Org',
        ['core', 'items', 'locations', 'categories', 'warehouse', 'approvals', 'stats'],
    )
    h.set_module_settings(org, 'approvals', {'allow_admin_self_approve': True})
    return org


@pytest.fixture
def ledger_user(h: ModuleTestHelper, ledger_org: Organization) -> User:
    return h.create_user(ledger_org, email='cardless-correction@example.com')


@pytest.fixture
def ledger_headers(h: ModuleTestHelper, ledger_user: User) -> dict[str, str]:
    return h.get_auth_headers(ledger_user)


@pytest.fixture
def ledger_shelf(
    h: ModuleTestHelper, ledger_org: Organization, ledger_user: User
) -> StorageLocation:
    storage_type = h.create_storage_type(
        'Correction Warehouse', 'CORRECTION_WAREHOUSE', organization_id=ledger_org.id
    )
    return h.create_storage_location(
        ledger_org, storage_type, ledger_user, name='Correction Shelf'
    )


def _cardless_record(
    db_session: Session,
    org_id: UUID,
    *,
    name: str,
    location_id: UUID,
    quantity: Decimal,
) -> Item:
    """The shape of anything stocked before the catalogue existed."""
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
    """The same stock, born after the catalogue: a card, a shelf, a record."""
    template = ProductTemplate(
        name=name,
        organization_id=org_id,
    )
    db_session.add(template)
    db_session.flush()
    return _sow(db_session, engine, org_id, template, location_id, quantity)


def _seed_completed_in(
    db_session: Session,
    org_id: UUID,
    user_id: UUID,
    *,
    item: Item,
    target_location_id: UUID,
    quantity: Decimal,
) -> Document:
    """An original receipt for a correction to lean on.

    The receipt this document stands for was completed in a world whose
    receipt door wrote nothing for a record without a card, so seeding it
    directly is what keeps the record cardless on the way to the correction —
    the door under test is the one that must adopt it.
    """
    doc = Document(
        organization_id=org_id,
        type='IN',
        number=f'IN/SEED/{uuid4().hex[:8]}',
        status='COMPLETED',
        target_location_id=target_location_id,
        created_by=user_id,
    )
    db_session.add(doc)
    db_session.flush()
    db_session.add(
        DocumentLine(
            document_id=doc.id,
            item_id=item.id,
            quantity=quantity,
            expected_quantity=quantity,
            done_quantity=quantity,
            line_number=1,
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


def _layer_quantity(db_session: Session, org_id: UUID, template_id: UUID) -> Decimal:
    total = db_session.scalar(
        select(func.sum(StockValuationLayer.remaining_qty)).where(
            StockValuationLayer.organization_id == org_id,
            StockValuationLayer.product_template_id == template_id,
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


def _run_doc(
    client: TestClient,
    headers: dict[str, str],
    payload: dict[str, object],
) -> tuple[int, str, str]:
    resp = client.post('/api/v1/warehouse/documents', headers=headers, json=payload)
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
class TestTheCorrectionDoorsAdoptTheCard:
    """Both signed-delta doors leave the same relation the other doors do."""

    def test_an_adjustment_leaves_the_records_and_the_shelf_agreeing(
        self,
        client: TestClient,
        ledger_headers: dict[str, str],
        ledger_shelf: StorageLocation,
        db_session: Session,
        ledger_org: Organization,
    ) -> None:
        record = _cardless_record(
            db_session,
            ledger_org.id,
            name=f'Cardless Adjust {uuid4().hex[:6]}',
            location_id=ledger_shelf.id,
            quantity=Decimal('10'),
        )
        db_session.commit()

        complete_status, doc_id, body = _run_doc(
            client,
            ledger_headers,
            {
                'type': 'ADJUSTMENT',
                'target_location_id': str(ledger_shelf.id),
                'lines': [{'item_id': str(record.id), 'expected_quantity': 3}],
            },
        )
        assert complete_status == status.HTTP_200_OK, body

        db_session.expire_all()
        adjusted = db_session.get(Item, record.id)
        assert adjusted is not None and adjusted.template_id is not None, (
            'the adjustment bound the record to a card'
        )
        assert adjusted.quantity == Decimal('13'), 'the record took the count'

        _the_register_agrees(
            db_session, ledger_org.id, adjusted.template_id, [ledger_shelf.id]
        )
        moves = _door_moves(db_session, ledger_org.id, doc_id)
        assert len(moves) == 1, 'the door wrote its own movement'
        assert moves[0].to_location_id == ledger_shelf.id
        assert moves[0].quantity == Decimal('3')
        assert _layer_quantity(db_session, ledger_org.id, adjusted.template_id) == (
            Decimal('13')
        ), 'the cost history covers what the shelf holds'

    def test_a_second_adjustment_runs_like_the_first(
        self,
        client: TestClient,
        ledger_headers: dict[str, str],
        ledger_shelf: StorageLocation,
        db_session: Session,
        ledger_org: Organization,
    ) -> None:
        record = _cardless_record(
            db_session,
            ledger_org.id,
            name=f'Cardless Readjust {uuid4().hex[:6]}',
            location_id=ledger_shelf.id,
            quantity=Decimal('10'),
        )
        db_session.commit()

        first_status, _, first_body = _run_doc(
            client,
            ledger_headers,
            {
                'type': 'ADJUSTMENT',
                'target_location_id': str(ledger_shelf.id),
                'lines': [{'item_id': str(record.id), 'expected_quantity': 3}],
            },
        )
        assert first_status == status.HTTP_200_OK, first_body
        second_status, _, second_body = _run_doc(
            client,
            ledger_headers,
            {
                'type': 'ADJUSTMENT',
                'target_location_id': str(ledger_shelf.id),
                'lines': [{'item_id': str(record.id), 'expected_quantity': 2}],
            },
        )
        assert second_status == status.HTTP_200_OK, second_body

        db_session.expire_all()
        adjusted = db_session.get(Item, record.id)
        assert adjusted is not None and adjusted.template_id is not None
        assert adjusted.quantity == Decimal('15'), 'the record took both counts'
        _the_register_agrees(
            db_session, ledger_org.id, adjusted.template_id, [ledger_shelf.id]
        )

    def test_a_correction_taking_back_leaves_the_register_agreeing(
        self,
        client: TestClient,
        ledger_headers: dict[str, str],
        ledger_shelf: StorageLocation,
        db_session: Session,
        ledger_org: Organization,
        ledger_user: User,
    ) -> None:
        record = _cardless_record(
            db_session,
            ledger_org.id,
            name=f'Cardless Correct {uuid4().hex[:6]}',
            location_id=ledger_shelf.id,
            quantity=Decimal('10'),
        )
        original = _seed_completed_in(
            db_session,
            ledger_org.id,
            ledger_user.id,
            item=record,
            target_location_id=ledger_shelf.id,
            quantity=Decimal('10'),
        )
        db_session.commit()

        complete_status, doc_id, body = _run_correction(
            client, ledger_headers, original=original, quantity_delta=-2
        )
        assert complete_status == status.HTTP_200_OK, body

        db_session.expire_all()
        corrected = db_session.get(Item, record.id)
        assert corrected is not None and corrected.template_id is not None, (
            'the correction bound the record to a card'
        )
        assert corrected.quantity == Decimal('8'), 'the record gave the surplus back'

        _the_register_agrees(
            db_session, ledger_org.id, corrected.template_id, [ledger_shelf.id]
        )
        moves = _door_moves(db_session, ledger_org.id, doc_id)
        assert len(moves) == 1, 'the door wrote its own movement'
        assert moves[0].from_location_id == ledger_shelf.id
        assert moves[0].quantity == Decimal('2')
        assert _layer_quantity(db_session, ledger_org.id, corrected.template_id) == (
            Decimal('8')
        ), 'the cost history covers what the shelf holds'

    def test_two_lines_differing_only_in_the_card_leave_the_same_trace(
        self,
        client: TestClient,
        ledger_headers: dict[str, str],
        ledger_shelf: StorageLocation,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        ledger_org: Organization,
        ledger_user: User,
    ) -> None:
        cardless = _cardless_record(
            db_session,
            ledger_org.id,
            name=f'Twin Without Card {uuid4().hex[:6]}',
            location_id=ledger_shelf.id,
            quantity=Decimal('10'),
        )
        carded = _carded_record(
            db_session,
            async_engine_fixture,
            ledger_org.id,
            name=f'Twin With Card {uuid4().hex[:6]}',
            location_id=ledger_shelf.id,
            quantity=Decimal('10'),
        )
        cardless_original = _seed_completed_in(
            db_session,
            ledger_org.id,
            ledger_user.id,
            item=cardless,
            target_location_id=ledger_shelf.id,
            quantity=Decimal('10'),
        )
        carded_original = _seed_completed_in(
            db_session,
            ledger_org.id,
            ledger_user.id,
            item=carded,
            target_location_id=ledger_shelf.id,
            quantity=Decimal('10'),
        )
        db_session.commit()

        cardless_status, cardless_doc, cardless_body = _run_correction(
            client, ledger_headers, original=cardless_original, quantity_delta=-2
        )
        assert cardless_status == status.HTTP_200_OK, cardless_body
        carded_status, carded_doc, carded_body = _run_correction(
            client, ledger_headers, original=carded_original, quantity_delta=-2
        )
        assert carded_status == status.HTTP_200_OK, carded_body

        db_session.expire_all()
        corrected_cardless = db_session.get(Item, cardless.id)
        corrected_carded = db_session.get(Item, carded.id)
        assert corrected_cardless is not None and corrected_carded is not None
        assert corrected_cardless.quantity == Decimal('8')
        assert corrected_carded.quantity == Decimal('8')

        # The one difference card presence may make: none. Both lines leave
        # the door's own movement behind, and both pairs (card, location)
        # say one number.
        assert len(_door_moves(db_session, ledger_org.id, cardless_doc)) == 1
        assert len(_door_moves(db_session, ledger_org.id, carded_doc)) == 1
        assert corrected_cardless.template_id is not None
        assert corrected_carded.template_id is not None
        _the_register_agrees(
            db_session,
            ledger_org.id,
            corrected_cardless.template_id,
            [ledger_shelf.id],
        )
        _the_register_agrees(
            db_session,
            ledger_org.id,
            corrected_carded.template_id,
            [ledger_shelf.id],
        )
