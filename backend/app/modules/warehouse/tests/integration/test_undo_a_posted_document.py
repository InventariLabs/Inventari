"""A just-posted document is undone by a reversing correction, not by hand.

"Undo" is the way back from a typo on the one-step screen: the system writes
the correcting document, posts it and leaves both rows in the history. These
tests hold the two promises that make the button safe — the stock it posted
goes back, and the original names the document that reversed it — and the
refusal that sends the reader to a correction when later movements have used
the stock up.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove, StockMoveReferenceType
from app.models.storage_location import StorageLocation
from app.modules.warehouse.models import Document, DocumentRelation


def _post(
    client: TestClient,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    resp = client.post(
        '/api/v1/warehouse/documents/post', headers=headers, json=payload
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return cast(dict[str, Any], resp.json())


def _receipt_payload(
    *,
    partner: Partner,
    target: StorageLocation,
    template: ProductTemplate,
    quantity: str = '10',
) -> dict[str, Any]:
    return {
        'type': 'IN',
        'partner_id': str(partner.id),
        'target_location_id': str(target.id),
        'lines': [
            {'product_template_id': str(template.id), 'expected_quantity': quantity}
        ],
    }


def _issue_payload(
    *,
    partner: Partner,
    source: StorageLocation,
    item: Item,
    quantity: str = '5',
) -> dict[str, Any]:
    return {
        'type': 'OUT',
        'partner_id': str(partner.id),
        'source_location_id': str(source.id),
        'lines': [
            {
                'item_id': str(item.id),
                'product_template_id': str(item.template_id),
                'expected_quantity': quantity,
                'unit_price': '10.00',
            }
        ],
    }


@pytest.mark.integration
class TestUndoAPostedDocument:
    def test_a_receipt_is_undone_by_a_linked_reversal_that_takes_the_stock_back(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        posted = _post(
            client,
            doc_auth_headers,
            _receipt_payload(
                partner=doc_partner,
                target=doc_target_location,
                template=doc_template,
            ),
        )
        record_id = posted['lines'][0]['item_id']
        assert record_id is not None
        db_session.expire_all()
        record = db_session.get(Item, record_id)
        assert record is not None
        assert record.quantity == Decimal('10')

        undone = client.post(
            f'/api/v1/warehouse/documents/{posted["id"]}/undo', headers=doc_auth_headers
        )
        assert undone.status_code == status.HTTP_200_OK, undone.text
        reversal = undone.json()
        assert reversal['type'] == 'CORRECTION'
        assert reversal['status'] == 'COMPLETED'
        assert reversal['corrects_document_id'] == posted['id']
        assert reversal['number'] != posted['number']

        # Both rows stay in the history, and the original names the reversal.
        original = client.get(
            f'/api/v1/warehouse/documents/{posted["id"]}', headers=doc_auth_headers
        )
        assert original.status_code == status.HTTP_200_OK, original.text
        original_body = original.json()
        assert original_body['status'] == 'COMPLETED'
        assert original_body['reversed_by_id'] == reversal['id']
        assert original_body['reversed_by_number'] == reversal['number']

        db_session.expire_all()
        record = db_session.get(Item, record_id)
        assert record is not None
        assert record.quantity == Decimal('0')

        relation = db_session.scalars(
            select(DocumentRelation).where(
                DocumentRelation.source_document_id == reversal['id'],
                DocumentRelation.target_document_id == posted['id'],
                DocumentRelation.relation_type == 'reverses',
            )
        ).first()
        assert relation is not None

    def test_an_issue_is_undone_and_its_stock_returns_to_the_shelf(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_stock_item: Item,
    ) -> None:
        posted = _post(
            client,
            doc_auth_headers,
            _issue_payload(
                partner=doc_partner,
                source=doc_source_location,
                item=doc_stock_item,
            ),
        )
        assert posted['status'] == 'COMPLETED'

        undone = client.post(
            f'/api/v1/warehouse/documents/{posted["id"]}/undo', headers=doc_auth_headers
        )
        assert undone.status_code == status.HTTP_200_OK, undone.text
        assert undone.json()['status'] == 'COMPLETED'

        db_session.expire_all()
        shelf = db_session.get(Item, doc_stock_item.id)
        assert shelf is not None
        assert shelf.quantity == Decimal('100')

    def test_a_write_off_is_undone_and_its_stock_returns_to_the_shelf(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_stock_item: Item,
    ) -> None:
        # "Damaged or expired" is one of the purposes of the issue screen,
        # and a wrong press there is as much a typo as a wrong customer.
        posted = _post(
            client,
            doc_auth_headers,
            {
                'type': 'SCRAP',
                'reason_code': 'DAMAGED',
                'lines': [
                    {
                        'item_id': str(doc_stock_item.id),
                        'product_template_id': str(doc_stock_item.template_id),
                        'expected_quantity': '5',
                    }
                ],
            },
        )
        assert posted['status'] == 'COMPLETED'
        db_session.expire_all()
        shelf = db_session.get(Item, doc_stock_item.id)
        assert shelf is not None
        assert shelf.quantity == Decimal('95')

        undone = client.post(
            f'/api/v1/warehouse/documents/{posted["id"]}/undo', headers=doc_auth_headers
        )
        assert undone.status_code == status.HTTP_200_OK, undone.text
        assert undone.json()['status'] == 'COMPLETED'
        assert undone.json()['corrects_document_id'] == posted['id']

        db_session.expire_all()
        shelf = db_session.get(Item, doc_stock_item.id)
        assert shelf is not None
        assert shelf.quantity == Decimal('100')

    def test_a_transfer_is_undone_on_both_shelves(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_stock_item: Item,
    ) -> None:
        posted = _post(
            client,
            doc_auth_headers,
            {
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_stock_item.id),
                        'product_template_id': str(doc_stock_item.template_id),
                        'expected_quantity': '5',
                    }
                ],
            },
        )
        assert posted['status'] == 'COMPLETED'
        db_session.expire_all()
        arrived = db_session.scalars(
            select(Item).where(
                Item.template_id == doc_stock_item.template_id,
                Item.storage_location_id == doc_target_location.id,
            )
        ).first()
        assert arrived is not None
        assert arrived.quantity == Decimal('5')

        undone = client.post(
            f'/api/v1/warehouse/documents/{posted["id"]}/undo', headers=doc_auth_headers
        )
        assert undone.status_code == status.HTTP_200_OK, undone.text

        db_session.expire_all()

        # The record the transfer moved is the same record the return moves
        # back; what the shelf holds is the sum over its records, which is
        # where the remainder of a partial transfer stayed.
        def on_shelf(location_id: Any) -> Decimal:
            total = db_session.scalar(
                select(func.sum(Item.quantity)).where(
                    Item.template_id == doc_stock_item.template_id,
                    Item.storage_location_id == location_id,
                )
            )
            return Decimal(str(total or 0))

        assert on_shelf(doc_source_location.id) == Decimal('100')
        assert on_shelf(doc_target_location.id) == Decimal('0')

    def test_the_undo_is_refused_when_later_movements_used_the_stock(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        posted = _post(
            client,
            doc_auth_headers,
            _receipt_payload(
                partner=doc_partner,
                target=doc_target_location,
                template=doc_template,
            ),
        )
        record_id = posted['lines'][0]['item_id']
        db_session.expire_all()
        record = db_session.get(Item, record_id)
        assert record is not None
        _post(
            client,
            doc_auth_headers,
            _issue_payload(
                partner=doc_partner,
                source=doc_target_location,
                item=record,
                quantity='4',
            ),
        )

        undone = client.post(
            f'/api/v1/warehouse/documents/{posted["id"]}/undo', headers=doc_auth_headers
        )
        assert undone.status_code == status.HTTP_400_BAD_REQUEST, undone.text
        detail = undone.json()['detail']
        assert 'Correct' in detail['message']

        # The refusal wrote nothing: no reversal, and the stock stays where
        # the later issue left it.
        original = client.get(
            f'/api/v1/warehouse/documents/{posted["id"]}', headers=doc_auth_headers
        )
        assert original.json()['reversed_by_id'] is None
        db_session.expire_all()
        record = db_session.get(Item, record_id)
        assert record is not None
        assert record.quantity == Decimal('6')
        reversals = db_session.scalars(
            select(Document).where(
                Document.corrects_document_id == posted['id'],
                Document.organization_id == record.organization_id,
            )
        ).all()
        assert reversals == []

    def test_a_later_receipt_does_not_hide_stock_a_later_issue_used(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """Replenishment is not proof the receipt's own goods are still there.

        A receipt of ten, four issued and another four received reads as ten
        on the shelf, so a quantity check alone lets the undo through: the
        reversing correction empties a shelf whose first four goods were
        already issued. The movement ledger remembers the issue, and that is
        what refuses the undo. Without the ledger check this test gets 200.
        """
        posted = _post(
            client,
            doc_auth_headers,
            _receipt_payload(
                partner=doc_partner,
                target=doc_target_location,
                template=doc_template,
            ),
        )
        record_id = posted['lines'][0]['item_id']
        db_session.expire_all()
        record = db_session.get(Item, record_id)
        assert record is not None
        _post(
            client,
            doc_auth_headers,
            _issue_payload(
                partner=doc_partner,
                source=doc_target_location,
                item=record,
                quantity='4',
            ),
        )
        # The same product lands on the same shelf and tops the same record
        # up, so the shelf reads ten again.
        _post(
            client,
            doc_auth_headers,
            _receipt_payload(
                partner=doc_partner,
                target=doc_target_location,
                template=doc_template,
                quantity='4',
            ),
        )
        db_session.expire_all()
        record = db_session.get(Item, record_id)
        assert record is not None
        assert record.quantity == Decimal('10')

        undone = client.post(
            f'/api/v1/warehouse/documents/{posted["id"]}/undo', headers=doc_auth_headers
        )
        assert undone.status_code == status.HTTP_400_BAD_REQUEST, undone.text
        assert 'Correct' in undone.json()['detail']['message']

        # The refusal wrote nothing: the stock the later issue left is still
        # there, and no reversal was added to the history.
        db_session.expire_all()
        record = db_session.get(Item, record_id)
        assert record is not None
        assert record.quantity == Decimal('10')
        original = client.get(
            f'/api/v1/warehouse/documents/{posted["id"]}', headers=doc_auth_headers
        )
        assert original.json()['reversed_by_id'] is None

    def test_a_later_receipt_alone_leaves_the_undo_allowed(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """A second receipt used nothing, so the first can still go back.

        This pins the other side of the ledger check: only stock taken *off*
        the shelf the original filled blocks the undo, so a shelf holding two
        deliveries of the same product can give the later one up without
        refusing the earlier one.
        """
        posted = _post(
            client,
            doc_auth_headers,
            _receipt_payload(
                partner=doc_partner,
                target=doc_target_location,
                template=doc_template,
            ),
        )
        _post(
            client,
            doc_auth_headers,
            _receipt_payload(
                partner=doc_partner,
                target=doc_target_location,
                template=doc_template,
                quantity='4',
            ),
        )

        undone = client.post(
            f'/api/v1/warehouse/documents/{posted["id"]}/undo', headers=doc_auth_headers
        )
        assert undone.status_code == status.HTTP_200_OK, undone.text

        db_session.expire_all()
        record_id = posted['lines'][0]['item_id']
        record = db_session.get(Item, record_id)
        assert record is not None
        assert record.quantity == Decimal('4')

    def test_a_partial_correction_leaves_the_rest_of_the_receipt_undoable(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """A correction of the original is not a use of its stock.

        The line already says what that correction took; its movement must
        not be mistaken for a later document drawing on the receipt, or the
        remainder could never be undone. The reversal carries the six the
        line has left.
        """
        posted = _post(
            client,
            doc_auth_headers,
            _receipt_payload(
                partner=doc_partner,
                target=doc_target_location,
                template=doc_template,
            ),
        )
        correction = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': posted['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [{'original_line_number': 1, 'quantity_delta': -4}],
            },
        )
        assert correction.status_code == status.HTTP_201_CREATED, correction.text
        correction_id = correction.json()['id']
        assert (
            client.patch(
                f'/api/v1/warehouse/documents/{correction_id}/confirm',
                headers=doc_auth_headers,
            ).status_code
            == status.HTTP_200_OK
        )
        assert (
            client.patch(
                f'/api/v1/warehouse/documents/{correction_id}/complete',
                headers=doc_auth_headers,
                json={'complete_as_planned': True},
            ).status_code
            == status.HTTP_200_OK
        )

        undone = client.post(
            f'/api/v1/warehouse/documents/{posted["id"]}/undo', headers=doc_auth_headers
        )
        assert undone.status_code == status.HTTP_200_OK, undone.text
        assert Decimal(undone.json()['lines'][0]['quantity']) == Decimal('-6')

        db_session.expire_all()
        record_id = posted['lines'][0]['item_id']
        record = db_session.get(Item, record_id)
        assert record is not None
        assert record.quantity == Decimal('0')

    def test_a_completed_return_of_the_receipt_leaves_the_rest_undoable(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """A return of the original is not a use of its stock, like a correction.

        The return is stored original -> return, the other way round from a
        correction, and its departure used to be counted as some later
        document drawing on the receipt, so the undo was refused. It
        reverses what the line has left.
        """
        posted = _post(
            client,
            doc_auth_headers,
            _receipt_payload(
                partner=doc_partner,
                target=doc_target_location,
                template=doc_template,
            ),
        )
        returned = client.post(
            f'/api/v1/warehouse/documents/{posted["id"]}/return',
            headers=doc_auth_headers,
            json={
                'reason_code': 'DAMAGED',
                'lines': [{'original_line_number': 1, 'return_quantity': '4'}],
            },
        )
        assert returned.status_code == status.HTTP_201_CREATED, returned.text
        return_id = returned.json()['id']
        assert (
            client.patch(
                f'/api/v1/warehouse/documents/{return_id}/confirm',
                headers=doc_auth_headers,
            ).status_code
            == status.HTTP_200_OK
        )
        assert (
            client.patch(
                f'/api/v1/warehouse/documents/{return_id}/complete',
                headers=doc_auth_headers,
                json={'complete_as_planned': True},
            ).status_code
            == status.HTTP_200_OK
        )

        undone = client.post(
            f'/api/v1/warehouse/documents/{posted["id"]}/undo', headers=doc_auth_headers
        )
        assert undone.status_code == status.HTTP_200_OK, undone.text
        assert Decimal(undone.json()['lines'][0]['quantity']) == Decimal('-6')

        db_session.expire_all()
        record = db_session.get(Item, posted['lines'][0]['item_id'])
        assert record is not None
        assert record.quantity == Decimal('0')

    def test_a_move_is_refused_when_its_stock_left_the_target_shelf(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_stock_item: Item,
    ) -> None:
        posted = _post(
            client,
            doc_auth_headers,
            {
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_stock_item.id),
                        'product_template_id': str(doc_stock_item.template_id),
                        'expected_quantity': '5',
                    }
                ],
            },
        )
        moved_id = posted['lines'][0]['item_id']
        db_session.expire_all()
        moved = db_session.get(Item, moved_id)
        assert moved is not None
        _post(
            client,
            doc_auth_headers,
            _issue_payload(
                partner=doc_partner,
                source=doc_target_location,
                item=moved,
                quantity='2',
            ),
        )

        undone = client.post(
            f'/api/v1/warehouse/documents/{posted["id"]}/undo', headers=doc_auth_headers
        )
        assert undone.status_code == status.HTTP_400_BAD_REQUEST, undone.text
        assert 'Correct' in undone.json()['detail']['message']
        db_session.expire_all()
        moved = db_session.get(Item, moved_id)
        assert moved is not None
        assert moved.quantity == Decimal('3')

    def test_every_group_the_document_filled_is_checked(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """A window of the newest movements cannot answer this question.

        The goods most likely to have been used are the ones longest on the
        shelf, and their movements are the oldest. This receipt has more
        movements than a page holds — a second group landing after its own —
        and the departure that has to refuse the undo is in the group a page
        of the newest movements would drop whole. The check reads every group
        the document filled, not the newest slice of them.
        """
        posted = _post(
            client,
            doc_auth_headers,
            _receipt_payload(
                partner=doc_partner,
                target=doc_target_location,
                template=doc_template,
            ),
        )
        document_id = uuid.UUID(posted['id'])
        db_session.expire_all()
        landed_at = datetime.now(UTC) - timedelta(hours=2)
        original = db_session.scalars(
            select(StockMove).where(
                StockMove.reference_type == StockMoveReferenceType.DOCUMENT.value,
                StockMove.reference_id == document_id,
            )
        ).one()
        original.created_at = landed_at
        lot = StockLot(
            organization_id=original.organization_id,
            product_template_id=doc_template.id,
            name='Late batch',
        )
        db_session.add(lot)
        db_session.flush()

        def move(**overrides: Any) -> dict[str, Any]:
            row: dict[str, Any] = {
                'id': uuid.uuid4(),
                'organization_id': original.organization_id,
                'product_template_id': doc_template.id,
                'quantity': Decimal('1'),
                'state': 'done',
                'reference_type': StockMoveReferenceType.DOCUMENT.value,
                'reference_id': document_id,
                'created_at': landed_at + timedelta(hours=1),
                'updated_at': landed_at + timedelta(hours=1),
            }
            row.update(overrides)
            return row

        # One group of batches landing after the receipt's own group, one row
        # per batch: one more movement than the page the check used to read.
        db_session.execute(
            insert(StockMove),
            [
                move(lot_id=lot.id, to_location_id=doc_target_location.id)
                for _ in range(5000)
            ],
        )
        # The receipt's own goods, still without a batch, are issued away.
        db_session.execute(
            insert(StockMove),
            [
                move(
                    from_location_id=doc_target_location.id,
                    to_location_id=doc_source_location.id,
                    reference_type=None,
                    reference_id=None,
                    created_at=landed_at + timedelta(hours=2),
                )
            ],
        )
        db_session.commit()

        undone = client.post(
            f'/api/v1/warehouse/documents/{posted["id"]}/undo', headers=doc_auth_headers
        )

        assert undone.status_code == status.HTTP_400_BAD_REQUEST, undone.text
        assert 'Correct' in undone.json()['detail']['message']
        db_session.expire_all()
        assert (
            db_session.scalars(
                select(Document).where(Document.corrects_document_id == document_id)
            ).all()
            == []
        )
