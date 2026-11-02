"""A second delivery of a catalogued product tops up the record it already has.

Completing a receipt used to call ``items.create`` for every line whose
product was named by template or barcode, without ever asking whether that
product was already on the shelf. The two halves of the consequence:

- **template with a barcode** — the second receipt broke
  ``uq_items_org_barcode_active`` and the endpoint answered 500.
- **template without one** — nothing stopped it, so the catalogue grew a
  second row and the stock of one product was split across two records.

Either way a catalogued product could be received exactly once. These tests
pin the fix: the line resolves to the existing record first, and the receipt
follows the same path as a line that named an item outright.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.storage_location import StorageLocation
from tests.integration._shelf import anchor_pending_records


def _receive(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: UUID,
    target_location_id: UUID,
    quantity: int,
    template_id: UUID | None = None,
    barcode: str | None = None,
    name: str | None = None,
    expiry_date: str | None = None,
) -> tuple[int, str]:
    """Create → confirm → complete one IN document; return the last response."""
    line: dict[str, object] = {'expected_quantity': quantity}
    if template_id is not None:
        line['product_template_id'] = str(template_id)
    if barcode is not None:
        line['barcode'] = barcode
    if name is not None:
        line['name'] = name
    if expiry_date is not None:
        line['expiry_date'] = expiry_date

    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(target_location_id),
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
    return complete.status_code, complete.text


def _items_for(db_session: Session, org_id: UUID, template_id: UUID) -> list[Item]:
    return list(
        db_session.scalars(
            select(Item).where(
                Item.organization_id == org_id,
                Item.template_id == template_id,
                Item.is_deleted.is_(False),
            )
        ).all()
    )


@pytest.mark.integration
class TestReceiptTopsUpExistingStock:
    def test_second_receipt_of_barcoded_template_succeeds_and_sums(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        h: ModuleTestHelper,
    ) -> None:
        template = h.create_template(
            doc_org, name='Vanilla Sugar', barcode='5901234000011'
        )

        code, body = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_target_location.id,
            template_id=template.id,
            quantity=4,
        )
        assert code == status.HTTP_200_OK, body

        code, body = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_target_location.id,
            template_id=template.id,
            quantity=6,
        )
        assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        items = _items_for(db_session, doc_org.id, template.id)
        assert len(items) == 1
        assert items[0].quantity == Decimal('10')

    def test_second_receipt_of_unbarcoded_template_sums_instead_of_duplicating(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        h: ModuleTestHelper,
    ) -> None:
        template = h.create_template(doc_org, name='MacBook Pro 14', barcode=None)

        for quantity in (3, 3):
            code, body = _receive(
                client,
                doc_auth_headers,
                partner_id=doc_partner.id,
                target_location_id=doc_target_location.id,
                template_id=template.id,
                quantity=quantity,
            )
            assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        items = _items_for(db_session, doc_org.id, template.id)
        assert len(items) == 1
        assert items[0].quantity == Decimal('6')

    def test_receipt_into_another_location_opens_a_record_there(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_source_location: StorageLocation,
        h: ModuleTestHelper,
    ) -> None:
        """Two shelves, two records — because the ledger is keyed that way.

        The movement ledger nets a quantity per (template, location) and the
        reconciliation report compares it against what the records on that
        shelf hold (ADR-004). One record standing in the first warehouse
        and holding the stock of both would put each of them in drift, and
        send anyone reading the catalogue to the wrong building.
        """
        template = h.create_template(
            doc_org, name='Cocoa Powder', barcode='5901234000028'
        )

        code, body = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_target_location.id,
            template_id=template.id,
            quantity=2,
        )
        assert code == status.HTTP_200_OK, body

        code, body = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_source_location.id,
            template_id=template.id,
            quantity=5,
        )
        assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        items = _items_for(db_session, doc_org.id, template.id)
        assert {(item.storage_location_id, item.quantity) for item in items} == {
            (doc_target_location.id, Decimal('2')),
            (doc_source_location.id, Decimal('5')),
        }
        # The record that carries the barcode is the one that was there
        # first; the second inherits its identity from the template, so
        # ``uq_items_org_barcode_active`` has nothing to object to.
        assert [item.barcode for item in items].count('5901234000028') <= 1

    def test_record_and_movement_land_on_the_same_shelf(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_source_location: StorageLocation,
        h: ModuleTestHelper,
    ) -> None:
        """A putaway rule moves the goods, and the record goes with them.

        The rule used to steer the stock alone: the delivery raised a quant on
        the shelf the rule named while the record it topped up went on
        standing where it had been, and the document named a third place. The
        record and the ledger's movement now answer with one shelf, and the
        line says which one it was.
        """
        from app.models.stock_move import StockMove

        template = h.create_template(doc_org, name='Smoked Bacon', barcode=None)

        code, body = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_source_location.id,
            template_id=template.id,
            quantity=50,
        )
        assert code == status.HTTP_200_OK, body

        rule = client.post(
            '/api/v1/warehouse/putaway-rules',
            headers=doc_auth_headers,
            json={
                'product_template_id': str(template.id),
                'target_location_id': str(doc_target_location.id),
                'priority': 10,
            },
        )
        assert rule.status_code == status.HTTP_201_CREATED, rule.text

        # The document asks for the source warehouse; the rule says otherwise.
        code, body = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_source_location.id,
            template_id=template.id,
            quantity=12,
        )
        assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        items = {
            item.storage_location_id: item.quantity
            for item in _items_for(db_session, doc_org.id, template.id)
        }
        moved: dict[UUID | None, Decimal] = {}
        for move in db_session.scalars(
            select(StockMove).where(
                StockMove.organization_id == doc_org.id,
                StockMove.product_template_id == template.id,
                StockMove.state == 'done',
            )
        ).all():
            moved[move.to_location_id] = (
                moved.get(move.to_location_id, Decimal('0')) + move.quantity
            )
            moved[move.from_location_id] = (
                moved.get(move.from_location_id, Decimal('0')) - move.quantity
            )
        moved.pop(None, None)
        assert items == {
            doc_source_location.id: Decimal('50'),
            doc_target_location.id: Decimal('12'),
        }
        assert moved == items

    def test_batches_with_different_expiry_stay_separate_records(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        h: ModuleTestHelper,
    ) -> None:
        """Without a barcode there is room for one row per expiry — use it.

        ``Item.expiry_date`` is the rotation cache for non-lot stock, so
        folding a June batch into a December row would make FEFO read a date
        that is true of neither.
        """
        template = h.create_template(doc_org, name='Fresh Yeast', barcode=None)

        for expiry in ('2026-06-30', '2026-12-31'):
            code, body = _receive(
                client,
                doc_auth_headers,
                partner_id=doc_partner.id,
                target_location_id=doc_target_location.id,
                template_id=template.id,
                quantity=1,
                expiry_date=expiry,
            )
            assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        items = _items_for(db_session, doc_org.id, template.id)
        assert len(items) == 2
        assert sorted(
            item.expiry_date for item in items if item.expiry_date is not None
        ) == [date(2026, 6, 30), date(2026, 12, 31)]

    def test_serialized_records_are_never_merged(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        h: ModuleTestHelper,
    ) -> None:
        """A record carrying a serial number is one physical thing.

        Equipment and any other serialized vertical build exactly such rows,
        and a delivery of the same model must not add its quantity to one of
        them.
        """
        template = h.create_template(doc_org, name='Drill Model X', barcode=None)
        serialized = Item(
            name='Drill Model X',
            organization_id=doc_org.id,
            storage_location_id=doc_target_location.id,
            template_id=template.id,
            serial_number='SN-0001',
            quantity=Decimal('1'),
        )
        db_session.add(serialized)
        anchor_pending_records(db_session)
        db_session.commit()

        code, body = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_target_location.id,
            template_id=template.id,
            quantity=2,
        )
        assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        items = _items_for(db_session, doc_org.id, template.id)
        assert len(items) == 2
        assert serialized.quantity == Decimal('1')
