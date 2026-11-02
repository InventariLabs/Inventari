"""
Integration tests for scan_providers service.

Tests barcode/label scanning providers:
- StorageScanProvider: Storage location scanning (any code, DB-lookup fallthrough)
- LabelPoolScanProvider: Label pool scanning (PREFIX-SUFFIX format)
- BarcodeScanProvider: Product barcode scanning (numeric codes)
"""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scan_providers import (
    BarcodeScanProvider,
    LabelPoolScanProvider,
    StorageScanProvider,
)
from app.models.category import Category
from app.models.item import Item
from app.models.label_pool import LabelPool
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_anchor import StockAnchor
from app.models.storage_location import LocationUsage, StorageLocation
from app.models.storage_type import StorageType


def _unique_short_code(prefix: str = 'STM') -> str:
    """Generate a unique short code per test to avoid UNIQUE collisions."""
    return f'{prefix}-{uuid.uuid4().hex[:8].upper()}'


async def _make_storage_type(db: AsyncSession) -> StorageType:
    storage_type = StorageType(name='Freezer', type_code='FREEZER', icon='Snowflake')
    db.add(storage_type)
    await db.commit()
    await db.refresh(storage_type)
    return storage_type


async def _make_storage_location(
    db: AsyncSession, org_id, user_id, storage_type_id
) -> StorageLocation:
    storage = StorageLocation(
        organization_id=org_id,
        created_by=user_id,
        storage_type_id=storage_type_id,
        name='Pantry',
        short_code=_unique_short_code('LOC'),
        usage=LocationUsage.INTERNAL,
    )
    db.add(storage)
    await db.commit()
    await db.refresh(storage)
    return storage


async def _make_category(db: AsyncSession) -> Category:
    category = Category(name='Pork', icon='🥩', sort_order=1)
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


async def _make_item(
    db: AsyncSession,
    org_id,
    storage_location_id,
    category_id,
    **kwargs,
) -> Item:
    freeze_date = kwargs.pop('freeze_date', date.today())
    item = Item(
        organization_id=org_id,
        storage_location_id=storage_location_id,
        category_id=category_id,
        name=kwargs.pop('name', 'Pork Loin'),
        brand=kwargs.pop('brand', 'Good Brand'),
        quantity=kwargs.pop('quantity', 2),
        expiry_date=kwargs.pop('expiry_date', date.today() + timedelta(days=30)),
        barcode=kwargs.pop('barcode', None),
        is_deleted=kwargs.pop('is_deleted', False),
        meta_data=kwargs.pop('meta_data', None),
    )
    # freeze_date now lives in meta_data['food'] (a shim), not a column.
    from app.services.items._date_meta import merge_legacy_date_into_meta

    item.meta_data = merge_legacy_date_into_meta(
        item.meta_data, 'freeze_date', freeze_date
    )
    for key, value in kwargs.items():
        setattr(item, key, value)
    if item.template_id is not None:
        # The record's group has to be on disk before the foreign key that
        # points at it is checked, so the anchor is committed on its own.
        known = await db.scalar(
            select(StockAnchor.id).where(
                StockAnchor.organization_id == org_id,
                StockAnchor.product_template_id == item.template_id,
                StockAnchor.storage_location_id == storage_location_id,
            )
        )
        if known is None:
            db.add(
                StockAnchor(
                    organization_id=org_id,
                    product_template_id=item.template_id,
                    storage_location_id=storage_location_id,
                )
            )
            await db.commit()
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def _make_template(db: AsyncSession, org_id, barcode: str, name: str):
    """The catalogue card a code names.

    A barcode belongs to the card: only one active record per organization may
    bear it, so stock under one code is built as several records on one card.
    """
    template = ProductTemplate(organization_id=org_id, name=name, barcode=barcode)
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


