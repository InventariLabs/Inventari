"""
Integration tests for export_service (XLSX export).

Tests cover:
- Export with items returns valid XLSX
- Export with empty organization returns empty spreadsheet
- Export filters by storage_id
- Export filters by context_tag
- Dynamic columns from meta_data (nutrition, equipment, custom)
- Column ordering (system columns first)
"""

import inspect
import io
from decimal import Decimal

import pandas as pd
import pytest
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.item import Item
from app.models.storage_location import StorageLocation
from app.services.items.export_service import export_items_to_xlsx


def _make_user_ctx(user):
    """Build a minimal object matching what export_items_to_xlsx reads from current_user."""
    from types import SimpleNamespace

    return SimpleNamespace(
        organization_id=user.organization_id,
        id=user.id,
    )


async def _read_xlsx_bytes(response: StreamingResponse) -> bytes:
    """Consume a StreamingResponse and return its raw body."""
    chunks = []
    iterator = response.body_iterator

    if inspect.isasyncgen(iterator):
        async for chunk in iterator:
            if isinstance(chunk, bytes):
                chunks.append(chunk)
            else:
                chunks.append(chunk.encode())
    else:
        for chunk in iterator:
            if isinstance(chunk, bytes):
                chunks.append(chunk)
            else:
                chunks.append(chunk.encode())

    return b''.join(chunks)


async def _read_xlsx_response(response: StreamingResponse) -> pd.DataFrame:
    """Consume a StreamingResponse and return its content as a DataFrame."""
    raw = await _read_xlsx_bytes(response)
    return pd.read_excel(io.BytesIO(raw), sheet_name='Inventory')


