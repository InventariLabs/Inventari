"""
Integration tests for the shelf's stock, StockLot, and reservation system.

The shelf's stock is what its records hold, per product, batch and owner
(the records' view); the tests read it through ``ShelfRow``.

Tests verify:
- Stock arriving on the shelf during IN document completion
- Stock leaving the shelf during OUT document completion
- Stock moving between shelves during INT document completion
- Reservation on CONFIRMED for dispatch/transfer documents
- Reservation release on CANCEL
- Lot/serial creation from document lines
"""

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.storage_location import StorageLocation
from app.modules.warehouse.tests.integration._records import (
    shelf_quant as _shelf_quant,
)
from app.modules.warehouse.tests.integration._records import (
    sow as _sow,
)


@pytest.mark.integration
class TestShelfStockIntegration:
    """Tests for the shelf's stock through the document workflow."""

    def test_in_document_creates_quant(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
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
                        'expected_quantity': 10,
                    }
                ],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        doc_id = response.json()['id']

        confirm = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )
        assert confirm.status_code == status.HTTP_200_OK

        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK

        quant = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.product_template_id == doc_template.id,
                ShelfRow.storage_location_id == doc_target_location.id,
            )
        ).first()
        assert quant is not None
        assert float(quant.quantity) == 10.0
        assert float(quant.reserved_quantity) == 0.0

    def test_out_document_decrements_quant(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '10',
        )

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'product_template_id': str(
                            doc_item.template_id or doc_template.id
                        ),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        doc_id = response.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )
        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK

        quant = _shelf_quant(
            db_session, doc_org.id, doc_template.id, doc_source_location.id
        )
        assert float(quant.quantity) == 5.0

    def test_transfer_moves_quant(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        template_id = doc_item.template_id or doc_template.id
        # The record the line names stands on the source shelf, carrying the
        # card the stock is filed under; it goes in through the items service.
        record = _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '10',
        )

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'INT',
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(record.id),
                        'product_template_id': str(template_id),
                        'expected_quantity': 3,
                    }
                ],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        doc_id = response.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )
        complete = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )
        assert complete.status_code == status.HTTP_200_OK

        quant_source = _shelf_quant(
            db_session, doc_org.id, doc_template.id, doc_source_location.id
        )
        assert float(quant_source.quantity) == 7.0

        quant_target = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.product_template_id == template_id,
                ShelfRow.storage_location_id == doc_target_location.id,
            )
        ).first()
        assert quant_target is not None
        assert float(quant_target.quantity) == 3.0


@pytest.mark.integration
class TestStockReservation:
    """Tests for reservation lifecycle (CONFIRM → reserve, CANCEL → release)."""

    def test_confirm_out_reserves_quant(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        template_id = doc_item.template_id or doc_template.id
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
        )

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'product_template_id': str(template_id),
                        'expected_quantity': 5,
                    }
                ],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        doc_id = response.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )

        quant = _shelf_quant(
            db_session, doc_org.id, template_id, doc_source_location.id
        )
        assert float(quant.reserved_quantity) == 5.0
        assert float(quant.available_quantity) == 15.0

    def test_cancel_confirmed_releases_reservation(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        template_id = doc_item.template_id or doc_template.id
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
        )

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'product_template_id': str(template_id),
                        'expected_quantity': 8,
                    }
                ],
            },
        )
        doc_id = response.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )

        quant = _shelf_quant(
            db_session, doc_org.id, template_id, doc_source_location.id
        )
        assert float(quant.reserved_quantity) == 8.0

        cancel = client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/cancel',
            headers=doc_auth_headers,
        )
        assert cancel.status_code == status.HTTP_200_OK

        quant = _shelf_quant(
            db_session, doc_org.id, template_id, doc_source_location.id
        )
        assert float(quant.reserved_quantity) == 0.0

    def test_complete_out_consumes_reservation(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        template_id = doc_item.template_id or doc_template.id
        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '20',
        )

        response = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'OUT',
                'partner_id': str(doc_partner.id),
                'source_location_id': str(doc_source_location.id),
                'target_location_id': str(doc_target_location.id),
                'lines': [
                    {
                        'item_id': str(doc_item.id),
                        'product_template_id': str(template_id),
                        'expected_quantity': 6,
                    }
                ],
            },
        )
        doc_id = response.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        quant = _shelf_quant(
            db_session, doc_org.id, template_id, doc_source_location.id
        )
        assert float(quant.quantity) == 14.0
        assert float(quant.reserved_quantity) == 0.0


@pytest.mark.integration
class TestStockLotCreation:
    """Tests for automatic StockLot creation from document lines."""

    def test_in_with_batch_creates_lot(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
        db_session: Session,
    ) -> None:
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
                        'expected_quantity': 10,
                        'batch_number': 'LOT-2026-001',
                        'expiry_date': '2026-12-31',
                    }
                ],
            },
        )
        doc_id = response.json()['id']

        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        lot = db_session.scalars(
            select(StockLot).where(
                StockLot.product_template_id == doc_template.id,
                StockLot.name == 'LOT-2026-001',
            )
        ).first()
        assert lot is not None
        assert lot.is_serial is False
        assert lot.expiry_date is not None

        quant = db_session.scalars(
            select(ShelfRow).where(
                ShelfRow.product_template_id == doc_template.id,
                ShelfRow.lot_id == lot.id,
            )
        ).first()
        assert quant is not None
        assert float(quant.quantity) == 10.0

    def test_stock_api_list_quants(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
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
                        'expected_quantity': 25,
                    }
                ],
            },
        )
        doc_id = response.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        quants = client.get(
            f'/api/v1/stock-quants?product_template_id={doc_template.id}',
            headers=doc_auth_headers,
        )
        assert quants.status_code == status.HTTP_200_OK
        data = quants.json()['items']
        assert len(data) >= 1
        assert any(float(q['quantity']) == 25.0 for q in data)

    def test_stock_api_list_lots(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
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
                        'expected_quantity': 5,
                        'batch_number': 'LOT-API-TEST',
                    }
                ],
            },
        )
        doc_id = response.json()['id']
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/confirm',
            headers=doc_auth_headers,
        )
        client.patch(
            f'/api/v1/warehouse/documents/{doc_id}/complete',
            headers=doc_auth_headers,
            json={'complete_as_planned': True},
        )

        lots = client.get(
            f'/api/v1/stock-lots?product_template_id={doc_template.id}',
            headers=doc_auth_headers,
        )
        assert lots.status_code == status.HTTP_200_OK
        data = lots.json()['items']
        assert len(data) >= 1
        assert any(lot['name'] == 'LOT-API-TEST' for lot in data)
