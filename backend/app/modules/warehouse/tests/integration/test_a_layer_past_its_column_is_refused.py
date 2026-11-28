"""A receipt restated into a smaller stock unit refuses a cost past its column.

A line priced per gram on a product kept in kilograms restates the price per
kilogram when its layer is posted. A price inside the line's own range can
outgrow the cost layer's ``numeric(12, 4)`` on that restatement, and the driver
answered with a server error after the record had taken the goods. The layer
now refuses it with the product and the bound named.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration

DOCUMENTS_URL = '/api/v1/warehouse/documents'


def test_a_restated_receipt_price_past_the_layer_column_is_refused(
    client: TestClient,
    doc_auth_headers: dict[str, str],
    doc_org: Organization,
    doc_target_location: StorageLocation,
    doc_partner: Partner,
    h: ModuleTestHelper,
    db_session: Session,
) -> None:
    """One gram at 99,999,999.99 a gram is nearly a hundred billion a kilogram."""
    card = h.create_template(
        doc_org, name='A Gram Worth Millions', uom_id=h.get_uom('kg').id
    )
    created = client.post(
        DOCUMENTS_URL,
        headers=doc_auth_headers,
        json={
            'type': 'IN',
            'partner_id': str(doc_partner.id),
            'target_location_id': str(doc_target_location.id),
            'lines': [
                {
                    'product_template_id': str(card.id),
                    'expected_quantity': '1',
                    'uom_id': str(h.get_uom('g').id),
                    'unit_price': '99999999.99',
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = created.json()['id']
    confirmed = client.patch(
        f'{DOCUMENTS_URL}/{doc_id}/confirm', headers=doc_auth_headers
    )
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text

    completed = client.patch(
        f'{DOCUMENTS_URL}/{doc_id}/complete',
        headers=doc_auth_headers,
        json={'complete_as_planned': True},
    )

    assert completed.status_code == status.HTTP_400_BAD_REQUEST, completed.text
    detail = completed.json()['detail']
    assert detail['code'] == 'STOCK_LAYER_UNIT_COST_ABOVE_CEILING'
    assert '99999999.9999' in detail['message'], detail['message']
    assert card.name in detail['message'], detail['message']
    db_session.expire_all()
    layers: list[Any] = list(
        db_session.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == card.id
            )
        ).all()
    )
    assert layers == [], 'nothing was written past the column'
