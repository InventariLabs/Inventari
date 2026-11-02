"""
Regression tests for lot-aware direct consume / move (CoreAPI drift fix).

Before the fix, direct ``PATCH /items/{id}/consume`` / ``/move`` always
debited the lot-LESS quant (``lot_id=None``), even when the stock had been
received via a document into a lot-SPECIFIC quant. That caused
``Item.quantity`` / quant drift and left document-received lots untouched.

These tests hold direct consume/move to the record's own batch: the batch's
group on the shelf (the records' view) is the one that changes, the ledger's
movements name the batch, and no lot-less stock appears anywhere.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation


def _receive_via_document(
    client: TestClient,
    headers: dict[str, str],
    *,
    target_location_id: uuid.UUID,
    partner_id: uuid.UUID,
    template_id: uuid.UUID,
    quantity: int,
    batch_number: str,
    expiry_date: str = '2026-12-31',
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


def _lotless_moves(db_session: Session, template_id: uuid.UUID) -> list[StockMove]:
    """The movements of *template_id* that name no batch — none are expected."""
    return list(
        db_session.scalars(
            select(StockMove).where(
                StockMove.product_template_id == template_id,
                StockMove.lot_id.is_(None),
            )
        )
    )


@pytest.mark.integration
class TestLotAwareConsumeMove:
    """Direct consume/move must honour lot-specific stock."""

    def test_consume_decrements_lot_specific_quant(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        # Receive 10 units into LOT-A via a document receipt.
        doc_id = _receive_via_document(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            partner_id=doc_partner.id,
            template_id=doc_template.id,
            quantity=10,
            batch_number='LOT-A',
        )

        # Resolve the item created by the receipt, then end the read
        # transaction so later assertions open a fresh snapshot that sees
        # the consume commit.
        from app.modules.warehouse.models import DocumentLine

        item_id = db_session.scalars(
            select(DocumentLine.item_id).where(DocumentLine.document_id == doc_id)
        ).first()
        assert item_id is not None
        db_session.commit()

        # Direct consume of 3 units (NOT via a document dispatch).
        r = client.patch(
            f'/api/v1/items/{item_id}/consume',
            headers=doc_auth_headers,
            json={'quantity': 3},
        )
        assert r.status_code == status.HTTP_200_OK, r.text

        lot = db_session.scalars(
            select(StockLot).where(
                StockLot.product_template_id == doc_template.id,
                StockLot.name == 'LOT-A',
            )
        ).first()
        assert lot is not None

        lot_group = db_session.scalars(
            select(ShelfRow).where(ShelfRow.lot_id == lot.id)
        ).first()
        assert lot_group is not None
        # The batch's group was debited (10 -> 7)...
        assert lot_group.quantity == Decimal('7')

        # ...and NO phantom lot-less stock was fabricated (the old bug).
        lotless = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.product_template_id == doc_template.id,
                ShelfRow.storage_location_id == doc_target_location.id,
                ShelfRow.lot_id.is_(None),
            )
        ).first()
        assert lotless is None
        assert _lotless_moves(db_session, doc_template.id) == [], (
            'the consume was written to the ledger without its batch'
        )

    def test_move_preserves_lot_identity(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        # Receive 10 units into LOT-B at the target location.
        doc_id = _receive_via_document(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            partner_id=doc_partner.id,
            template_id=doc_template.id,
            quantity=10,
            batch_number='LOT-B',
        )

        from app.modules.warehouse.models import DocumentLine

        item_id = db_session.scalars(
            select(DocumentLine.item_id).where(DocumentLine.document_id == doc_id)
        ).first()
        assert item_id is not None
        db_session.commit()

        # Move the item to the source location.
        r = client.patch(
            f'/api/v1/items/{item_id}/move',
            headers=doc_auth_headers,
            json={'to_location_id': str(doc_source_location.id)},
        )
        assert r.status_code == status.HTTP_200_OK, r.text

        lot = db_session.scalars(
            select(StockLot).where(
                StockLot.product_template_id == doc_template.id,
                StockLot.name == 'LOT-B',
            )
        ).first()
        assert lot is not None

        # Source (origin = target_location) drained: the record left it, so
        # the batch's group there is gone...
        src_group = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.lot_id == lot.id,
                ShelfRow.storage_location_id == doc_target_location.id,
            )
        ).first()
        assert src_group is None or src_group.quantity == Decimal('0'), (
            'the shelf the record left still holds its batch'
        )

        # ...destination carries the SAME lot at full quantity.
        dst_group = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.lot_id == lot.id,
                ShelfRow.storage_location_id == doc_source_location.id,
            )
        ).first()
        assert dst_group is not None
        assert dst_group.quantity == Decimal('10')

        # No phantom lot-less stock at either location, nor in the ledger.
        lotless = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.product_template_id == doc_template.id,
                ShelfRow.lot_id.is_(None),
            )
        ).first()
        assert lotless is None
        assert _lotless_moves(db_session, doc_template.id) == [], (
            'the move was written to the ledger without its batch'
        )

    def test_consume_across_multiple_lots(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        # Receive 4 into LOT-C (creates item1).
        doc1 = _receive_via_document(
            client,
            doc_auth_headers,
            target_location_id=doc_target_location.id,
            partner_id=doc_partner.id,
            template_id=doc_template.id,
            quantity=4,
            batch_number='LOT-C',
        )

        from app.modules.warehouse.models import DocumentLine

        item_id = db_session.scalars(
            select(DocumentLine.item_id).where(DocumentLine.document_id == doc1)
        ).first()
        assert item_id is not None
        db_session.commit()

        # Receive 6 into LOT-D naming the SAME item. A record holds one
        # batch, so the delivery opens a record of its own beside it
        # (LOT-C=4 on the first, LOT-D=6 on the second). It used to top the
        # first record up to 10 across two batches; a record that still
        # spans batches is the bridge's fallback, pinned where the bridge is
        # tested.
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(item_id),
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 6,
                        'batch_number': 'LOT-D',
                        'expiry_date': '2026-12-31',
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc2 = resp.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{doc2}/confirm', headers=doc_auth_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc2}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        second_id = db_session.scalars(
            select(DocumentLine.item_id).where(DocumentLine.document_id == doc2)
        ).first()
        assert second_id is not None and second_id != item_id
        db_session.commit()

        # Each record gives up all it holds, off its own batch — and never
        # off lot-less stock that was never there.
        for record_id, quantity in ((item_id, 4), (second_id, 6)):
            r = client.patch(
                f'/api/v1/items/{record_id}/consume',
                headers=doc_auth_headers,
                json={'quantity': quantity},
            )
            assert r.status_code == status.HTTP_200_OK, r.text

        for name in ('LOT-C', 'LOT-D'):
            lot = db_session.scalars(
                select(StockLot).where(
                    StockLot.product_template_id == doc_template.id,
                    StockLot.name == name,
                )
            ).first()
            assert lot is not None
            group = db_session.scalars(
                select(ShelfRow).where(ShelfRow.lot_id == lot.id)
            ).first()
            assert group is None or group.quantity == Decimal('0'), (
                f'{name} still holds stock after its record gave up all of it'
            )

        lotless = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.product_template_id == doc_template.id,
                ShelfRow.lot_id.is_(None),
            )
        ).first()
        assert lotless is None
        assert _lotless_moves(db_session, doc_template.id) == [], (
            'a consume was written to the ledger without its batch'
        )
