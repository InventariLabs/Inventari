"""A correction and a return undo one delivery, once, at its own price.

Two things were missing. Each restatement was measured against the original
line on its own, so a delivery of ten accepted a correction of minus ten and
then accepted a second one; six returned and six corrected away took twelve
off a line that received ten. And when the goods went back, the books drained
whatever layer was oldest instead of the delivery being corrected — so
sending back the expensive pallet took the cheap one off the books and left
the expensive one standing on them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation


def _receive(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: UUID,
    location_id: UUID,
    template_id: UUID,
    quantity: str,
    unit_price: str | None = None,
) -> str:
    line: dict[str, Any] = {
        'product_template_id': str(template_id),
        'expected_quantity': quantity,
    }
    if unit_price is not None:
        line['unit_price'] = unit_price
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
    assert (
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
        ).status_code
        == status.HTTP_200_OK
    )
    done = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert done.status_code == status.HTTP_200_OK, done.text
    return doc_id


def _ask_to_correct(
    client: TestClient,
    headers: dict[str, str],
    *,
    document_id: str,
    delta: str,
    line_number: int = 1,
) -> Any:
    """Only ask. The refusal under test belongs to the request, not to stock.

    Whether a restatement is too big is a question about the line's history,
    and the answer has to come back before the document exists. The executor
    refuses to take a record below zero, which catches the same mistake in
    the one case where there is nothing else on the shelf — and lets it
    through whenever there is.
    """
    return client.post(
        '/api/v1/warehouse/corrections',
        headers=headers,
        json={
            'corrects_document_id': document_id,
            'reason_code': 'DATA_ENTRY_ERROR',
            'lines': [{'original_line_number': line_number, 'quantity_delta': delta}],
        },
    )


def _ask_to_return(
    client: TestClient,
    headers: dict[str, str],
    *,
    document_id: str,
    quantity: str,
    line_number: int = 1,
) -> Any:
    return client.post(
        f'/api/v1/warehouse/documents/{document_id}/return',
        headers=headers,
        json={
            'reason_code': 'DAMAGED',
            'lines': [
                {'original_line_number': line_number, 'return_quantity': quantity}
            ],
        },
    )


def _execute(client: TestClient, headers: dict[str, str], resp: Any) -> tuple[int, str]:
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    if confirm.status_code != status.HTTP_200_OK:
        return confirm.status_code, confirm.text
    done = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    return done.status_code, done.text


def _correct(
    client: TestClient,
    headers: dict[str, str],
    *,
    document_id: str,
    delta: str,
    line_number: int = 1,
) -> tuple[int, str]:
    return _execute(
        client,
        headers,
        _ask_to_correct(
            client,
            headers,
            document_id=document_id,
            delta=delta,
            line_number=line_number,
        ),
    )


def _return(
    client: TestClient,
    headers: dict[str, str],
    *,
    document_id: str,
    quantity: str,
    line_number: int = 1,
) -> tuple[int, str]:
    return _execute(
        client,
        headers,
        _ask_to_return(
            client,
            headers,
            document_id=document_id,
            quantity=quantity,
            line_number=line_number,
        ),
    )


def _layers(
    db_session: Session, template_id: UUID, direction: str
) -> list[StockValuationLayer]:
    return list(
        db_session.scalars(
            select(StockValuationLayer)
            .where(
                StockValuationLayer.product_template_id == template_id,
                StockValuationLayer.direction == direction,
            )
            .order_by(StockValuationLayer.created_at.asc())
        ).all()
    )


@pytest.mark.integration
class TestOneDeliveryIsUndoneOnce:
    def test_a_second_correction_of_the_whole_line_is_refused(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        receipt = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            quantity='10',
        )
        # A second delivery of the same goods onto the same shelf, so the
        # record has stock behind it that does not belong to the line being
        # corrected. Without it the executor's own refusal to go below zero
        # hides the missing rule.
        _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            quantity='10',
        )
        code, body = _correct(
            client, doc_auth_headers, document_id=receipt, delta='-10'
        )
        assert code == status.HTTP_200_OK, body

        second = _ask_to_correct(
            client, doc_auth_headers, document_id=receipt, delta='-10'
        )
        assert second.status_code == status.HTTP_400_BAD_REQUEST, second.text

    def test_a_return_and_a_correction_share_one_line(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """Six back and six corrected away is twelve off a line that took ten."""
        receipt = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            quantity='10',
        )
        _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            quantity='10',
        )
        code, body = _return(
            client, doc_auth_headers, document_id=receipt, quantity='6'
        )
        assert code == status.HTTP_200_OK, body

        too_much = _ask_to_correct(
            client, doc_auth_headers, document_id=receipt, delta='-6'
        )
        assert too_much.status_code == status.HTTP_400_BAD_REQUEST, too_much.text

        # Four is what is left, and four goes through.
        code, body = _correct(client, doc_auth_headers, document_id=receipt, delta='-4')
        assert code == status.HTTP_200_OK, body

    def test_an_over_receipt_correction_makes_room_for_a_bigger_return(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """The control: the rule counts net, so it must count upwards too."""
        receipt = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            quantity='10',
        )
        code, body = _correct(client, doc_auth_headers, document_id=receipt, delta='5')
        assert code == status.HTTP_200_OK, body

        code, body = _return(
            client, doc_auth_headers, document_id=receipt, quantity='15'
        )
        assert code == status.HTTP_200_OK, body


@pytest.mark.integration
class TestGoodsGoBackAtTheirOwnPrice:
    def test_correcting_the_dear_delivery_takes_the_dear_layer(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_org: Organization,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """Ten at 1.00, then ten at 3.00; the second delivery is corrected away."""
        _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            quantity='10',
            unit_price='1.00',
        )
        dear = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=doc_template.id,
            quantity='10',
            unit_price='3.00',
        )

        code, body = _correct(client, doc_auth_headers, document_id=dear, delta='-10')
        assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        cheap_layer, dear_layer = _layers(db_session, doc_template.id, 'IN')
        assert cheap_layer.unit_cost == Decimal('1.0000')
        assert cheap_layer.remaining_qty == Decimal('10.000')
        assert dear_layer.unit_cost == Decimal('3.0000')
        assert dear_layer.remaining_qty == Decimal('0.000')

        out = _layers(db_session, doc_template.id, 'OUT')
        assert [layer.total_value for layer in out] == [Decimal('30.00')]

    def test_a_plain_dispatch_still_drains_the_oldest(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_source_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
        """The control: an ordinary sale names no delivery and stays FIFO."""
        from app.models.item import Item

        _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_source_location.id,
            template_id=doc_template.id,
            quantity='10',
            unit_price='1.00',
        )
        _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_source_location.id,
            template_id=doc_template.id,
            quantity='10',
            unit_price='3.00',
        )
        db_session.expire_all()
        item = db_session.scalars(
            select(Item).where(Item.template_id == doc_template.id)
        ).first()
        assert item is not None

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'lines': [
                    {
                        'item_id': str(item.id),
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': '10',
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        doc_id = cast(str, resp.json()['id'])
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert done.status_code == status.HTTP_200_OK, done.text

        db_session.expire_all()
        cheap_layer, dear_layer = _layers(db_session, doc_template.id, 'IN')
        assert cheap_layer.remaining_qty == Decimal('0.000')
        assert dear_layer.remaining_qty == Decimal('10.000')
        out = _layers(db_session, doc_template.id, 'OUT')
        assert [layer.total_value for layer in out] == [Decimal('10.00')]
