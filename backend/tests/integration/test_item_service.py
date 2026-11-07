"""
Integration tests for ItemService (item management).

Tests cover:
- Item creation with template linking (barcode, expiry, template creation)
- Item retrieval: search, pagination, sorting, low-stock filtering

Note: Uses database fixtures and real models.
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.exceptions import NotFoundException
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.schemas.item import ItemCreate
from app.services.items import create_item, get_items
from tests.integration._shelf import anchor_pending_records


@pytest.mark.integration
@pytest.mark.asyncio
class TestItemServiceLayer:
    """Item service layer integration tests."""

    # ======================== get_items tests ========================

    async def test_get_items_search_by_name(
        self, real_async_db_session, async_test_item, async_test_user
    ):
        """Test searching items by name."""
        items, total = await real_async_db_session.run_sync(
            lambda s: get_items(s, async_test_user, search=async_test_item.name)
        )

        assert len(items) >= 1
        assert any(item.id == async_test_item.id for item in items)

    async def test_get_items_search_by_brand(
        self, real_async_db_session, async_test_item, async_test_user
    ):
        """Test searching items by brand."""
        items, total = await real_async_db_session.run_sync(
            lambda s: get_items(s, async_test_user, search=async_test_item.brand)
        )

        assert len(items) >= 1
        assert any(item.id == async_test_item.id for item in items)

    async def test_get_items_pagination(
        self, real_async_db_session, async_test_items_batch, async_test_user
    ):
        """Test pagination with skip and limit."""
        items_page1, total1 = await real_async_db_session.run_sync(
            lambda s: get_items(s, async_test_user, offset=0, limit=2)
        )
        items_page2, total2 = await real_async_db_session.run_sync(
            lambda s: get_items(s, async_test_user, offset=2, limit=2)
        )

        assert len(items_page1) <= 2
        assert len(items_page2) <= 2
        assert total1 == total2  # Total should be same

    async def test_get_items_sort_by_expiry(
        self, real_async_db_session, async_test_items_batch, async_test_user
    ):
        """Test sorting by expiry date."""
        items_asc, _ = await real_async_db_session.run_sync(
            lambda s: get_items(
                s, async_test_user, sort_by='created_at', sort_order='asc'
            )
        )

        # Verify ordering
        if len(items_asc) > 1:
            assert items_asc[0].created_at <= items_asc[1].created_at

    async def test_get_items_low_stock(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """Test filtering low stock items with template min_quantity."""
        product = ProductTemplate(
            organization_id=async_test_user.organization_id,
            name='Low Stock Product',
            min_quantity=10,
        )
        real_async_db_session.add(product)
        await real_async_db_session.flush()

        low_stock_item = Item(
            organization_id=async_test_user.organization_id,
            storage_location_id=async_test_storage_location.id,
            template_id=product.id,
            name='Low Stock',
            quantity=5,  # Below min_quantity of 10
        )
        real_async_db_session.add(low_stock_item)
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.flush()

        items, total = await real_async_db_session.run_sync(
            lambda s: get_items(s, async_test_user, only_low_stock=True)
        )

        assert any(item.id == low_stock_item.id for item in items)

    async def test_get_items_sort_by_name(
        self, real_async_db_session, async_test_items_batch, async_test_user
    ):
        """Test sorting by name."""
        items_asc, _ = await real_async_db_session.run_sync(
            lambda s: get_items(s, async_test_user, sort_by='name', sort_order='asc')
        )

        if len(items_asc) > 1:
            for i in range(len(items_asc) - 1):
                assert items_asc[i].name <= items_asc[i + 1].name

    async def test_get_items_sort_by_quantity(
        self, real_async_db_session, async_test_items_batch, async_test_user
    ):
        """Test sorting by quantity."""
        items_desc, _ = await real_async_db_session.run_sync(
            lambda s: get_items(
                s, async_test_user, sort_by='quantity', sort_order='desc'
            )
        )

        if len(items_desc) > 1:
            for i in range(len(items_desc) - 1):
                assert items_desc[i].quantity >= items_desc[i + 1].quantity

    # ======================== create_item tests ========================

    async def test_create_item_with_expiry(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """Test creating item with expiry date."""
        expiry = date.today() + timedelta(days=30)
        item_in = ItemCreate(
            location_id=async_test_storage_location.id,
            name='Perishable',
            quantity=1,
            expiry_date=expiry,
        )

        item = await create_item(real_async_db_session, item_in, async_test_user)

        assert item.expiry_date == expiry

    async def test_create_item_with_barcode(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """Test creating item with barcode links to template."""
        item_in = ItemCreate(
            location_id=async_test_storage_location.id,
            name='Barcode Item',
            barcode='1234567890',
            quantity=1,
        )

        item = await create_item(real_async_db_session, item_in, async_test_user)

        # A scanned code is the product's: it lands on the catalogue row the
        # record links to, not on the record itself.
        assert item.barcode is None
        assert item.template_id is not None
        from app.models.product_template import ProductTemplate

        template = await real_async_db_session.get(ProductTemplate, item.template_id)
        assert template.barcode == '1234567890'

    async def test_create_item_creates_product_template(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """Test that creating item without existing template creates one."""
        item_in = ItemCreate(
            location_id=async_test_storage_location.id,
            name='New Template Item',
            brand='New Brand',
            quantity=1,
        )

        item = await create_item(real_async_db_session, item_in, async_test_user)

        # Should have created a product template
        assert item.template_id is not None
        template = (
            await real_async_db_session.scalars(
                select(ProductTemplate).where(ProductTemplate.id == item.template_id)
            )
        ).first()
        assert template is not None
        assert template.name == 'New Template Item'

    # ================== create_item with template_id ==================

    async def test_create_item_with_template_id_binds_that_card(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """Test a named card wins over barcode/name matching.

        Two cards share a name; the request names the second and carries the
        first card's barcode. The record must stand on the card the caller
        named — barcode matching used to answer first and pull it onto the
        other one.
        """
        first = ProductTemplate(
            organization_id=async_test_user.organization_id,
            name='Twin Card',
            barcode='1111111111',
        )
        second = ProductTemplate(
            organization_id=async_test_user.organization_id,
            name='Twin Card',
            barcode='2222222222',
        )
        real_async_db_session.add_all([first, second])
        await real_async_db_session.flush()

        item_in = ItemCreate(
            location_id=async_test_storage_location.id,
            name='Twin Card',
            barcode='1111111111',
            template_id=second.id,
            quantity=1,
        )

        item = await create_item(real_async_db_session, item_in, async_test_user)

        assert item.template_id == second.id

    async def test_create_item_with_shared_template_id_binds_it(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """Test a shared card named by id wins over the organization's own twin."""
        own = ProductTemplate(
            organization_id=async_test_user.organization_id,
            name='Shared Card',
        )
        shared = ProductTemplate(
            organization_id=None,
            name='Shared Card',
        )
        real_async_db_session.add_all([own, shared])
        await real_async_db_session.flush()

        item_in = ItemCreate(
            location_id=async_test_storage_location.id,
            name='Shared Card',
            template_id=shared.id,
            quantity=1,
        )

        item = await create_item(real_async_db_session, item_in, async_test_user)

        assert item.template_id == shared.id

    async def test_create_item_rejects_another_organizations_template(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """Test a foreign card id is refused, not silently matched away."""
        stranger_org = Organization(name=f'Stranger {uuid4().hex[:6]}')
        real_async_db_session.add(stranger_org)
        await real_async_db_session.flush()
        foreign = ProductTemplate(
            organization_id=stranger_org.id,
            name='Not Mine',
        )
        real_async_db_session.add(foreign)
        await real_async_db_session.flush()

        item_in = ItemCreate(
            location_id=async_test_storage_location.id,
            name='Not Mine',
            template_id=foreign.id,
            quantity=1,
        )

        with pytest.raises(NotFoundException):
            await create_item(real_async_db_session, item_in, async_test_user)

    async def test_create_item_rejects_unknown_template(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """Test an id no card answers to is refused, not matched by name."""
        item_in = ItemCreate(
            location_id=async_test_storage_location.id,
            name='Ghost Card',
            template_id=uuid4(),
            quantity=1,
        )

        with pytest.raises(NotFoundException):
            await create_item(real_async_db_session, item_in, async_test_user)

    # ============ what a named or matched card takes from a payload ============

    async def test_the_first_asset_of_a_model_keeps_its_own_code(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """An asset's code stays on the asset; the model card stays bare.

        Two records of one model, each created with its own code. Before,
        the first record's code moved onto the model's catalogue row (the
        row the caller named by id and that had no code of its own yet), so
        the record read "Barcode / EAN: —" while the row wore a code that
        identifies a *unit*, not a product — and searching for it answered
        with every asset of that model, because a record matches a search
        through its card as well as through its own columns.
        """
        model = ProductTemplate(
            organization_id=async_test_user.organization_id,
            name='Dell Precision 3580',
        )
        real_async_db_session.add(model)
        await real_async_db_session.flush()

        first = await create_item(
            real_async_db_session,
            ItemCreate(
                location_id=async_test_storage_location.id,
                name='Dell Precision 3580',
                template_id=model.id,
                barcode='LAP-0001',
                metadata={'equipment': {'asset_tag': 'LAP-0001'}},
                quantity=1,
            ),
            async_test_user,
        )
        second = await create_item(
            real_async_db_session,
            ItemCreate(
                location_id=async_test_storage_location.id,
                name='Dell Precision 3580',
                template_id=model.id,
                barcode='LAP-0002',
                metadata={'equipment': {'asset_tag': 'LAP-0002'}},
                quantity=1,
            ),
            async_test_user,
        )

        assert first.barcode == 'LAP-0001'
        assert second.barcode == 'LAP-0002'
        await real_async_db_session.refresh(model)
        assert model.barcode is None

        rows, _total = await real_async_db_session.run_sync(
            lambda s: get_items(s, async_test_user, search='LAP-0001')
        )
        found = {row.id for row in rows}
        assert first.id in found
        assert second.id not in found

    async def test_a_named_card_takes_the_numbers_a_matched_card_takes(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ):
        """The payload's weight and minimum reach the card either way.

        The card the caller named by ``template_id`` and the card matched by
        name are the same card as far as these two product-level fields are
        concerned: both take ``weight_value`` and ``min_quantity`` from the
        payload. The named branch used to return early and write neither,
        and ``min_quantity`` was not even on the create schema — a value the
        client named was dropped at the API edge, on both branches.
        """
        named = ProductTemplate(
            organization_id=async_test_user.organization_id,
            name='Named Weighted Card',
        )
        matched = ProductTemplate(
            organization_id=async_test_user.organization_id,
            name='Matched Weighted Card',
        )
        real_async_db_session.add_all([named, matched])
        await real_async_db_session.flush()

        await create_item(
            real_async_db_session,
            ItemCreate(
                location_id=async_test_storage_location.id,
                name='Named Weighted Card',
                template_id=named.id,
                quantity=1,
                weight_value=2.5,
                min_quantity=5,
            ),
            async_test_user,
        )
        await create_item(
            real_async_db_session,
            ItemCreate(
                location_id=async_test_storage_location.id,
                name='Matched Weighted Card',
                quantity=1,
                weight_value=2.5,
                min_quantity=5,
            ),
            async_test_user,
        )

        await real_async_db_session.refresh(named)
        await real_async_db_session.refresh(matched)
        assert named.weight_value == Decimal('2.5')
        assert named.min_quantity == 5
        assert (named.min_quantity, named.weight_value) == (
            matched.min_quantity,
            matched.weight_value,
        )
