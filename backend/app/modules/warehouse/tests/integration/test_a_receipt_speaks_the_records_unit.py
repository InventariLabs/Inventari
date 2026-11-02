"""A receipt in the supplier's unit lands on the record in the record's unit.

The document speaks kilograms and the record is kept in grams. For a carded
record the receipt converted before it wrote anything. For a record that
predates its card it could not — the card, which is what the conversion asks,
was adopted after the record had already been topped up — so the sum happened
across two units: 4 g of stock plus a 2 kg delivery came out as 6 on the
record while the shelf took 2004 g. The record and the ledger then said two
numbers about one tray, and the reconciliation report named a drift the
worker had not caused.

The card comes first, so the conversion has an answer, and the opening
balance follows in the same unit. These tests hold the receipt to the pair
of numbers a carded record already produced, with a carded twin measured
beside the cardless one: same shelf, same holding, same delivery, and — what
matters — one number on both sides at the end.
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
def weighing_org(h: ModuleTestHelper) -> Organization:
    """The documents organization, plus the module the report lives in."""
    org = h.create_org(
        'Weighing Receipt Org',
        ['core', 'items', 'locations', 'categories', 'warehouse', 'approvals', 'stats'],
    )
    h.set_module_settings(org, 'approvals', {'allow_admin_self_approve': True})
    return org


@pytest.fixture
def weighing_user(h: ModuleTestHelper, weighing_org: Organization) -> User:
    return h.create_user(weighing_org, email='weighing-receipt@example.com')


@pytest.fixture
def weighing_headers(h: ModuleTestHelper, weighing_user: User) -> dict[str, str]:
    return h.get_auth_headers(weighing_user)


@pytest.fixture
def weighing_shelf(
    h: ModuleTestHelper, weighing_org: Organization, weighing_user: User
) -> StorageLocation:
    storage_type = h.create_storage_type(
        'Weighing Warehouse', 'WEIGHING_WAREHOUSE', organization_id=weighing_org.id
    )
    return h.create_storage_location(
        weighing_org, storage_type, weighing_user, name='Weighing Shelf'
    )


@pytest.fixture
def weighing_elsewhere(
    h: ModuleTestHelper, weighing_org: Organization, weighing_user: User
) -> StorageLocation:
    storage_type = h.create_storage_type(
        'Weighing Overflow', 'WEIGHING_OVERFLOW', organization_id=weighing_org.id
    )
    return h.create_storage_location(
        weighing_org, storage_type, weighing_user, name='Overflow Shelf'
    )


@pytest.fixture
def weighing_partner(
    h: ModuleTestHelper, weighing_org: Organization, weighing_user: User
) -> Partner:
    return h.create_partner(weighing_org, weighing_user, name='Weighing Goods')


def _cardless_record(
    db_session: Session,
    org_id: UUID,
    *,
    name: str,
    location_id: UUID,
    quantity: Decimal,
    uom_id: UUID,
) -> Item:
    """The shape of anything stocked before the catalogue existed."""
    item = Item(
        name=name,
        organization_id=org_id,
        template_id=None,
        storage_location_id=location_id,
        quantity=quantity,
        uom_id=uom_id,
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


def _receive(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: UUID,
    location_id: UUID,
    line: dict[str, object],
) -> None:
    """One IN document, confirmed and completed — the whole door."""
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(location_id),
            'lines': [line],
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
    assert complete.status_code == status.HTTP_200_OK, complete.text


def _both_sides_read_the_same(
    db_session: Session, org_id: UUID, template_id: UUID, location_id: UUID
) -> Decimal:
    """The ledger pair the reconciliation report compares, read for one shelf."""
    db_session.expire_all()
    records = _record_quantity(db_session, org_id, template_id, location_id)
    moved = _moved_quantity(db_session, org_id, template_id, location_id)
    assert records == moved, (
        f'the record reads {records} where the ledger nets to {moved}'
    )
    return records


@pytest.mark.integration
class TestAReceiptConvertsBeforeItWrites:
    def test_a_delivery_in_kilograms_lands_on_a_record_kept_in_grams(
        self,
        h: ModuleTestHelper,
        client: TestClient,
        weighing_headers: dict[str, str],
        weighing_shelf: StorageLocation,
        weighing_partner: Partner,
        db_session: Session,
        weighing_org: Organization,
    ) -> None:
        """Four grams of stock plus a two-kilogram delivery is 2004 grams."""
        gram = h.get_uom('g')
        kilogram = h.get_uom('kg')
        record = _cardless_record(
            db_session,
            weighing_org.id,
            name=f'Legacy Weighed {uuid4().hex[:6]}',
            location_id=weighing_shelf.id,
            quantity=Decimal('4'),
            uom_id=gram.id,
        )
        db_session.commit()

        _receive(
            client,
            weighing_headers,
            partner_id=weighing_partner.id,
            location_id=weighing_shelf.id,
            line={
                'item_id': str(record.id),
                'expected_quantity': 2,
                'uom_id': str(kilogram.id),
            },
        )

        db_session.expire_all()
        received = db_session.get(Item, record.id)
        assert received is not None and received.template_id is not None, (
            'the receipt bound the record to a card'
        )
        assert received.quantity == Decimal('2004'), (
            'the record counts its own unit: four grams plus the delivery '
            f'converted, not four plus two — got {received.quantity}'
        )
        assert received.uom_id == gram.id, 'the record kept its unit'

        total = _both_sides_read_the_same(
            db_session, weighing_org.id, received.template_id, weighing_shelf.id
        )
        assert total == Decimal('2004')
        assert _layer_quantity(
            db_session, weighing_org.id, received.template_id
        ) == Decimal('2004'), 'the cost history covers what the shelf holds'

    def test_the_carded_twin_reads_the_same_pair(
        self,
        h: ModuleTestHelper,
        client: TestClient,
        weighing_headers: dict[str, str],
        weighing_shelf: StorageLocation,
        weighing_partner: Partner,
        db_session: Session,
        weighing_org: Organization,
    ) -> None:
        """Card present or absent, one shelf, one holding, one delivery."""
        gram = h.get_uom('g')
        kilogram = h.get_uom('kg')

        twin_name = f'Weighed Twin {uuid4().hex[:6]}'
        h.create_template(weighing_org, name=twin_name, uom_id=str(gram.id))
        opened = client.post(
            '/api/v1/items',
            headers=weighing_headers,
            json={
                'name': twin_name,
                'location_id': str(weighing_shelf.id),
                'quantity': 4,
            },
        )
        assert opened.status_code == status.HTTP_201_CREATED, opened.text
        carded_id = UUID(opened.json()['id'])

        cardless = _cardless_record(
            db_session,
            weighing_org.id,
            name=f'Legacy Twin {uuid4().hex[:6]}',
            location_id=weighing_shelf.id,
            quantity=Decimal('4'),
            uom_id=gram.id,
        )
        db_session.commit()

        for record_id in (carded_id, cardless.id):
            _receive(
                client,
                weighing_headers,
                partner_id=weighing_partner.id,
                location_id=weighing_shelf.id,
                line={
                    'item_id': str(record_id),
                    'expected_quantity': 2,
                    'uom_id': str(kilogram.id),
                },
            )

        db_session.expire_all()
        adopted = db_session.get(Item, cardless.id)
        carded = db_session.get(Item, carded_id)
        assert adopted is not None and carded is not None
        assert adopted.template_id is not None
        assert carded.template_id is not None

        assert carded.quantity == Decimal('2004')
        assert adopted.quantity == Decimal('2004'), (
            f'the cardless twin reads {adopted.quantity} where the carded one '
            'reads 2004'
        )
        for template_id in (carded.template_id, adopted.template_id):
            assert _both_sides_read_the_same(
                db_session, weighing_org.id, template_id, weighing_shelf.id
            ) == Decimal('2004')


@pytest.mark.integration
class TestTheCardFollowsTheRecordItWasAdoptedFor:
    def test_a_delivery_to_another_shelf_joins_the_record_that_waited(
        self,
        h: ModuleTestHelper,
        client: TestClient,
        weighing_headers: dict[str, str],
        weighing_shelf: StorageLocation,
        weighing_elsewhere: StorageLocation,
        weighing_partner: Partner,
        db_session: Session,
        weighing_org: Organization,
    ) -> None:
        """The named record's own shelf is where its holding is posted.

        The line names a record standing on one shelf and the document takes
        the goods to another: they are not the delivery, and the stock the
        record already held is not the delivery's to move. Adopting the card
        for that record means posting its holding where it stands — the
        delivery's shelf gets the delivery, and both shelves keep one number.
        """
        gram = h.get_uom('g')
        kilogram = h.get_uom('kg')
        waiting = _cardless_record(
            db_session,
            weighing_org.id,
            name=f'Waiting Weighed {uuid4().hex[:6]}',
            location_id=weighing_shelf.id,
            quantity=Decimal('4'),
            uom_id=gram.id,
        )
        db_session.commit()

        _receive(
            client,
            weighing_headers,
            partner_id=weighing_partner.id,
            location_id=weighing_elsewhere.id,
            line={
                'item_id': str(waiting.id),
                'expected_quantity': 2,
                'uom_id': str(kilogram.id),
            },
        )

        db_session.expire_all()
        joined = db_session.get(Item, waiting.id)
        assert joined is not None and joined.template_id is not None, (
            'the record the line named keeps its stock in the ledger too'
        )
        assert joined.quantity == Decimal('4'), (
            'nothing landed on the record the delivery did not go to'
        )
        assert _both_sides_read_the_same(
            db_session, weighing_org.id, joined.template_id, weighing_shelf.id
        ) == Decimal('4')

        elsewhere_record = (
            db_session.scalars(
                select(Item).where(
                    Item.organization_id == weighing_org.id,
                    Item.storage_location_id == weighing_elsewhere.id,
                )
            )
        ).one()
        assert elsewhere_record.template_id == joined.template_id, (
            'one product, one card, wherever its stock stands'
        )
        assert elsewhere_record.quantity == Decimal('2000')
        assert _both_sides_read_the_same(
            db_session,
            weighing_org.id,
            elsewhere_record.template_id,
            weighing_elsewhere.id,
        ) == Decimal('2000')
