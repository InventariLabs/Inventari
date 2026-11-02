"""A document issues exactly what it promised, whose goods included.

The reservation holds stock for a document across every owner on the
shelf — a consignor's goods standing beside the organization's own are
stock the shelf holds, and the promise at confirmation counts them. The
draw at completion used to answer a different question: it planned from
the records with the owner filter closed to the organization's own, so a
document that confirmed against eight (four ours, four the consignor's)
released its reservation and then refused with NOT_ENOUGH — the promise
and the issue disagreed about whose goods may serve the line.

The one rule that settles it (recorded in ``docs/subsystems/STOCK.md``):
the owner comes from the document line.
Every door answers by it — the reservation holds what the line may draw,
the draw takes what the line may hold, the movement says whose goods
left. A line that names no owner does not restrict, which is what the
reservation has promised all along.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from tests.integration._shelf import (
    put_on_shelf,
    run_in_async_session,
    shelf_keeper,
)


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


@pytest.mark.integration
class TestADocumentIssuesWhatItPromised:
    def test_eight_promised_are_eight_issued_whose_goods_included(
        self,
        client: TestClient,
        db_session: Session,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        h: ModuleTestHelper,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        """Four of ours and four of the consignor's leave the shelf.

        Falls on the old draw in two places at once: completion answered
        NOT_ENOUGH for stock the reservation had just promised, and the
        movements off the shelf did not say whose goods left.
        """
        template = h.create_template(doc_org, name='Promised Oats', barcode=None)
        db_session.commit()

        async def _stock(session: AsyncSession) -> tuple[UUID, UUID, UUID]:
            keeper = await shelf_keeper(session, doc_org.id)
            consignor = Partner(
                organization_id=doc_org.id, name='The Consignor', type='SUPPLIER'
            )
            session.add(consignor)
            await session.flush()
            ours = await put_on_shelf(
                session, keeper, template, doc_source_location.id, Decimal('4')
            )
            theirs = await put_on_shelf(
                session,
                keeper,
                template,
                doc_source_location.id,
                Decimal('6'),
                owner_id=consignor.id,
            )
            return ours.id, theirs.id, consignor.id

        own_id, consignor_id, consignor_partner_id = run_in_async_session(
            async_engine_fixture, _stock
        )
        db_session.expire_all()

        code, body = _dispatch(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            source_location_id=doc_source_location.id,
            item_id=own_id,
            template_id=template.id,
            quantity=8,
        )
        assert code == status.HTTP_200_OK, body

        # The shelf gave up exactly the eight: the own record is empty and
        # the consignor's keeps two of its six.
        db_session.expire_all()
        own = db_session.get(Item, own_id)
        consignor = db_session.get(Item, consignor_id)
        assert own is not None and consignor is not None
        assert own.quantity == Decimal('0')
        assert consignor.quantity == Decimal('2')

        # And the ledger says whose goods left: one movement for the
        # organization's own four, one for the consignor's four.
        movements = list(
            db_session.scalars(
                select(StockMove).where(
                    StockMove.organization_id == doc_org.id,
                    StockMove.product_template_id == template.id,
                    StockMove.to_location_id.is_(None),
                )
            )
        )
        by_owner = {
            (move.owner_id, move.quantity) for move in movements if move.quantity > 0
        }
        assert by_owner == {(None, Decimal('4')), (consignor_partner_id, Decimal('4'))}
