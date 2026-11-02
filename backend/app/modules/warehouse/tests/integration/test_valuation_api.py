"""
Integration tests for AVCO Valuation API.

Tests verify:
- StockValuationLayer creation on receipts
- AVCO rate calculation on receipts
- Delivery uses current AVCO rate
- FIFO-like consumption of valuation layers
"""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation


def _rate(
    client: TestClient, headers: dict[str, str], template_id: Any
) -> Decimal | None:
    """This organization's AVCO rate, read the way a reader gets it.

    It used to be a cached column on `product_templates`, and a global template
    is one row every organization shares — so the number there belonged to
    whichever one had last taken a delivery. It is computed per organization
    now, from that organization's own layers.
    """
    response = client.get(
        f'/api/v1/items/product-templates/{template_id}', headers=headers
    )
    assert response.status_code == 200, response.text
    raw = response.json()['current_valuation_rate']
    return None if raw is None else Decimal(str(raw))


@pytest.mark.integration
class TestAVCOValuation:
    def test_creates_svl_record_on_receipt(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """Each receipt creates a StockValuationLayer."""
        from app.models.stock_valuation_layer import StockValuationLayer

        initial_count = (
            db_session.scalar(
                select(func.count(StockValuationLayer.id)).where(
                    StockValuationLayer.product_template_id == doc_template.id
                )
            )
            or 0
        )

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': '10',
                        'unit_price': '15.00',
                    }
                ],
            },
        )
        assert response.status_code == 201, f'Document creation failed: {response.text}'

        doc_id = response.json()['id']

        confirm_response = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )
        assert confirm_response.status_code == 200, (
            f'Confirmation failed: {confirm_response.text}'
        )

        complete_response = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete_response.status_code == 200, (
            f'Completion failed: {complete_response.text}'
        )

        db_session.expire_all()
        final_count = (
            db_session.scalar(
                select(func.count(StockValuationLayer.id)).where(
                    StockValuationLayer.product_template_id == doc_template.id
                )
            )
            or 0
        )

        assert final_count > initial_count

    def test_first_receipt_sets_valuation_rate(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """First receipt makes the delivery price this organization's rate."""
        db_session.refresh(doc_template)

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': '10',
                        'unit_price': '15.00',
                    }
                ],
            },
        )
        assert response.status_code == 201, f'Document creation failed: {response.text}'

        doc_id = response.json()['id']

        confirm_response = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )
        assert confirm_response.status_code == 200, (
            f'Confirmation failed: {confirm_response.text}'
        )

        complete_response = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete_response.status_code == 200, (
            f'Completion failed: {complete_response.text}'
        )

        current_rate = _rate(client, doc_auth_headers, doc_template.id)
        assert current_rate is not None
        assert current_rate == Decimal('15.00')

    def test_delivery_uses_current_avco(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """Delivery does not change AVCO — uses current rate."""

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': '10',
                        'unit_price': '16.00',
                    }
                ],
            },
        )
        assert response.status_code == 201, (
            f'IN document creation failed: {response.text}'
        )

        db_session.expire_all()

        initial_rate = _rate(client, doc_auth_headers, doc_template.id)

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': '3',
                    }
                ],
            },
        )
        assert response.status_code == 201, (
            f'OUT document creation failed: {response.text}'
        )

        db_session.expire_all()

        final_rate = _rate(client, doc_auth_headers, doc_template.id)

        assert final_rate == initial_rate

    def test_second_receipt_updates_avco(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """Second receipt at different price triggers AVCO recalculation.

        Setup: 10 pcs at 15 (value: 150)
        Action: Receive 5 pcs at 18 (value: 90)
        Expected: AVCO = (150 + 90) / 15 = 16.00
        """

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': '10',
                        'unit_price': '15.00',
                    }
                ],
            },
        )
        assert response.status_code == 201, (
            f'First document creation failed: {response.text}'
        )

        doc_id = response.json()['id']

        confirm_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm_resp.status_code == 200, (
            f'First confirm failed: {confirm_resp.text}'
        )
        complete_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete_resp.status_code == 200, (
            f'First complete failed: {complete_resp.text}'
        )

        db_session.expire_all()

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': '5',
                        'unit_price': '18.00',
                    }
                ],
            },
        )
        assert response.status_code == 201, (
            f'Second document creation failed: {response.text}'
        )

        doc_id2 = response.json()['id']

        confirm_resp2 = client.patch(
            f'/api/v1/warehouse/documents/{doc_id2}/confirm', headers=doc_auth_headers
        )
        assert confirm_resp2.status_code == 200, (
            f'Second confirm failed: {confirm_resp2.text}'
        )
        complete_resp2 = client.patch(
            f'/api/v1/warehouse/documents/{doc_id2}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete_resp2.status_code == 200, (
            f'Second complete failed: {complete_resp2.text}'
        )

        assert _rate(client, doc_auth_headers, doc_template.id) == Decimal('16.00')

    def test_zero_cost_receipt_does_not_change_rate(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """Receipt without price does not change AVCO."""

        doc = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': '10',
                        'unit_price': '15.00',
                    }
                ],
            },
        )
        assert doc.status_code == 201, f'First document creation failed: {doc.text}'

        doc_id = doc.json()['id']
        confirm_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm_resp.status_code == 200, (
            f'First confirm failed: {confirm_resp.text}'
        )
        complete_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete_resp.status_code == 200, (
            f'First complete failed: {complete_resp.text}'
        )

        initial_rate = _rate(client, doc_auth_headers, doc_template.id)

        doc2 = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': '5',
                    }
                ],
            },
        )
        assert doc2.status_code == 201, f'Second document creation failed: {doc2.text}'

        doc_id2 = doc2.json()['id']
        confirm_resp2 = client.patch(
            f'/api/v1/warehouse/documents/{doc_id2}/confirm', headers=doc_auth_headers
        )
        assert confirm_resp2.status_code == 200, (
            f'Second confirm failed: {confirm_resp2.text}'
        )
        complete_resp2 = client.patch(
            f'/api/v1/warehouse/documents/{doc_id2}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete_resp2.status_code == 200, (
            f'Second complete failed: {complete_resp2.text}'
        )

        assert _rate(client, doc_auth_headers, doc_template.id) == initial_rate

    def test_delivery_decreases_remaining_qty(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_partner: Partner,
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """Delivery decreases remaining_qty on oldest SVL layer (FIFO)."""
        from app.models.item import Item
        from app.models.stock_valuation_layer import StockValuationLayer

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': '10',
                        'unit_price': '15.00',
                    }
                ],
            },
        )
        assert response.status_code == 201, (
            f'IN document creation failed: {response.text}'
        )

        doc_id = response.json()['id']
        confirm_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm', headers=doc_auth_headers
        )
        assert confirm_resp.status_code == 200, (
            f'IN confirm failed: {confirm_resp.text}'
        )
        complete_resp = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete_resp.status_code == 200, (
            f'IN complete failed: {complete_resp.text}'
        )

        db_session.expire_all()

        created_item = db_session.scalars(
            select(Item).where(
                Item.template_id == doc_template.id,
                Item.storage_location_id == doc_target_location.id,
            )
        ).first()
        assert created_item is not None, 'No item created from IN document'

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(created_item.id),
                        'expected_quantity': '3',
                    }
                ],
            },
        )
        assert response.status_code == 201, (
            f'OUT document creation failed: {response.text}'
        )

        doc_id2 = response.json()['id']
        confirm_resp2 = client.patch(
            f'/api/v1/warehouse/documents/{doc_id2}/confirm', headers=doc_auth_headers
        )
        assert confirm_resp2.status_code == 200, (
            f'OUT confirm failed: {confirm_resp2.text}'
        )
        complete_resp2 = client.patch(
            f'/api/v1/warehouse/documents/{doc_id2}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete_resp2.status_code == 200, (
            f'OUT complete failed: {complete_resp2.text}'
        )

        db_session.expire_all()
        layer = db_session.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == doc_template.id,
                StockValuationLayer.remaining_qty > 0,
            )
        ).first()
        assert layer is not None
        assert layer.remaining_qty == Decimal('7')

    def test_scrap_consumes_svl_layer(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """SCRAP must consume SVL remaining_qty (FIFO) like a delivery."""
        from app.models.item import Item
        from app.models.stock_valuation_layer import StockValuationLayer

        # Receive 10 pcs @ 15 → SVL layer qty=10, remaining=10
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': '10',
                        'unit_price': '15.00',
                    }
                ],
            },
        )
        assert resp.status_code == 201, resp.text
        in_doc_id = resp.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{in_doc_id}/confirm', headers=doc_auth_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{in_doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        db_session.expire_all()
        created_item = db_session.scalars(
            select(Item).where(
                Item.template_id == doc_template.id,
                Item.storage_location_id == doc_target_location.id,
            )
        ).first()
        assert created_item is not None

        # Scrap 3 pcs
        scrap_resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'SCRAP',
                'reason_code': 'DAMAGED',
                'lines': [
                    {
                        'item_id': str(created_item.id),
                        'expected_quantity': '3',
                    }
                ],
            },
        )
        assert scrap_resp.status_code == 201, scrap_resp.text
        scrap_doc_id = scrap_resp.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{scrap_doc_id}/confirm',
            headers=doc_auth_headers,
        )
        scrap_complete = client.patch(
            f'/api/v1/warehouse/documents/{scrap_doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert scrap_complete.status_code == 200, scrap_complete.text

        db_session.expire_all()
        layer = db_session.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == doc_template.id,
                StockValuationLayer.remaining_qty > 0,
            )
        ).first()
        assert layer is not None
        assert layer.remaining_qty == Decimal('7')

    def test_correction_negative_delta_consumes_svl(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        db_session: Session,
        doc_org: Organization,
        doc_partner: Partner,
        doc_target_location: StorageLocation,
        doc_template: ProductTemplate,
    ) -> None:
        """Negative correction delta consumes SVL (delivery), not adds receipt layer."""
        from app.models.stock_valuation_layer import StockValuationLayer

        # Receive 10 pcs @ 15 → SVL layer qty=10, remaining=10
        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': '10',
                        'unit_price': '15.00',
                    }
                ],
            },
        )
        assert resp.status_code == 201, resp.text
        in_doc_id = resp.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{in_doc_id}/confirm', headers=doc_auth_headers
        )
        client.patch(
            f'/api/v1/warehouse/documents/{in_doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        db_session.expire_all()
        layers_before = db_session.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == doc_template.id
            )
        ).all()
        assert len(layers_before) == 1
        assert layers_before[0].remaining_qty == Decimal('10')

        in_doc = client.get(
            f'/api/v1/warehouse/documents/{in_doc_id}', headers=doc_auth_headers
        ).json()
        line_number = in_doc['lines'][0]['line_number']

        # Correction with delta=-3 (remove 3 from stock)
        corr_resp = client.post(
            '/api/v1/warehouse/corrections',
            headers=doc_auth_headers,
            json={
                'corrects_document_id': in_doc_id,
                'reason_code': 'DATA_ENTRY_ERROR',
                'lines': [
                    {
                        'original_line_number': line_number,
                        'quantity_delta': -3,
                    }
                ],
                'notes': 'Valuation test correction',
            },
        )
        assert corr_resp.status_code == 201, corr_resp.text
        corr_id = corr_resp.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{corr_id}/confirm', headers=doc_auth_headers
        )
        corr_complete = client.patch(
            f'/api/v1/warehouse/documents/{corr_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert corr_complete.status_code == 200, corr_complete.text

        db_session.expire_all()
        layers_after = db_session.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == doc_template.id,
                StockValuationLayer.direction == 'IN',
            )
        ).all()
        # No new receipt layer should be created — negative delta is a delivery
        assert len(layers_after) == 1
        assert layers_after[0].remaining_qty == Decimal('7')

        # It is a delivery, so it posts what it was worth: three units off a
        # shelf averaging fifteen.
        outgoing = db_session.scalars(
            select(StockValuationLayer).where(
                StockValuationLayer.product_template_id == doc_template.id,
                StockValuationLayer.direction == 'OUT',
            )
        ).all()
        assert len(outgoing) == 1
        assert outgoing[0].quantity == Decimal('3')
        assert outgoing[0].total_value == Decimal('45.00')
        # A correction is neither a use nor a disposal, so it names no reason.
        assert outgoing[0].reason is None
