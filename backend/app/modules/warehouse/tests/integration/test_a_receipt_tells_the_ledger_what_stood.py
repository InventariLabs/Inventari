"""A receipt that adopts a card tells the ledger what stood before it.

The receipt door adopted the card a record that predates one never had —
and then raised the quant by the delivered quantity alone. Whatever the
record already held stayed outside the register, while the freshly bound
card made the record visible to the reconciliation report from that
moment: the pair *(card, location)* read the delivery where the record
read delivery plus everything that stood on the shelf before it.

These tests hold the receipt to the relation the other adopting doors
leave behind: the records and the movement ledger net to the same number for
every (card, location) the door touched, and the report has nothing to
report.
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


@pytest.fixture
def joining_org(h: ModuleTestHelper) -> Organization:
    """The documents organization, plus the module the report lives in."""
    org = h.create_org(
        'Receipt Ledger Org',
        ['core', 'items', 'locations', 'categories', 'warehouse', 'approvals', 'stats'],
    )
    h.set_module_settings(org, 'approvals', {'allow_admin_self_approve': True})
    return org


@pytest.fixture
def joining_user(h: ModuleTestHelper, joining_org: Organization) -> User:
    return h.create_user(joining_org, email='receipt-ledger@example.com')


@pytest.fixture
def joining_headers(h: ModuleTestHelper, joining_user: User) -> dict[str, str]:
    return h.get_auth_headers(joining_user)


@pytest.fixture
def joining_shelf(
    h: ModuleTestHelper, joining_org: Organization, joining_user: User
) -> StorageLocation:
    storage_type = h.create_storage_type(
        'Receipt Warehouse', 'RECEIPT_WAREHOUSE', organization_id=joining_org.id
    )
    return h.create_storage_location(
        joining_org, storage_type, joining_user, name='Receiving Shelf'
    )


@pytest.fixture
def joining_partner(
    h: ModuleTestHelper, joining_org: Organization, joining_user: User
) -> Partner:
    return h.create_partner(joining_org, joining_user, name='Ledger Goods')


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


@pytest.mark.integration
class TestAReceiptTellsTheLedgerWhatStood:
    def test_a_receipt_leaves_the_records_and_the_shelf_agreeing(
        self,
        client: TestClient,
        joining_headers: dict[str, str],
        joining_shelf: StorageLocation,
        joining_partner: Partner,
        db_session: Session,
        joining_org: Organization,
    ) -> None:
        """A cardless record of four receives two: the shelf says six."""
        record = _cardless_record(
            db_session,
            joining_org.id,
            name=f'Legacy Receipt {uuid4().hex[:6]}',
            location_id=joining_shelf.id,
            quantity=Decimal('4'),
        )
        db_session.commit()

        before = client.get('/api/v1/stats/reconciliation', headers=joining_headers)
        assert before.status_code == status.HTTP_200_OK, before.text
        assert before.json()['quant_move_drift_count'] == 0, (
            'a cardless record is invisible to both sides of the pair'
        )

        complete_status, _, body = _run_doc(
            client,
            joining_headers,
            {
                'type': 'IN',
                'partner_id': str(joining_partner.id),
                'target_location_id': str(joining_shelf.id),
                'lines': [{'item_id': str(record.id), 'expected_quantity': 2}],
            },
        )
        assert complete_status == status.HTTP_200_OK, body

        db_session.expire_all()
        received = db_session.get(Item, record.id)
        assert received is not None and received.template_id is not None, (
            'the receipt bound the record to a card'
        )
        assert received.quantity == Decimal('6'), 'the record holds four plus two'

        _the_register_agrees(
            db_session, joining_org.id, received.template_id, [joining_shelf.id]
        )
        assert _layer_quantity(db_session, joining_org.id, received.template_id) == (
            Decimal('6')
        ), 'the cost history covers what the shelf holds'

        after = client.get('/api/v1/stats/reconciliation', headers=joining_headers)
        assert after.status_code == status.HTTP_200_OK, after.text
        assert after.json()['quant_move_drift_count'] == 0, after.json()
        assert Decimal(str(after.json()['quant_move_drift_total'])) == Decimal('0')

    def test_two_records_differing_only_by_the_card_read_the_same_way(
        self,
        client: TestClient,
        joining_headers: dict[str, str],
        joining_shelf: StorageLocation,
        joining_partner: Partner,
        db_session: Session,
        joining_org: Organization,
    ) -> None:
        """The differential: card present or absent, one relation holds.

        A record the register knows and a record the register has never
        heard of stand on one shelf, four apiece. The same delivery of two
        lands on each. The carded one ends at records == movements because
        it always was in the ledger; the cardless one ends there only when its
        adoption posts what stood before the delivery.
        """
        # The control: a carded record the register really knows, opened the
        # way any priced receipt opens one — of a product on the list.
        card = client.post(
            '/api/v1/items/product-templates',
            headers=joining_headers,
            json={'name': f'Carded Twin {uuid4().hex[:6]}'},
        )
        assert card.status_code == status.HTTP_201_CREATED, card.text
        carded_status, _, carded_body = _run_doc(
            client,
            joining_headers,
            {
                'type': 'IN',
                'partner_id': str(joining_partner.id),
                'target_location_id': str(joining_shelf.id),
                'lines': [
                    {
                        'product_template_id': card.json()['id'],
                        'expected_quantity': 4,
                        'unit_price': '2.00',
                    }
                ],
            },
        )
        assert carded_status == status.HTTP_200_OK, carded_body

        cardless = _cardless_record(
            db_session,
            joining_org.id,
            name=f'Cardless Twin {uuid4().hex[:6]}',
            location_id=joining_shelf.id,
            quantity=Decimal('4'),
        )
        db_session.commit()

        db_session.expire_all()
        carded_row = (
            db_session.scalars(
                select(Item).where(
                    Item.organization_id == joining_org.id,
                    Item.template_id.is_not(None),
                    Item.storage_location_id == joining_shelf.id,
                )
            )
        ).first()
        assert carded_row is not None, 'the priced receipt opened a carded record'

        for record_id in (carded_row.id, cardless.id):
            complete_status, _, body = _run_doc(
                client,
                joining_headers,
                {
                    'type': 'IN',
                    'partner_id': str(joining_partner.id),
                    'target_location_id': str(joining_shelf.id),
                    'lines': [{'item_id': str(record_id), 'expected_quantity': 2}],
                },
            )
            assert complete_status == status.HTTP_200_OK, body

        db_session.expire_all()
        adopted = db_session.get(Item, cardless.id)
        assert adopted is not None and adopted.template_id is not None, (
            'the receipt bound the cardless record to a card'
        )
        for template_id in (carded_row.template_id, adopted.template_id):
            assert template_id is not None
            _the_register_agrees(
                db_session, joining_org.id, template_id, [joining_shelf.id]
            )
