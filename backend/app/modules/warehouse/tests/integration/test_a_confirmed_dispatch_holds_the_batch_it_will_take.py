"""Confirming a dispatch holds the batch the dispatch will draw.

A line without a named batch draws by the product's removal strategy when it
is completed. The hold made at confirmation used to plan by FIFO whatever the
product said, so a first-expired-first-out product had the oldest-received
batch promised to the dispatch while the dispatch itself took the one that
expires first: the promise covered the wrong stock, and the batch that was
actually taken stood unprotected for another document in between.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.stock_lot import StockLot
from app.models.stock_reservation import StockReservation
from app.models.storage_location import StorageLocation
from app.modules.warehouse.tests.integration._records import shelf_record, sow

_TODAY = datetime.now(UTC).date()


def _lot(
    db: Session, org_id: UUID, template_id: UUID, name: str, months: int
) -> StockLot:
    lot = StockLot(
        organization_id=org_id,
        product_template_id=template_id,
        name=name,
        use_by_date=_TODAY + timedelta(days=30 * months),
    )
    db.add(lot)
    db.flush()
    return lot


@pytest.mark.integration
@pytest.mark.parametrize(
    ('strategy', 'held'), [('FEFO', 'EXPIRES-SOON'), ('FIFO', 'RECEIVED-FIRST')]
)
def test_the_hold_follows_the_products_removal_strategy(
    strategy: str,
    held: str,
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_source_location: StorageLocation,
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    db_session: Session,
    async_engine_fixture: AsyncEngine,
    doc_org: Organization,
) -> None:
    template = ModuleTestHelper(db_session).create_template(
        doc_org, name=f'Strategy {uuid4().hex[:6]}'
    )
    template.removal_strategy = strategy
    db_session.commit()
    db_session.refresh(template)

    # Received first, expires last - then received second, expires first.
    first = _lot(db_session, doc_org.id, template.id, 'RECEIVED-FIRST', 12)
    second = _lot(db_session, doc_org.id, template.id, 'EXPIRES-SOON', 3)
    for lot in (first, second):
        sow(
            db_session,
            async_engine_fixture,
            doc_org.id,
            template,
            doc_source_location.id,
            Decimal('5'),
            lot_id=lot.id,
        )
    record = shelf_record(db_session, doc_org.id, template.id, doc_source_location.id)
    db_session.commit()

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
                    'item_id': str(record.id),
                    'product_template_id': str(template.id),
                    'expected_quantity': 3,
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = UUID(created.json()['id'])
    confirmed = client.patch(
        f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
    )
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text

    db_session.expire_all()
    rows = db_session.scalars(
        select(StockReservation).where(StockReservation.document_id == doc_id)
    ).all()
    by_name = {'RECEIVED-FIRST': first.id, 'EXPIRES-SOON': second.id}
    assert {row.lot_id for row in rows} == {by_name[held]}