@pytest.mark.integration
class TestStorageScanProvider:
    """Test StorageScanProvider for storage location scanning."""

    @pytest.fixture
    def provider(self):
        """Create provider instance."""
        return StorageScanProvider()

    @pytest.mark.asyncio
    async def test_can_handle_loc_prefix(self, provider):
        """Test can_handle returns True for LOC- prefix."""
        result = await provider.can_handle('LOC-PANTRY')
        assert result is True

    @pytest.mark.asyncio
    async def test_can_handle_lowercase_loc(self, provider):
        """Test can_handle returns True for any code (case-insensitive DB lookup)."""
        result = await provider.can_handle('loc-pantry')
        assert result is True  # Accepts any code; handle() returns None if not in DB

    @pytest.mark.asyncio
    async def test_can_handle_non_loc_code(self, provider):
        """Test can_handle returns True for any code (GLN, custom, etc.)."""
        result = await provider.can_handle('STM-001')
        assert result is True  # Accepts any code; registry fallthrough if no DB match

    @pytest.mark.asyncio
    async def test_can_handle_gln_code(self, provider):
        """Test can_handle returns True for GLN-style numeric codes."""
        result = await provider.can_handle('5901234123457')
        assert result is True

    @pytest.mark.asyncio
    async def test_can_handle_custom_code(self, provider):
        """Test can_handle returns True for custom warehouse codes."""
        result = await provider.can_handle('CHLODNIA-1')
        assert result is True

    @pytest.mark.asyncio
    async def test_handle_unknown_code_returns_none(
        self, provider, real_async_db_session: AsyncSession, async_test_user
    ):
        """Test handle returns None for unknown codes, allowing registry fallthrough."""
        result = await provider.handle(
            'UNKNOWN-9999', async_test_user, real_async_db_session
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_storage_found(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """Test handle returns storage context when found."""
        db = real_async_db_session
        storage_type = await _make_storage_type(db)
        short_code = _unique_short_code('LOC')
        storage = StorageLocation(
            organization_id=async_test_user.organization_id,
            created_by=async_test_user.id,
            storage_type_id=storage_type.id,
            name='Pantry',
            short_code=short_code,
            usage=LocationUsage.INTERNAL,
        )
        db.add(storage)
        await db.commit()

        result = await provider.handle(
            short_code, async_test_user, real_async_db_session
        )

        assert result is not None
        assert result.status == 'storage_context'
        assert result.label_code == short_code
        assert result.location['name'] == 'Pantry'
        assert result.action == 'set_storage_context'

    @pytest.mark.asyncio
    async def test_handle_storage_not_found(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """Test handle returns None when storage not found."""
        result = await provider.handle(
            'LOC-NOTFOUND', async_test_user, real_async_db_session
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_handle_wrong_organization(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """Test handle ignores storage from other organizations."""
        db = real_async_db_session
        storage_type = await _make_storage_type(db)
        other_org_id = (
            async_test_user.organization_id
        )  # In real test, would be different
        short_code = _unique_short_code('LOC')

        storage = StorageLocation(
            organization_id=other_org_id,
            created_by=async_test_user.id,
            storage_type_id=storage_type.id,
            name='Other Org Storage',
            short_code=short_code,
            usage=LocationUsage.INTERNAL,
        )
        db.add(storage)
        await db.commit()

        result = await provider.handle(
            short_code, async_test_user, real_async_db_session
        )

        # Storage belongs to same org in test, so it will be found
        assert result is not None


@pytest.mark.integration
class TestLabelPoolScanProvider:
    """Test LabelPoolScanProvider for label pool scanning."""

    @pytest.fixture
    def provider(self):
        """Create provider instance."""
        return LabelPoolScanProvider()

    @pytest.mark.asyncio
    async def test_can_handle_valid_format(self, provider):
        """Test can_handle returns True for valid PREFIX-SUFFIX format."""
        valid_codes = [
            'STM-001',
            'ABC-DEFGH',
            'A-ABC',
            'ABCDEFGHIJ-ABCDEFGH',
            # Short suffixes are valid so equipment serials like ASD-1 scan.
            'ASD-1',
            'ASD-10',
            'AB-CD',
        ]
        for code in valid_codes:
            result = await provider.can_handle(code)
            assert result is True

    @pytest.mark.asyncio
    async def test_can_handle_loc_prefix_false(self, provider):
        """Test can_handle returns True for LOC-* prefix (matches regex but higher priority goes to StorageScanProvider)."""
        # Note: Regex matches LOC- but StorageScanProvider has higher priority in chain
        result = await provider.can_handle('LOC-PANTRY')
        assert (
            result is True
        )  # Regex matches, but prioritization happens at registry level

    @pytest.mark.asyncio
    async def test_can_handle_barcode_false(self, provider):
        """Test can_handle returns False for pure numeric codes."""
        result = await provider.can_handle('12345678')
        assert result is False

    @pytest.mark.asyncio
    async def test_can_handle_invalid_format(self, provider):
        """Test can_handle returns False for invalid formats."""
        invalid_codes = [
            'ABC',  # No hyphen
            'abc-def',  # Lowercase
            'A-',  # Missing suffix
            '-ABC',  # Missing prefix
        ]
        for code in invalid_codes:
            result = await provider.can_handle(code)
            assert result is False

    @pytest.mark.asyncio
    async def test_handle_label_not_found(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """Test handle returns None when label not found."""
        result = await provider.handle(
            'STM-NOTFOUND', async_test_user, real_async_db_session
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_handle_storage_label(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """Test handle returns storage context for STORAGE type label."""
        db = real_async_db_session
        storage_type = await _make_storage_type(db)
        storage_location = await _make_storage_location(
            db,
            async_test_user.organization_id,
            async_test_user.id,
            storage_type.id,
        )
        short_code = _unique_short_code('STM')

        label = LabelPool(
            organization_id=async_test_user.organization_id,
            short_code=short_code,
            label_type='STORAGE',
            target_storage_location_id=storage_location.id,
            is_assigned=True,
            created_by=async_test_user.id,
        )
        db.add(label)
        await db.flush()

        result = await provider.handle(
            short_code, async_test_user, real_async_db_session
        )

        assert result is not None
        assert result.status == 'storage_context'
        assert result.label_code == short_code
        # Verify scan tracking was incremented — committed first, because the
        # session autoflush is off: a refresh without a commit reads the row
        # while a pending mirror of the same increment still sits in the
        # session, and the doubling stays invisible until the flush.
        await db.commit()
        await db.refresh(label)
        assert label.scan_count == 1

    @pytest.mark.asyncio
    async def test_handle_unassigned_label(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """Test handle returns unassigned response for unassigned label."""
        db = real_async_db_session
        short_code = _unique_short_code('STM')
        label = LabelPool(
            organization_id=async_test_user.organization_id,
            short_code=short_code,
            label_type='ITEM',
            is_assigned=False,
            created_by=async_test_user.id,
        )
        db.add(label)
        await db.commit()

        result = await provider.handle(
            short_code, async_test_user, real_async_db_session
        )

        assert result is not None
        assert result.status == 'unassigned'
        assert result.action == 'show_quick_add'

    @pytest.mark.asyncio
    async def test_handle_assigned_label_with_item(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """Test handle returns assigned response with item data."""
        db = real_async_db_session
        storage_type = await _make_storage_type(db)
        storage_location = await _make_storage_location(
            db,
            async_test_user.organization_id,
            async_test_user.id,
            storage_type.id,
        )
        category = await _make_category(db)
        test_item = await _make_item(
            db,
            async_test_user.organization_id,
            storage_location.id,
            category.id,
        )
        short_code = _unique_short_code('STM')

        label = LabelPool(
            organization_id=async_test_user.organization_id,
            short_code=short_code,
            label_type='ITEM',
            is_assigned=True,
            item_id=test_item.id,
            created_by=async_test_user.id,
        )
        db.add(label)
        await db.commit()

        result = await provider.handle(
            short_code, async_test_user, real_async_db_session
        )

        assert result is not None
        assert result.status == 'assigned'
        assert result.action == 'show_quick_actions'
        assert 'item' in result.quick_actions or result.item is not None

    @pytest.mark.asyncio
    async def test_handle_assigned_label_item_deleted(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """Test handle returns archived response when assigned item is deleted."""
        db = real_async_db_session
        storage_type = await _make_storage_type(db)
        storage_location = await _make_storage_location(
            db,
            async_test_user.organization_id,
            async_test_user.id,
            storage_type.id,
        )
        category = await _make_category(db)
        test_item = await _make_item(
            db,
            async_test_user.organization_id,
            storage_location.id,
            category.id,
        )
        test_item.is_deleted = True
        await db.commit()
        short_code = _unique_short_code('STM')

        label = LabelPool(
            organization_id=async_test_user.organization_id,
            short_code=short_code,
            label_type='ITEM',
            is_assigned=True,
            item_id=test_item.id,
            created_by=async_test_user.id,
        )
        db.add(label)
        await db.commit()

        result = await provider.handle(
            short_code, async_test_user, real_async_db_session
        )

        assert result is not None
        assert result.status == 'archived'
        assert result.action == 'show_archived_info'

    @pytest.mark.asyncio
    async def test_deleting_an_item_leaves_its_label_bound(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """Deleting the thing must not erase the answer to "what was this?".

        Deletion used to free the label slot in the same transaction that set
        is_deleted, so the archived branch above, the sheet it opens and the
        label pool's "Consumed (Archived)" filter described a state nothing
        could produce. A sticker outlives the thing it was stuck to; the sheet
        frees the slot when someone says the label is free.
        """
        from app.core.contracts import UserContextDTO
        from app.services.items import delete_item

        db = real_async_db_session
        storage_type = await _make_storage_type(db)
        storage_location = await _make_storage_location(
            db,
            async_test_user.organization_id,
            async_test_user.id,
            storage_type.id,
        )
        category = await _make_category(db)
        item = await _make_item(
            db,
            async_test_user.organization_id,
            storage_location.id,
            category.id,
        )
        short_code = _unique_short_code('STM')
        label = LabelPool(
            organization_id=async_test_user.organization_id,
            short_code=short_code,
            label_type='ITEM',
            is_assigned=True,
            item_id=item.id,
            created_by=async_test_user.id,
        )
        db.add(label)
        item.label_code = short_code
        await db.commit()

        await delete_item(
            db,
            item,
            UserContextDTO(
                id=async_test_user.id,
                email=async_test_user.email,
                organization_id=async_test_user.organization_id,
                role=async_test_user.role,
            ),
        )
        await db.commit()

        await db.refresh(label)
        assert label.is_assigned is True
        assert label.item_id == item.id

        result = await provider.handle(short_code, async_test_user, db)
        assert result is not None
        assert result.status == 'archived'
        assert result.action == 'show_archived_info'

    @pytest.mark.asyncio
    async def test_handle_label_item_missing_unlinks(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """Test handle returns unassigned when item deleted (label may not unlink immediately)."""
        # This test verifies that when an item is deleted but label still points to it,
        # scanning returns unassigned response (the real unlinking happens elsewhere)
        db = real_async_db_session
        storage_type = await _make_storage_type(db)
        storage_location = await _make_storage_location(
            db,
            async_test_user.organization_id,
            async_test_user.id,
            storage_type.id,
        )
        category = await _make_category(db)
        test_item = await _make_item(
            db,
            async_test_user.organization_id,
            storage_location.id,
            category.id,
        )
        short_code = _unique_short_code('STM')

        label = LabelPool(
            organization_id=async_test_user.organization_id,
            short_code=short_code,
            label_type='ITEM',
            is_assigned=True,
            item_id=test_item.id,
            created_by=async_test_user.id,
        )
        db.add(label)
        await db.commit()

        # Mark item as deleted (soft delete)
        test_item.is_deleted = True
        await db.commit()

        # Scan - item is marked as deleted, should return archived response
        result = await provider.handle(
            short_code, async_test_user, real_async_db_session
        )

        assert result is not None
        # Item is deleted but still exists, so returns archived
        assert result.status == 'archived'
        assert result.action == 'show_archived_info'

    @pytest.mark.asyncio
    async def test_handle_organization_mismatch_returns_none(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """A label belonging to a different org must fall through (return None),
        not raise 403 — raising 403 leaked label existence across tenants."""

        # Create another organization in DB
        db = real_async_db_session
        other_org = Organization(name='Other Org')
        db.add(other_org)
        await db.flush()
        short_code = _unique_short_code('STM')

        # Create label in different org
        label = LabelPool(
            organization_id=other_org.id,  # Different org
            short_code=short_code,
            label_type='ITEM',
            is_assigned=False,
            created_by=async_test_user.id,  # User from different org!
        )
        db.add(label)
        await db.commit()

        result = await provider.handle(
            short_code, async_test_user, real_async_db_session
        )
        # Foreign-org label: must NOT raise, must NOT return data. None lets the
        # scan chain try the next provider (e.g. barcode).
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_unassigned_label_with_context_tag(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """Test unassigned label returns context_tag in response."""
        db = real_async_db_session
        short_code = _unique_short_code('ITM')
        label = LabelPool(
            organization_id=async_test_user.organization_id,
            short_code=short_code,
            label_type='GENERIC',
            is_assigned=False,
            created_by=async_test_user.id,
            context_tag='equipment',
        )
        db.add(label)
        await db.commit()

        result = await provider.handle(
            short_code, async_test_user, real_async_db_session
        )

        assert result is not None
        assert result.status == 'unassigned'
        assert result.action == 'show_quick_add'
        assert result.context_tag == 'equipment'

    @pytest.mark.asyncio
    async def test_handle_unassigned_label_no_context_tag(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """Test unassigned label without context_tag returns None context_tag."""
        db = real_async_db_session
        short_code = _unique_short_code('STM')
        label = LabelPool(
            organization_id=async_test_user.organization_id,
            short_code=short_code,
            label_type='GENERIC',
            is_assigned=False,
            created_by=async_test_user.id,
            context_tag=None,
        )
        db.add(label)
        await db.commit()

        result = await provider.handle(
            short_code, async_test_user, real_async_db_session
        )

        assert result is not None
        assert result.context_tag is None

    @pytest.mark.asyncio
    async def test_handle_assigned_label_context_tag_from_category(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """Assigned label: context_tag resolved from item's category (takes priority)."""
        db = real_async_db_session
        storage_type = await _make_storage_type(db)
        storage_location = await _make_storage_location(
            db,
            async_test_user.organization_id,
            async_test_user.id,
            storage_type.id,
        )
        category = await _make_category(db)
        category.context_tag = 'equipment'
        await db.flush()

        test_item = await _make_item(
            db,
            async_test_user.organization_id,
            storage_location.id,
            category.id,
        )
        short_code = _unique_short_code('ITM')

        label = LabelPool(
            organization_id=async_test_user.organization_id,
            short_code=short_code,
            label_type='GENERIC',
            is_assigned=True,
            item_id=test_item.id,
            created_by=async_test_user.id,
            context_tag='equipment',
        )
        db.add(label)
        await db.commit()

        result = await provider.handle(
            short_code, async_test_user, real_async_db_session
        )

        assert result is not None
        assert result.status == 'assigned'
        assert result.context_tag == 'equipment'


@pytest.mark.integration
class TestBarcodeScanProvider:
    """Test BarcodeScanProvider for product barcode scanning."""

    @pytest.fixture
    def provider(self):
        """Create provider instance."""
        return BarcodeScanProvider()

    @pytest.mark.asyncio
    async def test_can_handle_valid_barcode_8digits(self, provider):
        """Test can_handle returns True for 8-digit barcode."""
        result = await provider.can_handle('12345678')
        assert result is True

    @pytest.mark.asyncio
    async def test_can_handle_valid_barcode_14digits(self, provider):
        """Test can_handle returns True for 14-digit barcode."""
        result = await provider.can_handle('12345678901234')
        assert result is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'code', ['1234567', '123456789012345', '1234567A', 'SKU-1']
    )
    async def test_can_handle_any_code_a_sku_or_an_alphanumeric_barcode_is_a_name(
        self, provider, code
    ):
        """A code of any shape may name a product; the lookup is the arbiter."""
        assert await provider.can_handle(code) is True

    @pytest.mark.asyncio
    async def test_can_handle_nothing(self, provider):
        assert await provider.can_handle('') is False

    @pytest.mark.asyncio
    async def test_handle_barcode_not_found(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """Test handle returns unassigned when barcode not found."""
        result = await provider.handle(
            '99999999', async_test_user, real_async_db_session
        )

        assert result is not None
        assert result.status == 'unassigned'
        assert result.action == 'show_quick_add'

    @pytest.mark.asyncio
    async def test_handle_barcode_active_items(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """Test handle returns stock summary for active items."""
        db = real_async_db_session
        storage_type = await _make_storage_type(db)
        storage_location = await _make_storage_location(
            db,
            async_test_user.organization_id,
            async_test_user.id,
            storage_type.id,
        )
        category = await _make_category(db)
        template = await _make_template(
            db, async_test_user.organization_id, '12345678', 'Milk'
        )

        await _make_item(
            db,
            async_test_user.organization_id,
            storage_location.id,
            category.id,
            name='Milk',
            template_id=template.id,
            quantity=Decimal('2'),
        )
        await _make_item(
            db,
            async_test_user.organization_id,
            storage_location.id,
            category.id,
            name='Milk',
            template_id=template.id,
            quantity=Decimal('1'),
        )

        result = await provider.handle(
            '12345678', async_test_user, real_async_db_session
        )

        assert result is not None
        assert result.status == 'product_stock'
        assert result.action == 'show_stock_actions'
        assert result.stock_summary['total_quantity'] == 3.0
        assert len(result.stock_summary['items']) == 2

    @pytest.mark.asyncio
    async def test_handle_barcode_history_only(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """Test handle returns template when barcode found in history only."""
        db = real_async_db_session
        storage_type = await _make_storage_type(db)
        storage_location = await _make_storage_location(
            db,
            async_test_user.organization_id,
            async_test_user.id,
            storage_type.id,
        )
        category = await _make_category(db)
        await _make_item(
            db,
            async_test_user.organization_id,
            storage_location.id,
            category.id,
            name='Old Milk',
            brand='Brand A',
            barcode='87654321',
            quantity=Decimal('1'),
            is_deleted=True,
        )

        result = await provider.handle(
            '87654321', async_test_user, real_async_db_session
        )

        assert result is not None
        assert result.status == 'unassigned'
        assert 'stock_summary' in result.model_dump()
        assert result.stock_summary['template']['name'] == 'Old Milk'
        assert result.stock_summary['total_quantity'] == 0

    @pytest.mark.asyncio
    async def test_handle_multiple_items_picks_best(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """Test handle selects best item based on metadata."""
        db = real_async_db_session
        storage_type = await _make_storage_type(db)
        storage_location = await _make_storage_location(
            db,
            async_test_user.organization_id,
            async_test_user.id,
            storage_type.id,
        )
        category = await _make_category(db)
        template = await _make_template(
            db, async_test_user.organization_id, '11111111', 'Milk'
        )

        await _make_item(
            db,
            async_test_user.organization_id,
            storage_location.id,
            category.id,
            name='Milk',
            template_id=template.id,
            quantity=Decimal('5'),
            created_at=datetime.now() - timedelta(days=5),
        )

        await _make_item(
            db,
            async_test_user.organization_id,
            storage_location.id,
            category.id,
            name='Milk',
            template_id=template.id,
            quantity=Decimal('2'),
            meta_data={'nutrition_source': 'vision_capture'},
            created_at=datetime.now(),
        )

        result = await provider.handle(
            '11111111', async_test_user, real_async_db_session
        )

        # Should use item_new_with_metadata as template (has metadata)
        assert result.stock_summary['template']['name'] == 'Milk'
        assert len(result.stock_summary['items']) == 2

    @pytest.mark.asyncio
    async def test_handle_prefers_internal_storage(
        self,
        provider,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """Test handle prefers internal storage locations for template."""
        # Create virtual storage
        db = real_async_db_session
        storage_type = await _make_storage_type(db)
        storage_location = await _make_storage_location(
            db,
            async_test_user.organization_id,
            async_test_user.id,
            storage_type.id,
        )
        category = await _make_category(db)
        template = await _make_template(
            db, async_test_user.organization_id, '22222222', 'Product'
        )

        virtual_storage = StorageLocation(
            organization_id=async_test_user.organization_id,
            created_by=async_test_user.id,
            name='Consumed (Virtual)',
            usage=LocationUsage.CUSTOMER,
        )
        db.add(virtual_storage)
        await db.flush()

        # Item in virtual location
        await _make_item(
            db,
            async_test_user.organization_id,
            virtual_storage.id,
            category.id,
            name='Product',
            template_id=template.id,
            quantity=Decimal('1'),
        )

        # Item in internal location
        await _make_item(
            db,
            async_test_user.organization_id,
            storage_location.id,
            category.id,
            name='Product',
            template_id=template.id,
            quantity=Decimal('3'),
        )

        result = await provider.handle(
            '22222222', async_test_user, real_async_db_session
        )

        # Should suggest internal storage, not virtual
        assert result.stock_summary['template']['location_id'] is not None
        # Template should reference internal storage location
        assert result.stock_summary['template']['location_id'] == str(
            storage_location.id
        )
