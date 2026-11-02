"""A transfer from a zone moves the record its line names, from that record's shelf.

A transfer moves exactly the record its line names, so a zone source does not
split it: confirmation pins the line to the shelf the record stands on, and
completion takes the goods from that shelf. A record standing outside the zone
is refused at confirmation, as it always was.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.tests.integration._records import (
    shelf_quant as _shelf_quant,
)
from app.modules.warehouse.tests.integration._records import (
    sow as _sow,
)


def _shelf(
    db_session: Session,
    org: Organization,
    user: User,
    parent: StorageLocation,
    name: str,
) -> StorageLocation:
    shelf = StorageLocation(
        organization_id=org.id,
        name=name,
        parent_id=parent.id,
        storage_type_id=parent.storage_type_id,
        created_by=user.id,
    )
    db_session.add(shelf)
    db_session.flush()
    return shelf


def _transfer(
    client: TestClient,
    headers: dict[str, str],
    zone: StorageLocation,
    target: StorageLocation,
    record: Item,
    template: ProductTemplate,
    quantity: int,
) -> str:
    created = client.post(
        '/api/v1/warehouse/documents',
        headers=headers,
        json={
            'type': 'INT',
            'source_location_id': str(zone.id),
            'target_location_id': str(target.id),
            'lines': [
                {
                    'item_id': str(record.id),
                    'product_template_id': str(template.id),
                    'expected_quantity': quantity,
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    return cast(str, created.json()['id'])


@pytest.mark.integration
class TestATransferFromAZoneMovesTheRecordFromItsShelf:
    def test_the_transfer_takes_the_record_from_the_shelf_it_stands_on(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
    ) -> None:
        """Three of five leave Bin A1; the other shelf below the zone is untouched."""
        shelf_a = _shelf(db_session, doc_org, doc_user, doc_source_location, 'Bin A1')
        shelf_b = _shelf(db_session, doc_org, doc_user, doc_source_location, 'Bin B2')
        record = _sow(
            db_session, async_engine_fixture, doc_org, doc_template, shelf_a.id, '5'
        )
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_b.id, '4')

        doc_id = _transfer(
            client,
            doc_auth_headers,
            doc_source_location,
            doc_target_location,
            record,
            doc_template,
            3,
        )
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        lines = client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        ).json()['lines']
        assert [line['source_location_id'] for line in lines] == [str(shelf_a.id)]

        db_session.expire_all()
        assert (
            float(
                _shelf_quant(
                    db_session, doc_org.id, doc_template.id, shelf_a.id
                ).reserved_quantity
            )
            == 3.0
        )
        assert (
            float(
                _shelf_quant(
                    db_session, doc_org.id, doc_template.id, shelf_b.id
                ).reserved_quantity
            )
            == 0.0
        )

        completed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text

        db_session.expire_all()
        moves = db_session.scalars(
            select(StockMove).where(
                StockMove.organization_id == doc_org.id,
                StockMove.product_template_id == doc_template.id,
                StockMove.state == 'done',
                StockMove.from_location_id.in_([shelf_a.id, shelf_b.id]),
            )
        ).all()
        assert [
            (move.from_location_id, move.to_location_id, move.quantity)
            for move in moves
        ] == [
            (shelf_a.id, doc_target_location.id, Decimal('3')),
        ]
        assert (
            float(
                _shelf_quant(
                    db_session, doc_org.id, doc_template.id, shelf_b.id
                ).quantity
            )
            == 4.0
        )

    def test_a_record_outside_the_zone_is_refused_at_confirmation(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
    ) -> None:
        """The record stands in the target warehouse, not under the zone: the transfer stays a draft."""
        shelf_a = _shelf(db_session, doc_org, doc_user, doc_source_location, 'Bin A1')
        _sow(db_session, async_engine_fixture, doc_org, doc_template, shelf_a.id, '5')
        outside = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_target_location.id,
            '5',
        )

        doc_id = _transfer(
            client,
            doc_auth_headers,
            doc_source_location,
            doc_target_location,
            outside,
            doc_template,
            2,
        )
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == status.HTTP_400_BAD_REQUEST, confirmed.text
        assert (
            client.get(
                f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
            ).json()['status']
            == 'DRAFT'
        )
