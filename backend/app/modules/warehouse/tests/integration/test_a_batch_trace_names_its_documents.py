"""A batch's trace names the receipt it came on and the delivery it left on.

Core's trace finds the movements of a batch; the documents they were posted
under are this module's, so the module names them — the number and the
partner, as the document recorded the partner when it was confirmed.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.models.user import User


def _post(client: TestClient, headers: dict[str, str], body: dict[str, object]) -> str:
    resp = client.post('/api/v1/warehouse/documents', headers=headers, json=body)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    doc_id = cast(str, resp.json()['id'])
    for step in ('confirm', 'complete'):
        done = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/{step}',
            headers=headers,
            json={'complete_as_planned': True} if step == 'complete' else None,
        )
        assert done.status_code == status.HTTP_200_OK, done.text
    return doc_id


def test_the_trace_names_the_supplier_and_the_customer(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    doc_template: ProductTemplate,
    doc_org: Organization,
    doc_user: User,
    db_session: Session,
) -> None:
    customer = ModuleTestHelper(db_session).create_partner(
        doc_org, doc_user, name='Corner Shop'
    )
    customer.address = {'street': '2 High St', 'city': 'York'}
    db_session.commit()

    receipt = _post(
        client,
        doc_auth_headers,
        {
            'type': 'IN',
            'partner_id': str(doc_partner.id),
            'target_location_id': str(doc_target_location.id),
            'lines': [
                {
                    'product_template_id': str(doc_template.id),
                    'expected_quantity': 10,
                    'batch_number': 'LOT-TRACE',
                }
            ],
        },
    )
    lot = db_session.scalars(
        select(StockLot).where(
            StockLot.organization_id == doc_org.id, StockLot.name == 'LOT-TRACE'
        )
    ).one()
    record = db_session.scalars(select(Item).where(Item.lot_id == lot.id)).one()
    delivery = _post(
        client,
        doc_auth_headers,
        {
            'type': 'OUT',
            'partner_id': str(customer.id),
            'source_location_id': str(doc_target_location.id),
            'lines': [
                {
                    'item_id': str(record.id),
                    'product_template_id': str(doc_template.id),
                    'expected_quantity': 4,
                    'batch_number': 'LOT-TRACE',
                }
            ],
        },
    )

    resp = client.get(f'/api/v1/stock-lots/{lot.id}/trace', headers=doc_auth_headers)

    assert resp.status_code == status.HTTP_200_OK, resp.text
    [batch] = resp.json()['lots']
    [came_in] = batch['received']
    [went_out] = batch['sent']
    numbers = {
        doc_id: client.get(
            f'/api/v1/warehouse/documents/{doc_id}', headers=doc_auth_headers
        ).json()['number']
        for doc_id in (receipt, delivery)
    }
    assert came_in['reference_id'] == receipt
    assert came_in['label'] == numbers[receipt]
    assert came_in['partner_name'] == 'Acme Supplies'
    assert Decimal(came_in['quantity']) == Decimal('10')
    assert went_out['reference_id'] == delivery
    assert went_out['label'] == numbers[delivery]
    assert went_out['partner_name'] == 'Corner Shop'
    assert went_out['partner_address'] == '2 High St, York'
    assert Decimal(went_out['quantity']) == Decimal('4')