@pytest.mark.integration
@pytest.mark.asyncio
class TestExportItemsToXlsx:
    """Tests for export_items_to_xlsx."""

    async def test_export_returns_streaming_response(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_item
    ):
        """Export with at least one item returns a StreamingResponse."""
        ctx = _make_user_ctx(async_test_user)
        response = await real_async_db_session.run_sync(
            lambda s: export_items_to_xlsx(s, ctx)
        )

        assert isinstance(response, StreamingResponse)
        assert (
            response.media_type
            == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

    async def test_export_contains_item_data(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_item
    ):
        """Exported spreadsheet contains the test item's data."""
        ctx = _make_user_ctx(async_test_user)
        response = await real_async_db_session.run_sync(
            lambda s: export_items_to_xlsx(s, ctx)
        )
        df = await _read_xlsx_response(response)

        assert len(df) >= 1
        row = df[df['Name'] == 'Pork Loin']
        assert len(row) == 1
        assert row.iloc[0]['Brand'] == 'Good Brand'
        assert float(row.iloc[0]['Quantity']) == 2.0

    async def test_item_name_is_never_exported_as_a_formula(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_item,
    ):
        """an item named like a formula must stay text in the sheet."""
        from openpyxl import load_workbook

        async_test_item.name = "=cmd|'/c calc'!A1"
        await real_async_db_session.flush()

        ctx = _make_user_ctx(async_test_user)
        response = await real_async_db_session.run_sync(
            lambda s: export_items_to_xlsx(s, ctx)
        )
        raw = await _read_xlsx_bytes(response)

        sheet = load_workbook(io.BytesIO(raw))['Inventory']
        cells = [
            c
            for row in sheet.iter_rows()
            for c in row
            if c.value == "=cmd|'/c calc'!A1"
        ]
        assert cells, 'the item name is missing from the export'
        assert all(cell.data_type == 's' for cell in cells)

    async def test_export_empty_org_returns_empty_df(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """Export for org with no items returns an empty DataFrame with system columns."""
        ctx = _make_user_ctx(async_test_user)
        response = await real_async_db_session.run_sync(
            lambda s: export_items_to_xlsx(s, ctx)
        )
        df = await _read_xlsx_response(response)

        assert len(df) == 0
        for col in [
            'Name',
            'Quantity',
            'Unit',
            'Location',
            'Category',
            'Barcode',
            'Label Code',
        ]:
            assert col in df.columns
        # The column was headed Storage until locations were called locations;
        # the importer still maps that header, the export no longer writes it.
        assert 'Storage' not in df.columns

    async def test_export_filters_by_storage_id(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
        async_test_category,
    ):
        """Export with storage_id filter only returns items from that location."""
        from app.models.storage_type import StorageType

        db = real_async_db_session
        other_type = StorageType(name='Pantry', type_code='PANTRY', icon='Box')
        db.add(other_type)
        await db.flush()

        other_loc = StorageLocation(
            organization_id=async_test_user.organization_id,
            created_by=async_test_user.id,
            storage_type_id=other_type.id,
            name='Other Location',
        )
        db.add(other_loc)
        await db.flush()

        other_item = Item(
            organization_id=async_test_user.organization_id,
            storage_location_id=other_loc.id,
            category_id=async_test_category.id,
            name='Other Item',
            quantity=Decimal('5'),
        )
        db.add(other_item)
        await db.commit()

        ctx = _make_user_ctx(async_test_user)
        response = await real_async_db_session.run_sync(
            lambda s: export_items_to_xlsx(
                s, ctx, {'storage_id': async_test_storage_location.id}
            )
        )
        df = await _read_xlsx_response(response)

        assert all(name != 'Other Item' for name in df['Name'].tolist())

    async def test_export_never_carries_another_organizations_products(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_item,
        async_test_storage_location,
    ):
        """The sheet is scoped by the organization's locations alone.

        The export runs the list's filter in its organization mode, which no
        other production path uses: the list itself goes by the reader's
        location ids. Remove the organization clause there and every other
        test stays green while the sheet fills with a neighbour's stock.
        """
        from app.models.organization import Organization
        from app.models.storage_type import StorageType

        db = real_async_db_session
        neighbour = Organization(name='Neighbour Org', enabled_modules=['core'])
        shelf_type = StorageType(name='Shelf', type_code='SHELF', icon='Box')
        db.add_all([neighbour, shelf_type])
        await db.flush()

        their_shelf = StorageLocation(
            organization_id=neighbour.id,
            created_by=async_test_user.id,
            storage_type_id=shelf_type.id,
            name='Neighbour Shelf',
        )
        db.add(their_shelf)
        await db.flush()
        db.add(
            Item(
                organization_id=neighbour.id,
                storage_location_id=their_shelf.id,
                name='Neighbour Product',
                quantity=Decimal('3'),
            )
        )
        await db.commit()

        ctx = _make_user_ctx(async_test_user)
        # The router's call: the reader's own locations beside the context.
        response = await db.run_sync(
            lambda s: export_items_to_xlsx(
                s, ctx, {}, None, [async_test_storage_location.id]
            )
        )
        df = await _read_xlsx_response(response)

        names = df['Name'].tolist()
        assert async_test_item.name in names
        assert 'Neighbour Product' not in names
        assert 'Neighbour Shelf' not in df.to_string()

    async def test_export_includes_metadata_custom_fields(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
        async_test_category,
    ):
        """Items with meta_data produce extra columns in the export."""
        db = real_async_db_session
        item = Item(
            organization_id=async_test_user.organization_id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Meta Item',
            quantity=Decimal('1'),
            meta_data={'notes': 'keep refrigerated', 'lot': 'A1'},
        )
        db.add(item)
        await db.commit()

        ctx = _make_user_ctx(async_test_user)
        response = await real_async_db_session.run_sync(
            lambda s: export_items_to_xlsx(s, ctx)
        )
        df = await _read_xlsx_response(response)

        row = df[df['Name'] == 'Meta Item']
        assert len(row) == 1
        assert 'Custom: notes' in df.columns or 'Custom: lot' in df.columns

    async def test_export_includes_nutrition_metadata(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
        async_test_category,
    ):
        """Nutrition metadata is expanded into Nutri: prefixed columns."""
        db = real_async_db_session
        item = Item(
            organization_id=async_test_user.organization_id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Nutri Item',
            quantity=Decimal('1'),
            meta_data={'nutrition': {'calories': 250, 'protein': 30}},
        )
        db.add(item)
        await db.commit()

        ctx = _make_user_ctx(async_test_user)
        response = await real_async_db_session.run_sync(
            lambda s: export_items_to_xlsx(s, ctx)
        )
        df = await _read_xlsx_response(response)

        assert 'Nutri: calories' in df.columns
        assert 'Nutri: protein' in df.columns

    async def test_export_column_order_system_first(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_item
    ):
        """System columns appear before dynamic columns in the export."""
        ctx = _make_user_ctx(async_test_user)
        response = await real_async_db_session.run_sync(
            lambda s: export_items_to_xlsx(s, ctx)
        )
        df = await _read_xlsx_response(response)

        system_cols = [
            'Name',
            'Quantity',
            'Unit',
            'Location',
            'Category',
            'Barcode',
            'Label Code',
        ]
        cols = list(df.columns)
        system_positions = [cols.index(c) for c in system_cols if c in cols]

        assert system_positions == sorted(system_positions)

    async def test_export_with_context_tag_filter(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ):
        """Export with context_tag filters items by category.context_tag."""
        db = real_async_db_session
        cat = Category(
            name='Equipment',
            context_tag='equipment',
            organization_id=async_test_user.organization_id,
        )
        db.add(cat)
        await db.flush()

        item = Item(
            organization_id=async_test_user.organization_id,
            storage_location_id=async_test_storage_location.id,
            category_id=cat.id,
            name='Equip Item',
            quantity=Decimal('1'),
        )
        db.add(item)
        await db.commit()

        ctx = _make_user_ctx(async_test_user)
        response = await real_async_db_session.run_sync(
            lambda s: export_items_to_xlsx(s, ctx, {'context_tag': 'equipment'})
        )
        df = await _read_xlsx_response(response)

        names = df['Name'].tolist()
        assert 'Equip Item' in names

    async def test_export_default_currency_usd(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
        async_test_category,
    ):
        """Without org settings, price column uses USD."""
        db = real_async_db_session
        async_test_storage_location.context_schema = ['purchase_price']
        await db.commit()

        item = Item(
            organization_id=async_test_user.organization_id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Priced Item',
            quantity=Decimal('1'),
            purchase_price=Decimal('9.99'),
        )
        db.add(item)
        await db.commit()

        ctx = _make_user_ctx(async_test_user)
        response = await real_async_db_session.run_sync(
            lambda s: export_items_to_xlsx(s, ctx)
        )
        df = await _read_xlsx_response(response)

        assert 'Purchase price per unit (USD)' in df.columns

    async def test_export_deleted_items_excluded(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
        async_test_category,
    ):
        """Soft-deleted items are not included in the export."""
        db = real_async_db_session
        item = Item(
            organization_id=async_test_user.organization_id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Deleted Item',
            quantity=Decimal('1'),
            is_deleted=True,
        )
        db.add(item)
        await db.commit()

        ctx = _make_user_ctx(async_test_user)
        response = await real_async_db_session.run_sync(
            lambda s: export_items_to_xlsx(s, ctx)
        )
        df = await _read_xlsx_response(response)

        assert all(name != 'Deleted Item' for name in df['Name'].tolist())

    async def test_the_notes_a_location_tracks_reach_the_description_column(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
        async_test_category,
    ):
        """The tracked field "Notes" is the product's description.

        The storage screens name two product fields in their own words —
        their toggles store 'notes' and 'price' where the product calls them
        'description' and 'purchase_price' — and the sheet names its columns
        after the product's fields. Reading the tracked keys as column keys
        dropped the Description column from every sheet of an organization
        whose locations track Notes.
        """
        db = real_async_db_session
        async_test_storage_location.context_schema = ['notes']
        await db.commit()

        item = Item(
            organization_id=async_test_user.organization_id,
            storage_location_id=async_test_storage_location.id,
            category_id=async_test_category.id,
            name='Noted Item',
            quantity=Decimal('1'),
            description='handle with care',
        )
        db.add(item)
        await db.commit()

        ctx = _make_user_ctx(async_test_user)
        response = await real_async_db_session.run_sync(
            lambda s: export_items_to_xlsx(s, ctx)
        )
        df = await _read_xlsx_response(response)

        assert 'Description' in df.columns
        row = df[df['Name'] == 'Noted Item']
        assert row.iloc[0]['Description'] == 'handle with care'


@pytest.mark.integration
@pytest.mark.asyncio
class TestEquipmentExportColumns:
    """equipment exports carry Price, Currency and Assigned To.

    Before the fix, ``active_keys`` was built from storage-location schemas
    only, so equipment exports (whose locations carry empty schemas) dropped
    every ``key_map`` column — including the purchase price the exporter
    already had a mapping for. The same export lacked the currency and the
    active assignee, and equipment meta columns used raw database keys as
    headers.
    """

    async def _seed_equipment_org(self, db: AsyncSession):
        from app.models.category import Category
        from app.models.item import Item
        from app.models.organization import Organization
        from app.models.storage_type import StorageType
        from app.models.user import User
        from app.modules.equipment.models import EquipmentAssignment

        org = Organization(
            name='Equip Export Org',
            enabled_modules=['core', 'items', 'equipment'],
            currency='PLN',
        )
        db.add(org)
        await db.flush()

        user = User(
            email='export-eq@example.com',
            hashed_password='x',
            full_name='Export Eq',
            organization_id=org.id,
            role='admin',
            is_active=True,
        )
        db.add(user)
        await db.flush()

        storage_type = StorageType(name='IT', type_code='IT', behavior_mode='NONE')
        db.add(storage_type)
        await db.flush()

        location = StorageLocation(
            name='Server Room',
            organization_id=org.id,
            storage_type_id=storage_type.id,
            created_by=user.id,
        )
        db.add(location)
        await db.flush()

        category = Category(
            name='Laptop',
            code='LAPTOP',
            context_tag='equipment',
            organization_id=None,
            field_definitions=[
                {
                    'key': 'serial_number',
                    'type': 'text',
                    'label': 'Serial Number',
                    'is_system': True,
                },
                {
                    'key': 'warranty_until',
                    'type': 'date',
                    'label': 'Warranty Until',
                    'is_system': True,
                },
            ],
        )
        db.add(category)
        await db.flush()

        item = Item(
            name='ThinkPad',
            organization_id=org.id,
            storage_location_id=location.id,
            category_id=category.id,
            quantity=1,
            purchase_price=Decimal('4500.00'),
            currency='PLN',
            meta_data={
                'equipment': {
                    'serial_number': 'SN-1',
                    'warranty_until': '2027-01-01',
                    'equipment_status': 'AVAILABLE',
                }
            },
        )
        db.add(item)
        await db.flush()

        db.add(
            EquipmentAssignment(
                organization_id=org.id,
                item_id=item.id,
                assigned_to_name='Anna Kowalska',
                checked_out_by=user.id,
            )
        )
        await db.commit()
        return org, user

    async def test_equipment_export_price_currency_assigned_to(
        self, real_async_db_session: AsyncSession
    ):
        """Price (org currency), Currency, Assigned To and human headers."""
        from app.core.export_enrichers import enrich_export_rows

        org, user = await self._seed_equipment_org(real_async_db_session)
        enrichment = await enrich_export_rows(
            real_async_db_session, org.id, org.enabled_modules or []
        )

        ctx = _make_user_ctx(user)
        response = await real_async_db_session.run_sync(
            lambda s: export_items_to_xlsx(
                s, ctx, {'context_tag': 'equipment'}, enrichment=enrichment
            )
        )
        df = await _read_xlsx_response(response)

        assert len(df) == 1
        assert 'Purchase price per unit (PLN)' in df.columns
        assert float(df.iloc[0]['Purchase price per unit (PLN)']) == 4500.00
        assert 'Currency' in df.columns
        assert df.iloc[0]['Currency'] == 'PLN'
        assert 'Assigned To' in df.columns
        assert df.iloc[0]['Assigned To'] == 'Anna Kowalska'
        # Equipment meta columns use the category field labels, not raw keys.
        assert 'Serial Number' in df.columns
        assert df.iloc[0]['Serial Number'] == 'SN-1'
        assert 'Warranty Until' in df.columns
        assert 'serial_number' not in df.columns
        assert 'warranty_until' not in df.columns

    async def test_food_context_keeps_its_columns(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_item
    ):
        """regression: the food context loses no column from the change."""
        ctx = _make_user_ctx(async_test_user)
        response = await real_async_db_session.run_sync(
            lambda s: export_items_to_xlsx(s, ctx)
        )
        df = await _read_xlsx_response(response)

        for col in [
            'Name',
            'Quantity',
            'Unit',
            'Location',
            'Category',
            'Barcode',
            'Label Code',
            'Brand',
        ]:
            assert col in df.columns, f'food export lost column {col}'
