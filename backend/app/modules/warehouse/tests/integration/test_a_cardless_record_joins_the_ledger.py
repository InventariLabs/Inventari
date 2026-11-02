"""A record that predates its card joins the register when a door adopts it.

Three doors — dispatch, scrap and transfer — adopt a card for a record whose
``template_id`` is still NULL, the same resolve-or-mint the receipt runs.
Adoption used to be where the ledger stopped: the goods left the record and
the movement was written, but nothing ever said the record had held stock
before. From that moment the pair *(card, location)* read two different
numbers for the same shelf — the record refused a second dispatch off a shelf
its own card said was full, and the reconciliation report named a drift
nobody had caused.

These tests hold every adopting door to one relation: for every (card,
location) the records and the movement ledger net to the same number, and the
report has nothing to report. The stock the record held is posted as an
opening balance, the way a quantity raised by hand is
(``record_unpriced_receipt_async``), so the cost history opens with the stock
rather than staying a hole in the third pair.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.stock_move import StockMove
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.models.document import Document, DocumentLine


@pytest.fixture
def ledger_org(h: ModuleTestHelper) -> Organization:
    """The documents organization, plus the module the report lives in."""
    org = h.create_org(
        'Cardless Ledger Org',
        ['core', 'items', 'locations', 'categories', 'warehouse', 'approvals', 'stats'],
    )
    h.set_module_settings(org, 'approvals', {'allow_admin_self_approve': True})
    return org


@pytest.fixture
def ledger_user(h: ModuleTestHelper, ledger_org: Organization) -> User:
    return h.create_user(ledger_org, email='cardless-ledger@example.com')


@pytest.fixture
def ledger_headers(h: ModuleTestHelper, ledger_user: User) -> dict[str, str]:
    return h.get_auth_headers(ledger_user)


@pytest.fixture
def ledger_from(
    h: ModuleTestHelper, ledger_org: Organization, ledger_user: User
) -> StorageLocation:
    storage_type = h.create_storage_type(
        'Ledger Warehouse', 'LEDGER_WAREHOUSE', organization_id=ledger_org.id
    )
    return h.create_storage_location(
        ledger_org, storage_type, ledger_user, name='Source Warehouse'
    )


@pytest.fixture
def ledger_to(
    h: ModuleTestHelper, ledger_org: Organization, ledger_user: User
) -> StorageLocation:
    storage_type = h.create_storage_type(
        'Ledger Warehouse', 'LEDGER_WAREHOUSE', organization_id=ledger_org.id
    )
    return h.create_storage_location(
        ledger_org, storage_type, ledger_user, name='Target Warehouse'
    )


@pytest.fixture
def ledger_elsewhere(
    h: ModuleTestHelper, ledger_org: Organization, ledger_user: User
) -> StorageLocation:
    storage_type = h.create_storage_type(
        'Another Ledger Warehouse', 'LEDGER_WAREHOUSE_2', organization_id=ledger_org.id
    )
    return h.create_storage_location(
        ledger_org, storage_type, ledger_user, name='Another Warehouse'
    )


@pytest.fixture
def ledger_partner(
    h: ModuleTestHelper, ledger_org: Organization, ledger_user: User
) -> Partner:
    return h.create_partner(ledger_org, ledger_user, name='Ledger Supplies')


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


def _seed_the_delivery(
    db_session: Session,
    org_id: UUID,
    user_id: UUID,
    *,
    item: Item,
    location_id: UUID,
    quantity: Decimal,
) -> Document:
    """The delivery a correction leans on, seeded as its door left it.

    Seeded and not run, for the same reason the door tests seed it: the receipt
    would hand the record its card before the correction could, and the door
    under this guard is the one that must adopt a record the catalogue does not
    know yet. The line carries the place the goods went, which is where the
    correction lands.
    """
    doc = Document(
        organization_id=org_id,
        type='IN',
        number=f'IN/LEDGER/{uuid4().hex[:8]}',
        status='COMPLETED',
        target_location_id=location_id,
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
            executed_location_id=location_id,
        )
    )
    db_session.flush()
    return doc


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


def _run_every_adopting_door(
    client: TestClient,
    headers: dict[str, str],
    *,
    dispatched: Item,
    scrapped: Item,
    sharing: Item,
    moved: Item,
    adjusted: Item,
    delivery: Document,
    ledger_from: StorageLocation,
    ledger_to: StorageLocation,
    partner: Partner,
) -> None:
    """All five adopting doors, one cardless record each: each answers 200.

    A door that keeps its ledger writes behind the card the record does not
    have stops here first — without the opening balance the shelf it works off
    reads empty, so it refuses its own document ("There is no <record> at
    <shelf>") instead of moving stock the register cannot see.
    """
    out_status, _, out_body = _run_doc(
        client,
        headers,
        {
            'type': 'OUT',
            'partner_id': str(partner.id),
            'source_location_id': str(ledger_from.id),
            'target_location_id': str(ledger_to.id),
            'lines': [{'item_id': str(dispatched.id), 'expected_quantity': 3}],
        },
    )
    assert out_status == status.HTTP_200_OK, out_body
    scrap_status, _, scrap_body = _run_doc(
        client,
        headers,
        {
            'type': 'SCRAP',
            'reason_code': 'DAMAGED',
            'source_location_id': str(ledger_from.id),
            'lines': [{'item_id': str(scrapped.id), 'expected_quantity': 3}],
        },
    )
    assert scrap_status == status.HTTP_200_OK, scrap_body
    share_status, _, share_body = _run_doc(
        client,
        headers,
        {
            'type': 'OUT',
            'partner_id': str(partner.id),
            'source_location_id': str(ledger_from.id),
            'target_location_id': str(ledger_to.id),
            'lines': [{'item_id': str(sharing.id), 'expected_quantity': 4}],
        },
    )
    assert share_status == status.HTTP_200_OK, share_body
    int_status, _, int_body = _run_doc(
        client,
        headers,
        {
            'type': 'INT',
            'source_location_id': str(ledger_from.id),
            'target_location_id': str(ledger_to.id),
            'lines': [{'item_id': str(moved.id), 'expected_quantity': 5}],
        },
    )
    assert int_status == status.HTTP_200_OK, int_body
    adjust_status, _, adjust_body = _run_doc(
        client,
        headers,
        {
            'type': 'ADJUSTMENT',
            'target_location_id': str(ledger_from.id),
            'lines': [{'item_id': str(adjusted.id), 'expected_quantity': 2}],
        },
    )
    assert adjust_status == status.HTTP_200_OK, adjust_body
    correction_status, _, correction_body = _run_correction(
        client, headers, original=delivery, quantity_delta=2
    )
    assert correction_status == status.HTTP_200_OK, correction_body


def _the_register_agrees(
    db_session: Session,
    org_id: UUID,
    template_id: UUID,
    locations: list[UUID],
) -> None:
    """One statement, every location the door touched: records == movements.

    The ledger pair the reconciliation report compares, asserted the way the
    report compares it — per (card, location), summed over the records
    standing there, because one shelf legitimately holds several of them.
    """
    db_session.expire_all()
    for location_id in locations:
        records = _record_quantity(db_session, org_id, template_id, location_id)
        moved = _moved_quantity(db_session, org_id, template_id, location_id)
        assert records == moved, (
            f'the records at {location_id} read {records} where the ledger '
            f'nets to {moved}'
        )


@pytest.mark.integration
class TestACardlessRecordJoinsTheLedger:
    """Every door that adopts a card leaves the same relation behind it."""

    def test_a_dispatch_leaves_the_records_and_the_shelf_agreeing(
        self,
        client: TestClient,
        ledger_headers: dict[str, str],
        ledger_from: StorageLocation,
        ledger_to: StorageLocation,
        ledger_partner: Partner,
        db_session: Session,
        ledger_org: Organization,
    ) -> None:
        record = _cardless_record(
            db_session,
            ledger_org.id,
            name=f'Cardless Out {uuid4().hex[:6]}',
            location_id=ledger_from.id,
            quantity=Decimal('5'),
        )
        db_session.commit()

        complete_status, doc_id, body = _run_doc(
            client,
            ledger_headers,
            {
                'type': 'OUT',
                'partner_id': str(ledger_partner.id),
                'source_location_id': str(ledger_from.id),
                'target_location_id': str(ledger_to.id),
                'lines': [{'item_id': str(record.id), 'expected_quantity': 2}],
            },
        )
        assert complete_status == status.HTTP_200_OK, body

        db_session.expire_all()
        moved = db_session.get(Item, record.id)
        assert moved is not None and moved.template_id is not None, (
            'the dispatch bound the record to a card'
        )
        assert moved.quantity == Decimal('3'), 'the record lost what left it'

        _the_register_agrees(
            db_session, ledger_org.id, moved.template_id, [ledger_from.id, ledger_to.id]
        )
        assert _layer_quantity(db_session, ledger_org.id, moved.template_id) == (
            Decimal('3')
        ), 'the cost history covers what the shelf holds'

    def test_a_scrap_leaves_the_records_and_the_shelf_agreeing(
        self,
        client: TestClient,
        ledger_headers: dict[str, str],
        ledger_from: StorageLocation,
        db_session: Session,
        ledger_org: Organization,
    ) -> None:
        record = _cardless_record(
            db_session,
            ledger_org.id,
            name=f'Cardless Scrap {uuid4().hex[:6]}',
            location_id=ledger_from.id,
            quantity=Decimal('5'),
        )
        db_session.commit()

        complete_status, doc_id, body = _run_doc(
            client,
            ledger_headers,
            {
                'type': 'SCRAP',
                'reason_code': 'DAMAGED',
                'source_location_id': str(ledger_from.id),
                'lines': [{'item_id': str(record.id), 'expected_quantity': 2}],
            },
        )
        assert complete_status == status.HTTP_200_OK, body

        db_session.expire_all()
        scrapped = db_session.get(Item, record.id)
        assert scrapped is not None and scrapped.template_id is not None, (
            'the scrap bound the record to a card'
        )
        assert scrapped.quantity == Decimal('3'), 'the record lost what left it'

        _the_register_agrees(
            db_session, ledger_org.id, scrapped.template_id, [ledger_from.id]
        )
        assert _layer_quantity(db_session, ledger_org.id, scrapped.template_id) == (
            Decimal('3')
        ), 'the cost history covers what the shelf holds'

    def test_a_transfer_carries_what_the_register_knows(
        self,
        client: TestClient,
        ledger_headers: dict[str, str],
        ledger_from: StorageLocation,
        ledger_to: StorageLocation,
        db_session: Session,
        ledger_org: Organization,
    ) -> None:
        record = _cardless_record(
            db_session,
            ledger_org.id,
            name=f'Cardless Int {uuid4().hex[:6]}',
            location_id=ledger_from.id,
            quantity=Decimal('5'),
        )
        db_session.commit()

        complete_status, doc_id, body = _run_doc(
            client,
            ledger_headers,
            {
                'type': 'INT',
                'source_location_id': str(ledger_from.id),
                'target_location_id': str(ledger_to.id),
                'lines': [{'item_id': str(record.id), 'expected_quantity': 5}],
            },
        )
        assert complete_status == status.HTTP_200_OK, body

        db_session.expire_all()
        moved = db_session.get(Item, record.id)
        assert moved is not None and moved.template_id is not None, (
            'the transfer bound the record to a card'
        )
        assert moved.storage_location_id == ledger_to.id

        _the_register_agrees(
            db_session, ledger_org.id, moved.template_id, [ledger_from.id, ledger_to.id]
        )
        assert _layer_quantity(db_session, ledger_org.id, moved.template_id) == (
            Decimal('5')
        ), 'a move does not eat the cost history'


@pytest.mark.integration
class TestAnAdoptedRecordKeepsWorking:
    """Once adopted, the record behaves like any other the ledger knows."""

    def test_a_second_dispatch_ends_like_the_first(
        self,
        client: TestClient,
        ledger_headers: dict[str, str],
        ledger_from: StorageLocation,
        ledger_to: StorageLocation,
        ledger_partner: Partner,
        db_session: Session,
        ledger_org: Organization,
    ) -> None:
        """The shelf its own card names is not read as empty one line later.

        Measured before the opening balance: the first dispatch of the
        adopted record answered 200 and took two off the record, and the
        same document a second time answered 400 naming a shelf whose card
        was, at that moment, showing the remaining three.
        """
        record = _cardless_record(
            db_session,
            ledger_org.id,
            name=f'Twice Out {uuid4().hex[:6]}',
            location_id=ledger_from.id,
            quantity=Decimal('5'),
        )
        db_session.commit()

        payload: dict[str, object] = {
            'type': 'OUT',
            'partner_id': str(ledger_partner.id),
            'source_location_id': str(ledger_from.id),
            'target_location_id': str(ledger_to.id),
            'lines': [{'item_id': str(record.id), 'expected_quantity': 2}],
        }
        first_status, _, first_body = _run_doc(client, ledger_headers, payload)
        assert first_status == status.HTTP_200_OK, first_body
        second_status, _, second_body = _run_doc(client, ledger_headers, payload)
        assert second_status == status.HTTP_200_OK, second_body

        db_session.expire_all()
        after = db_session.get(Item, record.id)
        assert after is not None and after.template_id is not None
        assert after.quantity == Decimal('1'), 'two dispatches of two off five'

        _the_register_agrees(
            db_session, ledger_org.id, after.template_id, [ledger_from.id, ledger_to.id]
        )

        # The third one asks for more than the shelf holds: the refusal and
        # the register agree about the one piece that is there. The adopted
        # record carries its card, so the hold sees the shortfall already at
        # confirmation instead of letting completion find it.
        third = client.post(
            '/api/v1/warehouse/documents', headers=ledger_headers, json=payload
        )
        assert third.status_code == status.HTTP_201_CREATED, third.text
        refused = client.patch(
            f'/api/v1/warehouse/documents/{third.json()["id"]}/confirm',
            headers=ledger_headers,
        )
        assert refused.status_code == status.HTTP_400_BAD_REQUEST, refused.text
        db_session.expire_all()
        still = db_session.get(Item, record.id)
        assert still is not None and still.quantity == Decimal('1'), (
            'a refused dispatch moves nothing'
        )
        _the_register_agrees(
            db_session, ledger_org.id, after.template_id, [ledger_from.id, ledger_to.id]
        )

    def test_the_report_stays_silent_after_the_cardless_doors(
        self,
        client: TestClient,
        ledger_headers: dict[str, str],
        ledger_from: StorageLocation,
        ledger_to: StorageLocation,
        ledger_elsewhere: StorageLocation,
        ledger_partner: Partner,
        ledger_user: User,
        db_session: Session,
        ledger_org: Organization,
    ) -> None:
        """Every adopting door leaves the report with nothing to report.

        The shape the drift was first seen in: a record dispatched whole and
        a record scrapped whole, both of them cardless beforehand, plus a
        cardless record whose name matches a card that already holds stock
        on another shelf — the case where adoption binds to an existing card
        instead of minting one. The three later doors join them here — a
        transfer, an adjustment and a correction, one cardless record each —
        because the silence of the report is the very property they were
        given an opening balance for, and it is the first thing a door's
        ledger writes take away again when they are touched.
        """
        dispatched = _cardless_record(
            db_session,
            ledger_org.id,
            name=f'Report Out {uuid4().hex[:6]}',
            location_id=ledger_from.id,
            quantity=Decimal('3'),
        )
        scrapped = _cardless_record(
            db_session,
            ledger_org.id,
            name=f'Report Scrap {uuid4().hex[:6]}',
            location_id=ledger_from.id,
            quantity=Decimal('3'),
        )
        h = ModuleTestHelper(db_session)
        shared_card = h.create_template(ledger_org, name='Bearing Assembly')
        db_session.commit()
        # The card the sharing record will join, holding stock somebody
        # received: a priced receipt opens the record, the movement and the
        # cost layer together, so the control is a shelf the register really
        # knows.
        receipt_status, _, receipt_body = _run_doc(
            client,
            ledger_headers,
            {
                'type': 'IN',
                'partner_id': str(ledger_partner.id),
                'target_location_id': str(ledger_elsewhere.id),
                'lines': [
                    {
                        'product_template_id': str(shared_card.id),
                        'expected_quantity': '28',
                        'unit_price': '4.50',
                    }
                ],
            },
        )
        assert receipt_status == status.HTTP_200_OK, receipt_body
        sharing = _cardless_record(
            db_session,
            ledger_org.id,
            name='Bearing Assembly',
            location_id=ledger_from.id,
            quantity=Decimal('6'),
        )
        moved = _cardless_record(
            db_session,
            ledger_org.id,
            name=f'Report Int {uuid4().hex[:6]}',
            location_id=ledger_from.id,
            quantity=Decimal('5'),
        )
        adjusted = _cardless_record(
            db_session,
            ledger_org.id,
            name=f'Report Adjust {uuid4().hex[:6]}',
            location_id=ledger_from.id,
            quantity=Decimal('4'),
        )
        corrected = _cardless_record(
            db_session,
            ledger_org.id,
            name=f'Report Correct {uuid4().hex[:6]}',
            location_id=ledger_from.id,
            quantity=Decimal('6'),
        )
        db_session.commit()
        delivery = _seed_the_delivery(
            db_session,
            ledger_org.id,
            ledger_user.id,
            item=corrected,
            location_id=ledger_from.id,
            quantity=Decimal('6'),
        )
        db_session.commit()

        before = client.get('/api/v1/stats/reconciliation', headers=ledger_headers)
        assert before.status_code == status.HTTP_200_OK, before.text
        assert before.json()['quant_move_drift_count'] == 0, (
            'a cardless record is invisible to both sides of the pair'
        )

        _run_every_adopting_door(
            client,
            ledger_headers,
            dispatched=dispatched,
            scrapped=scrapped,
            sharing=sharing,
            moved=moved,
            adjusted=adjusted,
            delivery=delivery,
            ledger_from=ledger_from,
            ledger_to=ledger_to,
            partner=ledger_partner,
        )

        db_session.expire_all()
        bound = db_session.get(Item, sharing.id)
        assert bound is not None
        assert bound.template_id == shared_card.id, (
            'a record whose name matches an existing card joins that card'
        )
        _the_register_agrees(
            db_session,
            ledger_org.id,
            shared_card.id,
            [ledger_from.id, ledger_elsewhere.id],
        )
        travelled = db_session.get(Item, moved.id)
        assert travelled is not None and travelled.template_id is not None, (
            'the transfer bound the record to a card'
        )
        assert travelled.storage_location_id == ledger_to.id
        _the_register_agrees(
            db_session,
            ledger_org.id,
            travelled.template_id,
            [ledger_from.id, ledger_to.id],
        )
        counted = db_session.get(Item, adjusted.id)
        assert counted is not None and counted.template_id is not None, (
            'the adjustment bound the record to a card'
        )
        _the_register_agrees(
            db_session, ledger_org.id, counted.template_id, [ledger_from.id]
        )
        restated = db_session.get(Item, corrected.id)
        assert restated is not None and restated.template_id is not None, (
            'the correction bound the record to a card'
        )
        _the_register_agrees(
            db_session, ledger_org.id, restated.template_id, [ledger_from.id]
        )

        after = client.get('/api/v1/stats/reconciliation', headers=ledger_headers)
        assert after.status_code == status.HTTP_200_OK, after.text
        assert after.json()['layer_quant_drift_count'] == 0, after.json()
        assert Decimal(str(after.json()['layer_quant_drift_total'])) == Decimal('0')
        # And the ledger pair: every stock an opening put on a shelf has the
        # movement that says where it came from, so the ledger nets to the
        # shelf instead of to the shelf less everything the doors opened.
        assert after.json()['quant_move_drift_count'] == 0, after.json()
        assert Decimal(str(after.json()['quant_move_drift_total'])) == Decimal('0')
