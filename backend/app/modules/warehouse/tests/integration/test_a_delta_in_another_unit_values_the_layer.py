"""A signed delta written in another unit values its layer in the stock unit.

A correction and an adjustment take their quantity in whatever unit the line
was written in and their price per that unit; the cost layer they open is kept
in the product's stock unit. The receipt restated the price before it posted,
the two signed-delta doors did not: taking back 500 g of a product kept in
kilograms took the right stock off the shelf and wrote a layer 1000 times too
cheap, and a positive adjustment did the same the other way round.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation

pytestmark = pytest.mark.integration

DOCUMENTS_URL = '/api/v1/warehouse/documents'


def _kilogram_card(
    h: ModuleTestHelper, org: Organization, name: str
) -> ProductTemplate:
    """A product kept in kilograms, the unit the shelf and the layer speak."""
    return h.create_template(org, name=name, uom_id=h.get_uom('kg').id)


def _receive(
    client: TestClient,
    headers: dict[str, str],
    *,
    partner_id: Any,
    location_id: Any,
    template_id: Any,
    quantity: str,
    unit: Any,
    price: str,
) -> dict[str, Any]:
    """One receipt in grams, confirmed and completed."""
    created = client.post(
        DOCUMENTS_URL,
        headers=headers,
        json={
            'type': 'IN',
            'partner_id': str(partner_id),
            'target_location_id': str(location_id),
            'lines': [
                {
                    'product_template_id': str(template_id),
                    'expected_quantity': quantity,
                    'uom_id': str(unit),
                    'unit_price': price,
                }
            ],
        },
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    doc_id = created.json()['id']
    confirmed = client.patch(f'{DOCUMENTS_URL}/{doc_id}/confirm', headers=headers)
    assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
    completed = client.patch(
        f'{DOCUMENTS_URL}/{doc_id}/complete',
        headers=headers,
        json={'complete_as_planned': True},
    )
    assert completed.status_code == status.HTTP_200_OK, completed.text
    return cast(dict[str, Any], completed.json())


def _layer_of(db_session: Session, line_id: str) -> StockValuationLayer:
    """The cost layer the door opened for this line."""
    db_session.expire_all()
    return db_session.scalars(
        select(StockValuationLayer).where(
            StockValuationLayer.document_line_id == line_id,
            StockValuationLayer.direction == 'IN',
        )
    ).one()


class TestACorrectionValuesTheStockUnit:
    def test_a_correction_in_grams_values_a_kilogram_layer(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        h: ModuleTestHelper,
        db_session: Session,
    ) -> None:
        """500 g more at 0.02 a gram is half a kilogram worth 10.00, not 0.01."""
        card = _kilogram_card(h, doc_org, 'Weighed Correction Product')
        original = _receive(
            client,
            doc_auth_headers,
            partner_id=doc_partner.id,
            location_id=doc_target_location.id,
            template_id=card.id,
            quantity='1000',
            unit=h.get_uom('g').id,
            price='0.02',
        )
        created = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': original['id'],
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [
                    {
                        'original_line_number': original['lines'][0]['line_number'],
                        'quantity_delta': '500',
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        correction_id = created.json()['id']
        correction_line_id = created.json()['lines'][0]['id']
        confirmed = client.patch(
            f'{DOCUMENTS_URL}/{correction_id}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        completed = client.patch(
            f'{DOCUMENTS_URL}/{correction_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text

        layer = _layer_of(db_session, correction_line_id)
        assert layer.quantity == Decimal('0.5'), 'half a kilogram came back'
        assert layer.unit_cost == Decimal('20'), (
            'the layer keeps the price per kilogram, not per gram'
        )
        assert layer.total_value == Decimal('10.00'), (
            'five hundred grams at two grosz is ten zloty, not one'
        )


class TestAnAdjustmentValuesTheStockUnit:
    def test_an_adjustment_in_grams_values_a_kilogram_layer(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_org: Organization,
        doc_target_location: StorageLocation,
        h: ModuleTestHelper,
        db_session: Session,
    ) -> None:
        """500 g counted in at 0.02 a gram is half a kilogram worth 10.00."""
        card = _kilogram_card(h, doc_org, 'Counted Adjustment Product')
        record = client.post(
            '/api/v1/items',
            headers=doc_auth_headers,
            json={
                'name': card.name,
                'template_id': str(card.id),
                'location_id': str(doc_target_location.id),
                'quantity': '0',
            },
        )
        assert record.status_code == status.HTTP_201_CREATED, record.text
        created = client.post(
            DOCUMENTS_URL,
            headers=doc_auth_headers,
            json={
                'type': 'ADJUSTMENT',
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': record.json()['id'],
                        'product_template_id': str(card.id),
                        'expected_quantity': '500',
                        'uom_id': str(h.get_uom('g').id),
                        'unit_price': '0.02',
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc_id = created.json()['id']
        line_id = created.json()['lines'][0]['id']
        confirmed = client.patch(
            f'{DOCUMENTS_URL}/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        completed = client.patch(
            f'{DOCUMENTS_URL}/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert completed.status_code == status.HTTP_200_OK, completed.text

        layer = _layer_of(db_session, line_id)
        assert layer.quantity == Decimal('0.5'), (
            'the count reached the shelf in kilograms'
        )
        assert layer.unit_cost == Decimal('20'), (
            'the layer keeps the price per kilogram, not per gram'
        )
        assert layer.total_value == Decimal('10.00'), (
            'five hundred grams at two grosz is ten zloty, not one'
        )
