"""endpoint-level regression: equipment XLSX export completeness.

Proves the whole wiring — Core export endpoint → export enrichment
registry → equipment module enricher — produces an accountant-ready sheet
with the purchase price (org currency), Currency, Assigned To, and human
field headers.
"""

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.import_sheet import read_sheet
from app.models.category import Category
from app.models.item import Item
from app.models.organization import Organization
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.equipment.models import EquipmentAssignment


@pytest.mark.integration
class TestEquipmentExportColumns:
    def test_export_includes_price_currency_and_assigned_to(
        self,
        client: TestClient,
        db_session: Session,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_user: User,
        eq_item: Item,
    ) -> None:
        eq_org.currency = 'PLN'
        eq_item.purchase_price = Decimal('4500.00')
        eq_item.currency = 'PLN'
        db_session.add(
            EquipmentAssignment(
                organization_id=eq_org.id,
                item_id=eq_item.id,
                assigned_to_name='Anna Kowalska',
                checked_out_by=eq_user.id,
            )
        )
        db_session.commit()

        response = client.get(
            '/api/v1/items/export/xlsx?context_tag=equipment',
            headers=eq_auth_headers,
        )

        assert response.status_code == 200
        df = read_sheet(response.content, 'export.xlsx', sheet_name='Inventory')

        assert len(df) == 1
        assert 'Purchase price per unit (PLN)' in df.columns
        assert float(df.iloc[0]['Purchase price per unit (PLN)']) == 4500.00
        assert 'Currency' in df.columns
        assert df.iloc[0]['Currency'] == 'PLN'
        assert 'Assigned To' in df.columns
        assert df.iloc[0]['Assigned To'] == 'Anna Kowalska'
        assert 'Serial Number' in df.columns
        assert 'serial_number' not in df.columns

    def test_a_deployment_exports_the_place_that_holds_it(
        self,
        client: TestClient,
        db_session: Session,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_user: User,
        eq_item: Item,
        eq_storage_location: StorageLocation,
    ) -> None:
        """The accountant's sheet asks who holds the asset; a deployed one
        is held by the place, and the cell must not be blank."""
        db_session.add(
            EquipmentAssignment(
                organization_id=eq_org.id,
                item_id=eq_item.id,
                assigned_to_name='',
                checkout_location_id=eq_storage_location.id,
                checked_out_by=eq_user.id,
            )
        )
        db_session.commit()

        response = client.get(
            '/api/v1/items/export/xlsx?context_tag=equipment',
            headers=eq_auth_headers,
        )

        assert response.status_code == 200
        df = read_sheet(response.content, 'export.xlsx', sheet_name='Inventory')
        assert df.iloc[0]['Assigned To'] == 'Server Room A'

    def test_one_header_per_field_regardless_of_category(
        self,
        client: TestClient,
        db_session: Session,
        eq_auth_headers: dict[str, str],
        eq_org: Organization,
        eq_item: Item,
    ) -> None:
        """A field lands in one column for the whole sheet.

        Headers used to come from the row's own category, so an asset
        without one (or with a category that does not declare the field)
        produced a second column — "Equipment Status" next to "Status" —
        and the sheet could no longer be re-imported without remapping
        (audit 2026-08-16).
        """
        # A second equipment category that declares no equipment_status
        # field — its assets still carry the value in meta_data.
        sparse_category = Category(
            organization_id=eq_org.id,
            name='Peripheral',
            code='PERIPHERAL',
            context_tag='equipment',
            field_definitions=[
                {
                    'key': 'serial_number',
                    'type': 'text',
                    'label': 'Serial Number',
                    'is_system': True,
                }
            ],
        )
        db_session.add(sparse_category)
        db_session.commit()
        db_session.refresh(sparse_category)

        sparse_item = Item(
            organization_id=eq_org.id,
            storage_location_id=eq_item.storage_location_id,
            category_id=sparse_category.id,
            name='Logitech MX Master',
            quantity=1,
            meta_data={
                'equipment': {
                    'serial_number': 'SN-NOCAT',
                    'equipment_status': 'AVAILABLE',
                }
            },
        )
        db_session.add(sparse_item)
        db_session.commit()

        response = client.get(
            '/api/v1/items/export/xlsx?context_tag=equipment',
            headers=eq_auth_headers,
        )

        assert response.status_code == 200
        df = read_sheet(response.content, 'export.xlsx', sheet_name='Inventory')

        assert 'Equipment Status' not in df.columns, (
            f'raw-key fallback produced a duplicate column: {list(df.columns)}'
        )
        assert 'Status' in df.columns
        statuses = df['Status'].dropna().tolist()
        assert len(statuses) == 2, (
            f'both assets must report their status in one column, got {statuses}'
        )
        serials = df['Serial Number'].dropna().tolist()
        assert 'SN-NOCAT' in serials
