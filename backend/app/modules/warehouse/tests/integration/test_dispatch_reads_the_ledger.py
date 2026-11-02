"""Confirmation and execution ask the same question of the same source.

Confirming an outbound document reserves against the shelf's quantity per
(template, location) — then the quant table's, now the records' view that
sums them. Execution used to check ``Item.quantity`` of the line's one
record — that same figure, split across however many records stand on the
shelf. One product on one shelf in two records is an
ordinary situation: two batches, or two deliveries that arrived apart. The
two numbers then differed every time, and a document could pass confirmation,
gather a reservation on the whole shelf, and break on its last step quoting a
figure matching neither the shelf nor the reservation.

The way out the warehouse was left with wrote down an untruth: dispatch what
the single record admits to and mark the rest SHORTAGE — a shortage of goods
that were on the shelf the whole time.
"""

from __future__ import annotations

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


def _receive(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: UUID,
    target_location_id: UUID,
    template_id: UUID,
    quantity: int,
    expiry_date: str | None = None,
) -> None:
    line: dict[str, object] = {
        'product_template_id': str(template_id),
        'expected_quantity': quantity,
    }
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
    assert (
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
        ).status_code
        == status.HTTP_200_OK
    )
    complete = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert complete.status_code == status.HTTP_200_OK, complete.text


def _dispatch(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: UUID,
    source_location_id: UUID,
    item_id: UUID,
    template_id: UUID,
    quantity: int,
) -> tuple[int, str]:
    resp = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'OUT',
            'partner_id': str(partner_id),
            'source_location_id': str(source_location_id),
            'lines': [
                {
                    'item_id': str(item_id),
                    'product_template_id': str(template_id),
                    'expected_quantity': quantity,
                }
            ],
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    confirm = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=headers
    )
    if confirm.status_code != status.HTTP_200_OK:
        return confirm.status_code, confirm.text
    complete = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    return complete.status_code, complete.text


def _rows(db_session: Session, org_id: UUID, template_id: UUID) -> list[Item]:
    return list(
        db_session.scalars(
            select(Item)
            .where(
                Item.organization_id == org_id,
                Item.template_id == template_id,
                Item.is_deleted.is_(False),
            )
            .order_by(Item.created_at.asc())
        ).all()
    )


@pytest.mark.integration
class TestDispatchReadsTheLedger:
    def test_dispatch_of_stock_split_across_two_records_goes_through(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        h: ModuleTestHelper,
    ) -> None:
        """Ten in one record and two in another are twelve on the shelf."""
        template = h.create_template(doc_org, name='Split Bacon', barcode=None)
        # Two deliveries of different batches: the expiry date is the rotation
        # cache for non-lot stock, so they stay two records on one shelf.
        _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_source_location.id,
            template_id=template.id,
            quantity=10,
            expiry_date='2026-06-30',
        )
        _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_source_location.id,
            template_id=template.id,
            quantity=2,
            expiry_date='2026-12-31',
        )
        db_session.expire_all()
        rows = _rows(db_session, doc_org.id, template.id)
        assert [row.quantity for row in rows] == [Decimal('10'), Decimal('2')]

        code, body = _dispatch(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            source_location_id=doc_source_location.id,
            item_id=rows[0].id,
            template_id=template.id,
            quantity=12,
        )
        assert code == status.HTTP_200_OK, body

        db_session.expire_all()
        # Both records are drawn down, earliest expiry first, so neither is
        # left claiming stock that has gone.
        assert [row.quantity for row in _rows(db_session, doc_org.id, template.id)] == [
            Decimal('0'),
            Decimal('0'),
        ]

    def test_refusal_quotes_the_shelf_not_one_record(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        h: ModuleTestHelper,
    ) -> None:
        """Asking for more than is there is refused with the shelf's figure."""
        template = h.create_template(doc_org, name='Short Bacon', barcode=None)
        _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            target_location_id=doc_source_location.id,
            template_id=template.id,
            quantity=3,
        )
        db_session.expire_all()
        rows = _rows(db_session, doc_org.id, template.id)

        code, body = _dispatch(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            source_location_id=doc_source_location.id,
            item_id=rows[0].id,
            template_id=template.id,
            quantity=5,
        )
        assert code != status.HTTP_200_OK
        # Refused at confirmation, where the reservation is taken, and the
        # figure is the ledger's: two of the five asked for could not be
        # covered, so three are on the shelf. Nothing quotes the quantity of
        # whichever record the line happened to name.
        assert 'could not be reserved' in body
        # The shelf's figure, in the reader's numbers — the database's own
        # scale ("2.000 of 5.000") was the quantity column's spelling, not
        # the one every screen uses.
        assert '2 of 5' in body
