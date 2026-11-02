"""A picking session over a zone dispatch has one line per shelf, in the walk.

A dispatch from a zone is split at confirmation into one line per shelf the
draw reaches, each pinned to its shelf. Picking opens one pick line per
document line, so the session gets the same shelves: each pick line stands on
the shelf its share is drawn from, and the lines come out in the order the
warehouse is walked, not in the order the stock was drawn.
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

from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse.models import WmsPickLine
from app.modules.warehouse.tests.integration._records import (
    sow as _sow,
)


def _shelf(
    db_session: Session,
    org: Organization,
    user: User,
    parent: StorageLocation,
    *,
    name: str,
    code: str,
    sequence: int,
) -> StorageLocation:
    shelf = StorageLocation(
        organization_id=org.id,
        name=name,
        short_code=code,
        sequence=sequence,
        parent_id=parent.id,
        storage_type_id=parent.storage_type_id,
        created_by=user.id,
    )
    db_session.add(shelf)
    db_session.flush()
    return shelf


@pytest.mark.integration
class TestAZoneDispatchIsPickedOnePerShelf:
    def test_the_session_has_a_line_per_shelf_in_walk_order(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        async_engine_fixture: AsyncEngine,
        doc_org: Organization,
        doc_user: User,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
    ) -> None:
        """The older stock is on the far shelf, drawn first; the walk reaches the near one first."""
        doc_template.removal_strategy = 'FIFO'
        db_session.commit()
        far = _shelf(
            db_session,
            doc_org,
            doc_user,
            doc_source_location,
            name='Far bin',
            code='C-07',
            sequence=2,
        )
        near = _shelf(
            db_session,
            doc_org,
            doc_user,
            doc_source_location,
            name='Near bin',
            code='A-01',
            sequence=1,
        )
        oldest = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            far.id,
            '6',
            backdate_days=30,
        )
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            near.id,
            '5',
        )

        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(oldest.id),
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 7,
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = cast(str, created.json()['id'])
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text

        started = client.post(
            f'/api/v1/warehouse/documents/{doc_id}/picking/start',
            headers=doc_auth_headers,
        )
        assert started.status_code == status.HTTP_201_CREATED, started.text
        session_id = started.json()['id']

        db_session.expire_all()
        lines = db_session.scalars(
            select(WmsPickLine)
            .where(WmsPickLine.session_id == session_id)
            .order_by(WmsPickLine.pick_order)
        ).all()
        assert [(line.location_id, line.expected_quantity) for line in lines] == [
            (near.id, Decimal('1')),
            (far.id, Decimal('6')),
        ]
