"""
Integration tests for WMS configuration, scrap and replenishment.

Tests verify:
- Item.is_catalog_entry field
- StorageLocation.warehouse_config JSONB
- DocumentTypeConfig CRUD
- SCRAP document type executor
- Replenishment alerts
"""

from decimal import Decimal

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.partner import Partner
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.user import User
from app.modules.purchase_orders.models import ReorderRule
from app.modules.warehouse.tests.integration._records import (
    shelf_quant,
)
from app.modules.warehouse.tests.integration._records import (
    sow as _sow,
)


@pytest.mark.integration
class TestItemIsCatalogEntry:
    def test_create_catalog_entry_item(
        self,
        db_session: Session,
        doc_org: Organization,
        doc_target_location: StorageLocation,
        doc_user: User,
    ) -> None:
        item = Item(
            name='Catalog Widget',
            organization_id=doc_org.id,
            storage_location_id=doc_target_location.id,
            is_catalog_entry=True,
            quantity=Decimal('0'),
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        assert item.is_catalog_entry is True
        assert item.quantity == Decimal('0')

    def test_default_is_not_catalog(
        self,
        db_session: Session,
        doc_org: Organization,
        doc_target_location: StorageLocation,
        doc_user: User,
    ) -> None:
        item = Item(
            name='Stock Widget',
            organization_id=doc_org.id,
            storage_location_id=doc_target_location.id,
            quantity=Decimal('5'),
        )
        db_session.add(item)
        db_session.commit()
        db_session.refresh(item)

        assert item.is_catalog_entry is False


@pytest.mark.integration
class TestWarehouseConfig:
    def test_warehouse_config_jsonb(
        self,
        db_session: Session,
        doc_org: Organization,
        doc_storage_type: StorageType,
        doc_user: User,
    ) -> None:
        loc = StorageLocation(
            name='Main Warehouse',
            organization_id=doc_org.id,
            storage_type_id=doc_storage_type.id,
            created_by=doc_user.id,
            warehouse_config={
                'reception_steps': '2_steps',
                'delivery_steps': 'pick_ship',
                'default_source_location_id': None,
                'default_dest_location_id': None,
            },
        )
        db_session.add(loc)
        db_session.commit()
        db_session.refresh(loc)

        assert loc.warehouse_config is not None
        assert loc.warehouse_config['reception_steps'] == '2_steps'
        assert loc.warehouse_config['delivery_steps'] == 'pick_ship'


@pytest.mark.integration
class TestDocumentTypeConfig:
    def test_upsert_type_config(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.put(
            '/api/v1/warehouse/settings/type-configs/IN',
            headers=doc_auth_headers,
            json={
                'document_type': 'IN',
                'sequence_format': 'PZ/{YEAR}/{SEQ:04d}',
                'require_partner': True,
            },
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data['document_type'] == 'IN'
        assert data['require_partner'] is True

    def test_config_supplies_default_locations_and_numbering(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_target_location: StorageLocation,
        doc_partner: Partner,
        doc_template: ProductTemplate,
    ) -> None:
        """what the settings promise is what the document gets.

        The per-type configuration was stored and read by nothing — an
        organization could set a default warehouse and its own numbering and
        watch every document ignore both.
        """
        client.put(
            '/api/v1/warehouse/settings/type-configs/IN',
            headers=doc_auth_headers,
            json={
                'document_type': 'IN',
                'sequence_format': 'PZ/{YEAR}/{SEQ:04d}',
                'default_target_location_id': str(doc_target_location.id),
            },
        )

        created = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'IN',
                'partner_id': str(doc_partner.id),
                'lines': [
                    {
                        'product_template_id': str(doc_template.id),
                        'expected_quantity': 1,
                    }
                ],
            },
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        doc = created.json()
        assert doc['target_location_id'] == str(doc_target_location.id)
        # The type's own format reaches the number the document is given
        # when it is confirmed.
        confirmed = client.patch(
            f'/api/v1/warehouse/documents/{doc["id"]}/confirm', headers=doc_auth_headers
        )
        assert confirmed.status_code == status.HTTP_200_OK, confirmed.text
        assert confirmed.json()['number'].startswith('PZ/')

    def test_config_can_demand_a_partner(
        self,
        client: TestClient,
        h: ModuleTestHelper,
    ) -> None:
        """A type the Core leaves optional can still require a partner here.

        Only with the partners module on: with it off the form hides the field,
        so demanding one would deadlock the flow (the rule
        test_document_partner_requirement pins).
        """
        org = h.create_org(
            'Type Config Org',
            ['core', 'items', 'locations', 'categories', 'warehouse', 'partners'],
        )
        user = h.create_user(org, email='typeconfig@example.com')
        headers = h.get_auth_headers(user)
        storage_type = h.create_storage_type('Type Config WH', 'TC_WAREHOUSE')
        location = h.create_storage_location(org, storage_type, user, name='TC Main')
        template = h.create_template(org, name='TC Product')

        client.put(
            '/api/v1/warehouse/settings/type-configs/PW',
            headers=headers,
            json={'document_type': 'INTERNAL_IN', 'require_partner': True},
        )

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=headers,
            json={
                'type': 'INTERNAL_IN',
                'target_location_id': str(location.id),
                'lines': [
                    {'product_template_id': str(template.id), 'expected_quantity': 1}
                ],
            },
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.text

    def test_list_type_configs(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        client.put(
            '/api/v1/warehouse/settings/type-configs/OUT',
            headers=doc_auth_headers,
            json={
                'document_type': 'OUT',
                'require_partner': False,
            },
        )

        resp = client.get(
            '/api/v1/warehouse/settings/type-configs',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert len(data) >= 1

    def test_delete_type_config(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        client.put(
            '/api/v1/warehouse/settings/type-configs/INT',
            headers=doc_auth_headers,
            json={
                'document_type': 'INT',
                'require_partner': False,
            },
        )

        resp = client.delete(
            '/api/v1/warehouse/settings/type-configs/INT',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT

    def test_invalid_type_rejected(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
    ) -> None:
        resp = client.put(
            '/api/v1/warehouse/settings/type-configs/INVALID',
            headers=doc_auth_headers,
            json={
                'document_type': 'INVALID',
            },
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.integration
class TestScrapDocument:
    def test_scrap_document_decrements_quant(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_target_location: StorageLocation,
        doc_stock_item: Item,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
    ) -> None:

        resp = client.post(
            '/api/v1/warehouse/documents',
            headers=doc_auth_headers,
            json={
                'type': 'SCRAP',
                'reason_code': 'DAMAGED',
                'source_location_id': str(doc_source_location.id),
                'lines': [
                    {
                        'item_id': str(doc_stock_item.id),
                        'expected_quantity': 3,
                    }
                ],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED
        doc_id = resp.json()['id']

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
        assert complete.json()['status'] == 'COMPLETED'

        quant = shelf_quant(
            db_session, doc_org.id, doc_template.id, doc_source_location.id
        )
        assert float(quant.quantity) == 97.0
        # And the record it came off, which used to be left alone: the line
        # named no record, so the quant fell while the catalogue went on
        # claiming the goods.
        db_session.refresh(doc_stock_item)
        assert doc_stock_item.quantity == Decimal('97')


@pytest.mark.integration
class TestReplenishmentAlerts:
    def test_alerts_for_low_stock(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        # Replenishment alerts are driven by per-location ReorderRule
        # rows, not ProductTemplate.min_quantity. A rule with
        # min_quantity=10 at the source location defines the threshold.
        rule = ReorderRule(
            organization_id=doc_org.id,
            product_template_id=doc_template.id,
            storage_location_id=doc_source_location.id,
            min_quantity=Decimal('10'),
            max_quantity=Decimal('20'),
            safety_stock=Decimal('0'),
        )
        db_session.add(rule)
        db_session.commit()

        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '3',
        )

        # The alerts are the purchase orders module's route now.
        doc_org.enabled_modules = [*doc_org.enabled_modules, 'purchase_orders']
        db_session.commit()

        resp = client.get(
            '/api/v1/purchase-orders/replenishment/alerts',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()['items']
        assert len(data) >= 1
        alert = next(
            a for a in data if a['product_template_id'] == str(doc_template.id)
        )
        assert alert['available_quantity'] == 3.0
        assert alert['min_quantity'] == 10.0
        assert alert['shortage'] == 7.0

    def test_no_alerts_when_stock_sufficient(
        self,
        client: TestClient,
        doc_auth_headers: dict[str, str],
        doc_source_location: StorageLocation,
        doc_template: ProductTemplate,
        doc_org: Organization,
        db_session: Session,
        async_engine_fixture: AsyncEngine,
    ) -> None:
        # A ReorderRule with min_quantity=2 — stock (50) exceeds it, so
        # no alert is emitted for this (product, location) pair.
        rule = ReorderRule(
            organization_id=doc_org.id,
            product_template_id=doc_template.id,
            storage_location_id=doc_source_location.id,
            min_quantity=Decimal('2'),
            max_quantity=Decimal('20'),
            safety_stock=Decimal('0'),
        )
        db_session.add(rule)
        db_session.commit()

        _sow(
            db_session,
            async_engine_fixture,
            doc_org,
            doc_template,
            doc_source_location.id,
            '50',
        )

        # The alerts are the purchase orders module's route now.
        doc_org.enabled_modules = [*doc_org.enabled_modules, 'purchase_orders']
        db_session.commit()

        resp = client.get(
            '/api/v1/purchase-orders/replenishment/alerts',
            headers=doc_auth_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()['items']
        matching = [a for a in data if a['product_template_id'] == str(doc_template.id)]
        assert len(matching) == 0
