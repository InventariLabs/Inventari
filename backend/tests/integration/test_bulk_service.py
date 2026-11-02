"""
Integration tests for bulk_service (bulk update + import).

Tests cover:
- bulk_update_items: name update, quantity change, empty update_data, no matching items
- import_items: CSV import, missing name row skipped, invalid file raises ValueError
"""

from decimal import Decimal
from io import BytesIO

import pandas as pd
import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.product_template import ProductTemplate
from app.schemas.item import ItemBulkUpdate, ItemUpdate
from app.services.items._bulk_update import bulk_update_items
from app.services.items._import import import_items


def _make_user_ctx(user):
    """The caller as the services see it."""
    from app.core.contracts import UserContextDTO

    return UserContextDTO(
        organization_id=user.organization_id,
        id=user.id,
        role='admin',
    )


@pytest.mark.integration
@pytest.mark.asyncio
class TestBulkUpdateItems:
    """Tests for bulk_update_items."""

    async def test_bulk_update_name(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_item
    ):
        """Bulk update changes item name."""
        bulk_data = ItemBulkUpdate(
            item_ids=[async_test_item.id],
            update_data=ItemUpdate(name='Updated Name'),
        )
        user_ctx = _make_user_ctx(async_test_user)

        count = await bulk_update_items(real_async_db_session, bulk_data, user_ctx)
        assert count == 1

        await real_async_db_session.refresh(async_test_item)
        assert async_test_item.name == 'Updated Name'

    async def test_bulk_update_brand(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_item
    ):
        """Bulk update changes item brand."""
        bulk_data = ItemBulkUpdate(
            item_ids=[async_test_item.id],
            update_data=ItemUpdate(brand='New Brand'),
        )
        user_ctx = _make_user_ctx(async_test_user)

        count = await bulk_update_items(real_async_db_session, bulk_data, user_ctx)
        assert count == 1

        await real_async_db_session.refresh(async_test_item)
        assert async_test_item.brand == 'New Brand'

    async def test_bulk_update_empty_update_data_returns_zero(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_item
    ):
        """Empty update_data (no fields set) returns 0."""
        bulk_data = ItemBulkUpdate(
            item_ids=[async_test_item.id],
            update_data=ItemUpdate(),
        )
        user_ctx = _make_user_ctx(async_test_user)

        count = await bulk_update_items(real_async_db_session, bulk_data, user_ctx)
        assert count == 0

    async def test_bulk_update_nonexistent_item_returns_zero(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """No matching items returns 0."""
        import uuid

        bulk_data = ItemBulkUpdate(
            item_ids=[uuid.uuid4()],
            update_data=ItemUpdate(name='Ghost'),
        )
        user_ctx = _make_user_ctx(async_test_user)

        count = await bulk_update_items(real_async_db_session, bulk_data, user_ctx)
        assert count == 0

    async def test_bulk_update_multiple_items(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_items_batch,
    ):
        """Bulk update applies to multiple items at once."""
        ids = [item.id for item in async_test_items_batch[:3]]
        bulk_data = ItemBulkUpdate(
            item_ids=ids,
            update_data=ItemUpdate(brand='Bulk Brand'),
        )
        user_ctx = _make_user_ctx(async_test_user)

        count = await bulk_update_items(real_async_db_session, bulk_data, user_ctx)
        assert count == 3

        for item in async_test_items_batch[:3]:
            await real_async_db_session.refresh(item)
            assert item.brand == 'Bulk Brand'

    async def test_bulk_update_creates_history(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_item
    ):
        """Each bulk-updated item gets a history entry."""
        bulk_data = ItemBulkUpdate(
            item_ids=[async_test_item.id],
            update_data=ItemUpdate(name='History Test'),
        )
        user_ctx = _make_user_ctx(async_test_user)

        await bulk_update_items(real_async_db_session, bulk_data, user_ctx)

        history = (
            await real_async_db_session.scalars(
                select(ItemHistory).where(ItemHistory.item_id == async_test_item.id)
            )
        ).all()
        assert len(history) >= 1
        assert any(h.action == 'UPDATED' for h in history)

    async def test_bulk_update_excludes_deleted_items(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_item
    ):
        """Soft-deleted items are not updated by bulk_update."""
        async_test_item.is_deleted = True
        await real_async_db_session.commit()

        bulk_data = ItemBulkUpdate(
            item_ids=[async_test_item.id],
            update_data=ItemUpdate(name='Should Not Apply'),
        )
        user_ctx = _make_user_ctx(async_test_user)

        count = await bulk_update_items(real_async_db_session, bulk_data, user_ctx)
        assert count == 0

    async def test_bulk_update_quantity(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_item
    ):
        """Bulk update can change item quantity."""
        bulk_data = ItemBulkUpdate(
            item_ids=[async_test_item.id],
            update_data=ItemUpdate(quantity=Decimal('10')),
        )
        user_ctx = _make_user_ctx(async_test_user)

        count = await bulk_update_items(real_async_db_session, bulk_data, user_ctx)
        assert count == 1

        await real_async_db_session.refresh(async_test_item)
        assert async_test_item.quantity == Decimal('10')

    async def test_bulk_update_shelf_location(
        self, real_async_db_session: AsyncSession, async_test_user, async_test_item
    ):
        """Bulk update can change shelf_location."""
        bulk_data = ItemBulkUpdate(
            item_ids=[async_test_item.id],
            update_data=ItemUpdate(shelf_location='New Shelf'),
        )
        user_ctx = _make_user_ctx(async_test_user)

        count = await bulk_update_items(real_async_db_session, bulk_data, user_ctx)
        assert count == 1

        await real_async_db_session.refresh(async_test_item)
        assert async_test_item.shelf_location == 'New Shelf'


@pytest.mark.integration
@pytest.mark.asyncio
class TestImportItems:
    """Tests for import_items."""

    def _make_xlsx_bytes(self, rows: list[dict]) -> bytes:
        """Helper: build an XLSX file in memory from a list of row dicts."""
        df = pd.DataFrame(rows)
        buf = BytesIO()
        df.to_excel(buf, index=False)
        return buf.getvalue()

    def _make_csv_bytes(self, rows: list[dict]) -> bytes:
        """Helper: build a CSV file in memory from a list of row dicts."""
        df = pd.DataFrame(rows)
        return df.to_csv(index=False).encode()

    async def test_import_refuses_more_rows_than_the_limit(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
    ):
        """the byte cap does not bound row count — a small CSV can
        carry hundreds of thousands of rows, each costing lookups and inserts
        inside one request."""
        from app.core.upload_validation import MAX_IMPORT_ROWS

        csv = self._make_csv_bytes(
            [{'Name': f'Row {i}', 'Quantity': 1} for i in range(MAX_IMPORT_ROWS + 1)]
        )
        mapping = {'name': 'Name', 'quantity': 'Quantity'}

        with pytest.raises(ValueError, match='limit'):
            await import_items(
                db=real_async_db_session,
                file_content=csv,
                filename='big.csv',
                mapping=mapping,
                user=_make_user_ctx(async_test_user),
            )

    async def test_import_xlsx_basic(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
        async_test_category,
    ):
        """Import a simple XLSX file creates items."""
        xlsx = self._make_xlsx_bytes(
            [
                {'Name': 'Import A', 'Quantity': 3},
                {'Name': 'Import B', 'Quantity': 1},
            ]
        )
        mapping = {'name': 'Name', 'quantity': 'Quantity'}
        user_ctx = _make_user_ctx(async_test_user)

        result = await import_items(
            real_async_db_session,
            xlsx,
            'test.xlsx',
            mapping,
            user_ctx,
            create_missing_locations=False,
            create_missing_categories=False,
        )
        assert result['total'] == 2
        assert result['imported'] == 2
        assert result['failed'] == 0

    async def test_import_csv_basic(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ):
        """Import a simple CSV file creates items."""
        csv_bytes = self._make_csv_bytes(
            [
                {'Name': 'CSV Item', 'Qty': 5},
            ]
        )
        mapping = {'name': 'Name', 'quantity': 'Qty'}
        user_ctx = _make_user_ctx(async_test_user)

        result = await import_items(
            real_async_db_session,
            csv_bytes,
            'test.csv',
            mapping,
            user_ctx,
            create_missing_locations=False,
            create_missing_categories=False,
        )
        assert result['total'] == 1
        assert result['imported'] == 1

    async def test_import_missing_name_skips_row(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ):
        """Rows where the name column maps to a missing column are counted as failed."""
        csv_bytes = self._make_csv_bytes(
            [
                {'Name': 'Valid Item'},
                {'Name': 'Valid Item 2'},
            ]
        )
        mapping = {'name': 'NonexistentColumn'}
        user_ctx = _make_user_ctx(async_test_user)

        result = await import_items(
            real_async_db_session,
            csv_bytes,
            'test.csv',
            mapping,
            user_ctx,
            create_missing_locations=False,
            create_missing_categories=False,
        )
        assert result['total'] == 2
        assert result['imported'] == 0
        assert result['failed'] == 2
        assert all('Missing product name' in e['error'] for e in result['errors'])

    async def test_import_invalid_file_raises_valueerror(
        self, real_async_db_session: AsyncSession, async_test_user
    ):
        """Garbage file content raises ValueError."""
        user_ctx = _make_user_ctx(async_test_user)

        with pytest.raises(ValueError, match='could not be read as a spreadsheet'):
            await import_items(
                real_async_db_session,
                b'not a real file',
                'test.xlsx',
                {'name': 'Name'},
                user_ctx,
            )

    async def test_import_with_brand_and_barcode(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ):
        """Import correctly maps brand and barcode columns."""
        xlsx = self._make_xlsx_bytes(
            [
                {'Name': 'Branded', 'Brand': 'Acme', 'Barcode': '123456'},
            ]
        )
        mapping = {'name': 'Name', 'brand': 'Brand', 'barcode': 'Barcode'}
        user_ctx = _make_user_ctx(async_test_user)

        result = await import_items(
            real_async_db_session,
            xlsx,
            'test.xlsx',
            mapping,
            user_ctx,
            create_missing_locations=False,
            create_missing_categories=False,
        )
        assert result['imported'] == 1

        item = (
            await real_async_db_session.scalars(
                select(Item).where(Item.name == 'Branded')
            )
        ).first()
        assert item is not None
        assert item.brand == 'Acme'
        # The imported code is the product's: it sits on the template the
        # row links to, not on the record.
        assert item.barcode is None
        template = (
            await real_async_db_session.scalars(
                select(ProductTemplate).where(ProductTemplate.id == item.template_id)
            )
        ).first()
        assert template is not None
        assert template.barcode == '123456'

    async def test_import_with_category_lookup(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ):
        """Import maps category name to existing category."""
        cat = Category(
            name='TestCat',
            organization_id=async_test_user.organization_id,
        )
        real_async_db_session.add(cat)
        await real_async_db_session.commit()

        xlsx = self._make_xlsx_bytes(
            [
                {'Name': 'Categorized', 'Cat': 'TestCat'},
            ]
        )
        mapping = {'name': 'Name', 'category': 'Cat'}
        user_ctx = _make_user_ctx(async_test_user)

        result = await import_items(
            real_async_db_session,
            xlsx,
            'test.xlsx',
            mapping,
            user_ctx,
            create_missing_locations=False,
            create_missing_categories=False,
        )
        assert result['imported'] == 1

        item = (
            await real_async_db_session.scalars(
                select(Item).where(Item.name == 'Categorized')
            )
        ).first()
        assert item is not None
        assert item.category_id == cat.id

    async def test_import_creates_missing_category(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ):
        """Import creates a new category when create_missing_categories=True."""
        xlsx = self._make_xlsx_bytes(
            [
                {'Name': 'New Cat Item', 'Cat': 'Brand New Category'},
            ]
        )
        mapping = {'name': 'Name', 'category': 'Cat'}
        user_ctx = _make_user_ctx(async_test_user)

        result = await import_items(
            real_async_db_session,
            xlsx,
            'test.xlsx',
            mapping,
            user_ctx,
            create_missing_locations=False,
            create_missing_categories=True,
        )
        assert result['imported'] == 1

        cat = (
            await real_async_db_session.scalars(
                select(Category).where(Category.name == 'Brand New Category')
            )
        ).first()
        assert cat is not None

    async def test_import_default_quantity_is_one(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ):
        """Items imported without quantity column default to 1."""
        xlsx = self._make_xlsx_bytes(
            [
                {'Name': 'Default Qty', 'Tag': 'x'},
            ]
        )
        mapping = {'name': 'Name'}
        user_ctx = _make_user_ctx(async_test_user)

        result = await import_items(
            real_async_db_session,
            xlsx,
            'test.xlsx',
            mapping,
            user_ctx,
            create_missing_locations=False,
            create_missing_categories=False,
        )
        assert result['imported'] == 1

        item = (
            await real_async_db_session.scalars(
                select(Item).where(Item.name == 'Default Qty')
            )
        ).first()
        assert item is not None
        assert item.quantity == Decimal('1.0')

    async def test_import_errors_limited_to_ten(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ):
        """Error list is capped at 10 entries."""
        rows = [{'Name': f'Item {i}', 'Tag': str(i)} for i in range(15)]
        csv_bytes = self._make_csv_bytes(rows)
        mapping = {'name': 'NonexistentCol'}
        user_ctx = _make_user_ctx(async_test_user)

        result = await import_items(
            real_async_db_session,
            csv_bytes,
            'test.csv',
            mapping,
            user_ctx,
            create_missing_locations=False,
            create_missing_categories=False,
        )
        assert result['failed'] == 15
        assert len(result['errors']) == 10

    async def test_import_with_purchase_price(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ):
        """Import correctly maps purchase_price column."""
        xlsx = self._make_xlsx_bytes(
            [
                {'Name': 'Priced Import', 'Price': 12.50},
            ]
        )
        mapping = {'name': 'Name', 'purchase_price': 'Price'}
        user_ctx = _make_user_ctx(async_test_user)

        result = await import_items(
            real_async_db_session,
            xlsx,
            'test.xlsx',
            mapping,
            user_ctx,
            create_missing_locations=False,
            create_missing_categories=False,
        )
        assert result['imported'] == 1

        item = (
            await real_async_db_session.scalars(
                select(Item).where(Item.name == 'Priced Import')
            )
        ).first()
        assert item is not None
        assert item.purchase_price == Decimal('12.50')

    async def test_import_empty_quantity_cell_is_refused_instead_of_nan_or_one(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ):
        """An empty quantity cell in a mapped column refuses the row.

        Pandas reads the empty cell as float('nan'), which is not None, so an
        old None-only gate stored NaN; the poisoned row then 400'd the whole
        items list. The cell then became a silent 1. It is neither now: the
        row is refused and nothing is stored."""
        xlsx = self._make_xlsx_bytes(
            [
                {'Name': 'Empty Qty', 'Quantity': None},
            ]
        )
        mapping = {'name': 'Name', 'quantity': 'Quantity'}
        user_ctx = _make_user_ctx(async_test_user)

        result = await import_items(
            real_async_db_session,
            xlsx,
            'test.xlsx',
            mapping,
            user_ctx,
            create_missing_locations=False,
            create_missing_categories=False,
        )
        assert result['imported'] == 0
        assert result['failed'] == 1
        assert 'the quantity is empty' in result['errors'][0]['error']

        item = (
            await real_async_db_session.scalars(
                select(Item).where(Item.name == 'Empty Qty')
            )
        ).first()
        assert item is None

    async def test_import_empty_purchase_price_cell_stays_none(
        self,
        real_async_db_session: AsyncSession,
        async_test_user,
        async_test_storage_location,
    ):
        """An empty purchase_price cell imports None, not Decimal('NaN').

        Same mechanism as the empty quantity cell: the column is
        numeric, pandas reads the gap as float('nan')."""
        xlsx = self._make_xlsx_bytes(
            [
                {'Name': 'No Price', 'Quantity': 2, 'Price': None},
            ]
        )
        mapping = {'name': 'Name', 'quantity': 'Quantity', 'purchase_price': 'Price'}
        user_ctx = _make_user_ctx(async_test_user)

        result = await import_items(
            real_async_db_session,
            xlsx,
            'test.xlsx',
            mapping,
            user_ctx,
            create_missing_locations=False,
            create_missing_categories=False,
        )
        assert result['imported'] == 1

        item = (
            await real_async_db_session.scalars(
                select(Item).where(Item.name == 'No Price')
            )
        ).first()
        assert item is not None
        assert item.purchase_price is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestQuantityFiniteGuard:
    """The column type — not the Pydantic schema — is the write gate."""

    async def test_core_update_with_nan_quantity_raises(
        self,
        real_async_db_session: AsyncSession,
        async_test_item,
    ):
        """A raw Core ``update()`` bypasses every Pydantic schema; the column
        type itself must refuse the write, on the ORM flush path alike."""
        stmt = (
            update(Item)
            .where(Item.id == async_test_item.id)
            .values(quantity=Decimal('NaN'))
        )
        with pytest.raises((ValueError, StatementError), match='finite'):
            await real_async_db_session.execute(stmt)
        await real_async_db_session.rollback()

    async def test_core_update_with_infinite_quantity_raises(
        self,
        real_async_db_session: AsyncSession,
        async_test_item,
    ):
        """Infinity cannot reach the column either."""
        stmt = (
            update(Item)
            .where(Item.id == async_test_item.id)
            .values(quantity=Decimal('Infinity'))
        )
        with pytest.raises((ValueError, StatementError), match='finite'):
            await real_async_db_session.execute(stmt)
        await real_async_db_session.rollback()
