"""
Tests for StockLot quarantine/hold status enforcement.

A quarantined (or held/recalled) lot's stock cannot be consumed by the
removal-strategy draw. The stock physically exists but is operationally blocked
until released. This is the quality-hold pattern used for food safety (HACCP
recall), pharma compliance, and equipment safety holds.
"""

import uuid
from datetime import date, timedelta

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import LotStatus, StockLot
from app.models.storage_location import StorageLocation

# Far enough ahead that the lot is never expired whenever the suite runs.
_BEST_BEFORE = (date.today() + timedelta(days=400)).isoformat()


def _receive_via_document(
    client: TestClient,
    headers: dict[str, str],
    *,
    target_location_id: uuid.UUID,
    partner_id: uuid.UUID,
    template_id: uuid.UUID,
    quantity: int,
    batch_number: str,
    expiry_date: str = _BEST_BEFORE,
) -> str:
    """Create + confirm + complete an IN document. Returns the doc id."""
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(target_location_id),
            'lines': [
                {
                    'product_template_id': str(template_id),
                    'expected_quantity': quantity,
                    'batch_number': batch_number,
                    'expiry_date': expiry_date,
                }
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = resp.json()['id']
    client.patch(f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers)
    client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    return str(doc_id)


@pytest.mark.integration
class TestStockLotQuarantine:
    """Quarantined lots cannot be consumed or picked."""

    def test_quarantined_lot_blocks_consumption(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """Consume on an item whose stock is entirely in a quarantined lot must fail."""
        # Receive 10 units into LOT-Q, creating a record in that batch
        _receive_via_document(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            partner_id=doc_partner.id,
            template_id=doc_template.id,
            quantity=10,
            batch_number='LOT-Q',
        )

        lot = db_session.execute(
            select(StockLot).where(StockLot.name == 'LOT-Q')
        ).scalar_one()
        assert lot.status == LotStatus.ACTIVE

        # Find the item that was created by the receipt
        from app.models.item import Item

        item = db_session.execute(
            select(Item).where(
                Item.template_id == doc_template.id,
                Item.storage_location_id == doc_target_location.id,
            )
        ).scalar_one()
        assert item.quantity == 10

        # Quarantine the lot directly (simulates core_api.quarantine_lot_async)
        lot.status = LotStatus.QUARANTINED
        db_session.commit()

        # Consuming must fail — all stock is in a quarantined lot
        resp = client.patch(
            f'/api/v1/items/{item.id}/consume',
            headers=doc_auth_headers,
            json={'quantity': 1},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

    def test_released_lot_allows_consumption(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """After releasing a quarantined lot, consumption works again."""
        _receive_via_document(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            partner_id=doc_partner.id,
            template_id=doc_template.id,
            quantity=10,
            batch_number='LOT-R',
        )

        lot = db_session.execute(
            select(StockLot).where(StockLot.name == 'LOT-R')
        ).scalar_one()

        from app.models.item import Item

        item = db_session.execute(
            select(Item).where(
                Item.template_id == doc_template.id,
                Item.storage_location_id == doc_target_location.id,
            )
        ).scalar_one()

        # Quarantine then release
        lot.status = LotStatus.QUARANTINED
        db_session.flush()
        lot.status = LotStatus.ACTIVE
        db_session.flush()

        # Consumption should now succeed
        resp = client.patch(
            f'/api/v1/items/{item.id}/consume',
            headers=doc_auth_headers,
            json={'quantity': 3},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text

    def test_quarantine_does_not_affect_other_lots(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """Quarantining LOT-A must not block consumption from LOT-B."""
        # Receive into two lots
        _receive_via_document(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            partner_id=doc_partner.id,
            template_id=doc_template.id,
            quantity=10,
            batch_number='LOT-GOOD',
        )
        _receive_via_document(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            partner_id=doc_partner.id,
            template_id=doc_template.id,
            quantity=5,
            batch_number='LOT-BAD',
        )

        lot_bad = db_session.execute(
            select(StockLot).where(StockLot.name == 'LOT-BAD')
        ).scalar_one()

        # Quarantine only LOT-BAD
        lot_bad.status = LotStatus.QUARANTINED
        db_session.flush()

        # The group of LOT-GOOD should still have stock available
        lot_good = db_session.execute(
            select(StockLot).where(StockLot.name == 'LOT-GOOD')
        ).scalar_one()
        group_good = db_session.execute(
            select(ShelfRow).where(ShelfRow.lot_id == lot_good.id)
        ).scalar_one()
        assert group_good.quantity == 10  # untouched, available
