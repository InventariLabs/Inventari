"""
Integration tests for shopping suggestions service.

Tests verify the business logic for generating shopping suggestions:
1. Low stock items (quantity <= min_quantity)
2. Frequently consumed items (consumption in last 30 days)
3. Items expiring soon (expiry_date within n days)
4. Duplicate filtering
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.item import Item
from app.models.item_history import ItemHistory
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.models.uom import Uom
from app.models.user import User
from app.modules.shopping_lists import shopping_suggestions_service
from app.modules.shopping_lists.shopping_suggestions_service import (
    ShoppingSuggestion,
    filter_duplicate_suggestions,
    generate_suggestions,
)
from tests.integration._far_clock import zone_where_today_differs
from tests.integration._shelf import anchor_pending_records


@pytest.fixture
async def uom_kg(real_async_db_session: AsyncSession) -> Uom:
    """Gets kilogram UOM from seeded data."""
    uom = (
        await real_async_db_session.scalars(select(Uom).where(Uom.symbol == 'kg'))
    ).first()
    assert uom is not None, 'kg UOM should be seeded in conftest'
    return uom


@pytest.fixture
async def product_template_with_min(
    real_async_db_session: AsyncSession,
    async_test_household: Organization,
    uom_kg: Uom,
) -> ProductTemplate:
    """Creates product template with min_quantity threshold."""
    template = ProductTemplate(
        organization_id=async_test_household.id,
        name='Chicken Breast',
        brand='Premium Farms',
        barcode='1234567890',
        uom_id=uom_kg.id,
        min_quantity=Decimal('2.0'),
    )
    real_async_db_session.add(template)
    await real_async_db_session.commit()
    await real_async_db_session.refresh(template)
    return template


@pytest.mark.integration
class TestShoppingSuggestionsService:
    """Test suite for shopping suggestions generation."""

    @pytest.fixture
    async def uom_l(self, real_async_db_session: AsyncSession) -> Uom:
        """Gets liter UOM from seeded data."""
        uom = (
            await real_async_db_session.scalars(select(Uom).where(Uom.symbol == 'l'))
        ).first()
        if not uom:
            # If not seeded, find any volume UOM as alternative
            uom = (
                await real_async_db_session.scalars(
                    select(Uom).where(Uom.name.ilike('%liter%'))
                )
            ).first()
        assert uom is not None, 'Should have a volume UOM seeded'
        return uom

    @pytest.fixture
    async def product_template_global(
        self, real_async_db_session: AsyncSession, uom_kg: Uom
    ) -> ProductTemplate:
        """Creates global product template (no organization)."""
        template = ProductTemplate(
            organization_id=None,
            name='Generic Tomato',
            brand='Generic',
            uom_id=uom_kg.id,
            min_quantity=Decimal('1.0'),
        )
        real_async_db_session.add(template)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(template)
        return template

    @pytest.fixture
    async def category_meat(self, real_async_db_session: AsyncSession) -> Category:
        """Creates meat category."""
        category = Category(name='Meat', icon='🥩', sort_order=1)
        real_async_db_session.add(category)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(category)
        return category

    async def test_low_stock_items_basic(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        product_template_with_min: ProductTemplate,
        category_meat: Category,
    ) -> None:
        """Test detection of low stock items below min_quantity threshold."""
        # Create item with qty < min_quantity (qty=1, min=2)
        item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            template_id=product_template_with_min.id,
            category_id=category_meat.id,
            name='Chicken Breast - 1kg',
            quantity=Decimal('1.0'),
            expiry_date=date.today() + timedelta(days=30),
        )
        real_async_db_session.add(item)
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.commit()

        # Generate suggestions
        suggestions = await generate_suggestions(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            include_low_stock=True,
            include_frequent=False,
            include_expiring=False,
        )

        # Verify
        assert len(suggestions) == 1
        suggestion = suggestions[0]
        assert suggestion.name == 'Chicken Breast'
        assert suggestion.source == 'auto_low_stock'
        assert suggestion.priority == 1
        assert suggestion.unit == 'kg'
        assert suggestion.item_id is None  # Template-based suggestion
        # The template is the row's identity: a name is not unique in an
        # organization, the template it belongs to is.
        assert suggestion.template_id == product_template_with_min.id

    async def test_two_templates_with_the_same_name_keep_their_own_identity(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
        product_template_with_min: ProductTemplate,
        uom_kg: Uom,
    ) -> None:
        """Two templates may share a name; only the template id tells them apart.

        Before the template travelled on the suggestion, every reader
        downstream saw one product — the modal's row key collided, so
        ticking one row ticked both, and one "add" put two identical rows
        on the list.
        """
        other = ProductTemplate(
            organization_id=async_test_household.id,
            name=product_template_with_min.name,
            brand='Other Farm',
            uom_id=uom_kg.id,
            min_quantity=Decimal('2.0'),
        )
        real_async_db_session.add(other)
        await real_async_db_session.commit()
        await real_async_db_session.refresh(other)

        for template in (product_template_with_min, other):
            real_async_db_session.add(
                Item(
                    organization_id=async_test_household.id,
                    storage_location_id=async_test_storage_location.id,
                    template_id=template.id,
                    name=f'{template.name} — {template.brand}',
                    quantity=Decimal('1.0'),
                )
            )
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.commit()

        suggestions = await generate_suggestions(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            include_low_stock=True,
            include_frequent=False,
            include_expiring=False,
        )

        assert len(suggestions) == 2
        assert [s.name for s in suggestions] == [
            product_template_with_min.name,
            product_template_with_min.name,
        ]
        assert {s.template_id for s in suggestions} == {
            product_template_with_min.id,
            other.id,
        }

    async def test_low_stock_multiple_items_same_template(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        product_template_with_min: ProductTemplate,
        category_meat: Category,
    ) -> None:
        """Test that multiple items of same template create only one suggestion."""
        # Create two items from same template, both below min
        for i in range(2):
            item = Item(
                organization_id=async_test_household.id,
                storage_location_id=async_test_storage_location.id,
                template_id=product_template_with_min.id,
                category_id=category_meat.id,
                name=f'Chicken Breast #{i + 1}',
                quantity=Decimal('0.5'),
                expiry_date=date.today() + timedelta(days=30),
            )
            real_async_db_session.add(item)
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.commit()

        suggestions = await generate_suggestions(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            include_low_stock=True,
            include_frequent=False,
            include_expiring=False,
        )

        # Should get one suggestion per template, not per item
        assert len(suggestions) == 1

    async def test_low_stock_no_min_quantity_ignored(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        uom_kg: Uom,
        category_meat: Category,
    ) -> None:
        """Test that items without min_quantity are not suggested."""
        # Create template without min_quantity
        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Beef',
            uom_id=uom_kg.id,
            min_quantity=None,  # No threshold
        )
        real_async_db_session.add(template)
        await real_async_db_session.flush()

        # Create item with very low qty
        item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            template_id=template.id,
            category_id=category_meat.id,
            name='Beef',
            quantity=Decimal('0.1'),
        )
        real_async_db_session.add(item)
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.commit()

        suggestions = await generate_suggestions(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            include_low_stock=True,
            include_frequent=False,
            include_expiring=False,
        )

        # Should not suggest anything
        assert len(suggestions) == 0

    async def test_low_stock_zero_quantity_in_virtual_location(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        uom_kg: Uom,
        category_meat: Category,
    ) -> None:
        """Test that a template IS suggested when all its items have been consumed
        and moved to a virtual (non-internal) location — total stock = 0 < min_quantity."""
        # Create a virtual (consumed) storage location
        virtual_loc = StorageLocation(
            organization_id=async_test_household.id,
            name='__virtual_consumed__',
            usage='consumed',
            created_by=async_test_user.id,
        )
        real_async_db_session.add(virtual_loc)
        await real_async_db_session.flush()

        template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Salt',
            uom_id=uom_kg.id,
            min_quantity=Decimal('1.0'),
        )
        real_async_db_session.add(template)
        await real_async_db_session.flush()

        # Item with quantity=0, sitting in the virtual location (as if fully consumed)
        item = Item(
            organization_id=async_test_household.id,
            storage_location_id=virtual_loc.id,
            template_id=template.id,
            category_id=category_meat.id,
            name='Salt',
            quantity=Decimal('0.0'),
        )
        real_async_db_session.add(item)
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.commit()

        suggestions = await generate_suggestions(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            include_low_stock=True,
            include_frequent=False,
            include_expiring=False,
        )

        # Template with zero stock should appear in suggestions
        assert any(s.name == 'Salt' for s in suggestions), (
            'Product with zero stock (all items consumed) should appear in shopping suggestions'
        )

    async def test_frequently_consumed_items(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        product_template_with_min: ProductTemplate,
        category_meat: Category,
    ) -> None:
        """Test detection of frequently consumed items."""
        # Create item
        item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            template_id=product_template_with_min.id,
            category_id=category_meat.id,
            name='Chicken Breast - Consumed',
            quantity=Decimal('0.0'),  # Already consumed
        )
        real_async_db_session.add(item)
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.flush()

        # Add consumption history (last 30 days)
        for i in range(4):  # 4 consumptions (>= min_consumption_count of 3)
            history = ItemHistory(
                organization_id=async_test_household.id,
                item_id=item.id,
                user_id=async_test_user.id,
                action='USED',
                created_at=date.today() - timedelta(days=i),
            )
            real_async_db_session.add(history)
        await real_async_db_session.commit()

        suggestions = await generate_suggestions(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            include_low_stock=False,
            include_frequent=True,
            include_expiring=False,
            min_consumption_count=3,
        )

        # Verify
        assert len(suggestions) == 1
        suggestion = suggestions[0]
        assert suggestion.source == 'auto_consumption'
        assert suggestion.priority == 0
        assert suggestion.notes == 'Frequently consumed (4× in the last month)'

    async def test_frequently_consumed_note_is_in_the_reader_language(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        product_template_with_min: ProductTemplate,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The reason a frequent item is proposed is written in the request's
        language, as the expiring reasons already were — it read English in
        every language."""
        item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            template_id=product_template_with_min.id,
            name='Kefir',
            quantity=Decimal('0.0'),
        )
        real_async_db_session.add(item)
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.flush()
        for i in range(3):
            real_async_db_session.add(
                ItemHistory(
                    organization_id=async_test_household.id,
                    item_id=item.id,
                    user_id=async_test_user.id,
                    action='USED',
                    created_at=date.today() - timedelta(days=i),
                )
            )
        await real_async_db_session.commit()
        monkeypatch.setattr(
            shopping_suggestions_service, 'get_current_lang', lambda: 'pl'
        )

        suggestions = await generate_suggestions(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            include_low_stock=False,
            include_frequent=True,
            include_expiring=False,
            min_consumption_count=3,
        )

        assert [s.notes for s in suggestions] == [
            'Często zużywane (3× w ostatnim miesiącu)'
        ]

    async def test_frequently_consumed_min_count_filter(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        product_template_with_min: ProductTemplate,
        category_meat: Category,
    ) -> None:
        """Test that min_consumption_count filter works correctly."""
        # Create item
        item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            template_id=product_template_with_min.id,
            category_id=category_meat.id,
            name='Chicken Breast',
            quantity=Decimal('0.0'),
        )
        real_async_db_session.add(item)
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.flush()

        # Add only 2 consumptions (below min_consumption_count of 3)
        for i in range(2):
            history = ItemHistory(
                organization_id=async_test_household.id,
                item_id=item.id,
                user_id=async_test_user.id,
                action='USED',
                created_at=date.today() - timedelta(days=i),
            )
            real_async_db_session.add(history)
        await real_async_db_session.commit()

        suggestions = await generate_suggestions(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            include_low_stock=False,
            include_frequent=True,
            include_expiring=False,
            min_consumption_count=3,
        )

        # Should not suggest (below threshold)
        assert len(suggestions) == 0

    async def test_frequently_consumed_only_recent_history(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        product_template_with_min: ProductTemplate,
        category_meat: Category,
    ) -> None:
        """Test that only last 30 days of consumption history is counted."""
        # Create item
        item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            template_id=product_template_with_min.id,
            category_id=category_meat.id,
            name='Chicken Breast',
            quantity=Decimal('0.0'),
        )
        real_async_db_session.add(item)
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.flush()

        # Add consumptions: 2 recent + 2 old (>30 days)
        dates = [
            date.today() - timedelta(days=1),  # Recent
            date.today() - timedelta(days=5),  # Recent
            date.today() - timedelta(days=35),  # Old
            date.today() - timedelta(days=40),  # Old
        ]

        for _, consumption_date in enumerate(dates):
            history = ItemHistory(
                organization_id=async_test_household.id,
                item_id=item.id,
                user_id=async_test_user.id,
                action='USED',
                created_at=consumption_date,
            )
            real_async_db_session.add(history)
        await real_async_db_session.commit()

        suggestions = await generate_suggestions(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            include_low_stock=False,
            include_frequent=True,
            include_expiring=False,
            min_consumption_count=2,  # Lower threshold
        )

        # Should not suggest (only 2 recent, need 2 but they're discounted)
        # Actually it should suggest because we have exactly 2 recent
        assert len(suggestions) == 1

    async def test_expiring_items_soon(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        product_template_with_min: ProductTemplate,
        category_meat: Category,
    ) -> None:
        """Test detection of items expiring within n days."""
        # Create item expiring in 3 days (within default 7-day threshold)
        item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            template_id=product_template_with_min.id,
            category_id=category_meat.id,
            name='Chicken Breast - Expiring',
            quantity=Decimal('1.0'),
            expiry_date=date.today() + timedelta(days=3),
        )
        real_async_db_session.add(item)
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.commit()

        suggestions = await generate_suggestions(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            include_low_stock=False,
            include_frequent=False,
            include_expiring=True,
            days_for_expiring=7,
        )

        # Verify
        assert len(suggestions) == 1
        suggestion = suggestions[0]
        assert suggestion.source == 'auto_expiring'
        assert suggestion.priority == 2  # Urgent
        assert suggestion.item_id == item.id
        assert 'Expires in 3 days' in (suggestion.notes or '')

    async def test_expiring_items_not_before_threshold(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        product_template_with_min: ProductTemplate,
        category_meat: Category,
    ) -> None:
        """Test that items expiring beyond threshold are not suggested."""
        # Create item expiring in 10 days (beyond 7-day threshold)
        item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            template_id=product_template_with_min.id,
            category_id=category_meat.id,
            name='Chicken Breast',
            quantity=Decimal('1.0'),
            expiry_date=date.today() + timedelta(days=10),
        )
        real_async_db_session.add(item)
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.commit()

        suggestions = await generate_suggestions(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            include_low_stock=False,
            include_frequent=False,
            include_expiring=True,
            days_for_expiring=7,
        )

        # Should not suggest
        assert len(suggestions) == 0

    async def test_expiring_today(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        product_template_with_min: ProductTemplate,
        category_meat: Category,
    ) -> None:
        """Test that items expiring today are suggested."""
        # Create item expiring today
        item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            template_id=product_template_with_min.id,
            category_id=category_meat.id,
            name='Chicken Breast',
            quantity=Decimal('1.0'),
            expiry_date=date.today(),
        )
        real_async_db_session.add(item)
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.commit()

        suggestions = await generate_suggestions(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            include_low_stock=False,
            include_frequent=False,
            include_expiring=True,
            days_for_expiring=7,
        )

        assert len(suggestions) == 1
        # "Expires in 0 days" is arithmetic read aloud; the day it goes off is
        # today, and that is what the shopper needs to be told.
        assert suggestions[0].notes == 'Expires today'
        assert suggestions[0].source == 'auto_expiring'

    async def test_expired_item_is_described_as_expired(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
    ) -> None:
        """A thing past its date is not "expiring in minus forty-nine days".

        The modal is where somebody decides what to buy; it used to hand them a
        minus sign and let them work it out. The two reasons also travel apart
        now — "running out" and "gone off" are different answers to "why is this
        on my list".
        """
        item = Item(
            name='Yoghurt',
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            quantity=1,
            expiry_date=date.today() - timedelta(days=49),
        )
        real_async_db_session.add(item)
        await real_async_db_session.commit()

        suggestions = await generate_suggestions(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            include_low_stock=False,
            include_frequent=False,
            include_expiring=True,
            days_for_expiring=7,
        )

        assert len(suggestions) == 1
        assert suggestions[0].notes == 'Expired 49 days ago'
        assert '-49' not in (suggestions[0].notes or '')
        assert suggestions[0].source == 'auto_expired'

    async def test_the_day_a_thing_goes_off_is_the_organizations_day(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_storage_location: StorageLocation,
    ) -> None:
        """The day a thing goes off is today where the household is.

        The engine counted the days left from the server's ``date.today()``, so
        for a household a day ahead of the server the yoghurt going off today
        was "expired 1 days ago", and for one behind it "expires in 1 days".
        The zone is one whose today differs from the server's right now, so the
        reverted code fails at any hour.
        """
        zone, org_today = zone_where_today_differs()
        async_test_household.timezone = zone
        real_async_db_session.add(
            Item(
                name='Yoghurt',
                organization_id=async_test_household.id,
                storage_location_id=async_test_storage_location.id,
                quantity=1,
                expiry_date=org_today,
            )
        )
        await real_async_db_session.commit()

        suggestions = await generate_suggestions(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            include_low_stock=False,
            include_frequent=False,
            include_expiring=True,
            days_for_expiring=7,
        )

        assert [(s.notes, s.source) for s in suggestions] == [
            ('Expires today', 'auto_expiring')
        ]

    async def test_combined_suggestions_all_sources(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        product_template_with_min: ProductTemplate,
        uom_kg: Uom,
        category_meat: Category,
    ) -> None:
        """Test that all suggestion sources work together."""
        # 1. Low stock item - Chicken (template_with_min)
        low_stock_item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            template_id=product_template_with_min.id,
            category_id=category_meat.id,
            name='Chicken Low Stock',
            quantity=Decimal('0.5'),  # Below min_quantity=2.0
            expiry_date=date.today() + timedelta(days=30),
        )
        real_async_db_session.add(low_stock_item)
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.flush()

        # 2. Frequently consumed item - Pork (separate template)
        pork_template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Pork',
            uom_id=uom_kg.id,
            min_quantity=Decimal('2.0'),
        )
        real_async_db_session.add(pork_template)
        await real_async_db_session.flush()

        consumed_item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            template_id=pork_template.id,
            category_id=category_meat.id,
            name='Pork - Consumed',
            quantity=Decimal('0.0'),
        )
        real_async_db_session.add(consumed_item)
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.flush()

        # Add consumption history
        for i in range(3):
            history = ItemHistory(
                organization_id=async_test_household.id,
                item_id=consumed_item.id,
                user_id=async_test_user.id,
                action='USED',
                created_at=date.today() - timedelta(days=i),
            )
            real_async_db_session.add(history)

        # 3. Expiring item - Beef (separate template)
        beef_template = ProductTemplate(
            organization_id=async_test_household.id,
            name='Beef',
            uom_id=uom_kg.id,
            min_quantity=Decimal('1.0'),
        )
        real_async_db_session.add(beef_template)
        await real_async_db_session.flush()

        expiring_item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            template_id=beef_template.id,
            category_id=category_meat.id,
            name='Beef - Expiring',
            quantity=Decimal('2.0'),
            expiry_date=date.today() + timedelta(days=2),
        )
        real_async_db_session.add(expiring_item)
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.commit()

        suggestions = await generate_suggestions(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            include_low_stock=True,
            include_frequent=True,
            include_expiring=True,
        )

        # Should have suggestions from all 3 sources
        # Note: Pork appears twice (low_stock because qty=0 < min=2.0, AND consumption)
        assert len(suggestions) >= 3, (
            f'Expected at least 3 suggestions, got {len(suggestions)}: {[s.source for s in suggestions]}'
        )
        sources = {s.source for s in suggestions}
        assert sources == {'auto_low_stock', 'auto_consumption', 'auto_expiring'}

    async def test_suggestions_exclude_deleted_items(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        product_template_with_min: ProductTemplate,
        category_meat: Category,
    ) -> None:
        """Test that deleted items are not included in suggestions."""
        # Create deleted item
        deleted_item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            template_id=product_template_with_min.id,
            category_id=category_meat.id,
            name='Chicken Deleted',
            quantity=Decimal('0.5'),
            is_deleted=True,  # Marked as deleted
            expiry_date=date.today() + timedelta(days=30),
        )
        real_async_db_session.add(deleted_item)
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.commit()

        suggestions = await generate_suggestions(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            include_low_stock=True,
            include_frequent=False,
            include_expiring=False,
        )

        # Should not suggest anything
        assert len(suggestions) == 0

    async def test_suggestions_exclude_external_storage(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_type: StorageType,
        product_template_with_min: ProductTemplate,
        category_meat: Category,
    ) -> None:
        """Test that items in external storage locations are excluded."""
        # Create external storage (not 'internal')
        external_storage = StorageLocation(
            organization_id=async_test_household.id,
            created_by=async_test_user.id,
            storage_type_id=async_test_storage_type.id,
            name='Supplier Warehouse',
            usage='external',  # External storage
        )
        real_async_db_session.add(external_storage)
        await real_async_db_session.flush()

        # Create item in external storage
        item = Item(
            organization_id=async_test_household.id,
            storage_location_id=external_storage.id,
            template_id=product_template_with_min.id,
            category_id=category_meat.id,
            name='Chicken',
            quantity=Decimal('0.5'),  # Below min_quantity
            expiry_date=date.today() + timedelta(days=30),
        )
        real_async_db_session.add(item)
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.commit()

        suggestions = await generate_suggestions(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            include_low_stock=True,
            include_frequent=False,
            include_expiring=False,
        )

        # Should not suggest (external storage excluded)
        assert len(suggestions) == 0

    async def test_filter_duplicate_suggestions(self) -> None:
        """Test filtering of duplicate suggestions against existing shopping list items."""
        # Create suggestions
        suggestion1 = ShoppingSuggestion(
            name='Chicken Breast',
            quantity=1,
            source='auto_low_stock',
            priority=1,
        )
        suggestion2 = ShoppingSuggestion(
            name='Pork',
            quantity=2,
            source='auto_consumption',
            priority=0,
        )
        suggestion3 = ShoppingSuggestion(
            name='Tomato',
            quantity=3,
            source='auto_expiring',
            priority=2,
        )

        suggestions = [suggestion1, suggestion2, suggestion3]

        # Existing items (unpurchased)
        existing_items = [
            {'name': 'chicken breast', 'is_purchased': False},  # Case-insensitive match
            {'name': 'Rice', 'is_purchased': False},
            {'name': 'Pork', 'is_purchased': True},  # Purchased, so not a duplicate
        ]

        filtered = filter_duplicate_suggestions(suggestions, existing_items)

        # Should exclude chicken (exact match) but keep pork (already purchased)
        # and tomato (not in list)
        assert len(filtered) == 2
        names = {s.name for s in filtered}
        assert names == {'Pork', 'Tomato'}

    async def test_filter_duplicate_case_insensitive(self) -> None:
        """Test that duplicate filtering is case-insensitive."""
        suggestions = [
            ShoppingSuggestion(name='CHICKEN', quantity=1),
            ShoppingSuggestion(name='Pork', quantity=2),
        ]

        existing_items = [
            {'name': 'chicken', 'is_purchased': False},  # Match (case-insensitive)
            {'name': 'BEEF', 'is_purchased': False},
        ]

        filtered = filter_duplicate_suggestions(suggestions, existing_items)

        # Should only keep Pork
        assert len(filtered) == 1
        assert filtered[0].name == 'Pork'

    async def test_no_suggestions_when_all_disabled(
        self,
        real_async_db_session: AsyncSession,
        async_test_household: Organization,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
        product_template_with_min: ProductTemplate,
        category_meat: Category,
    ) -> None:
        """Test that no suggestions are generated when all sources are disabled."""
        # Create items that would normally generate suggestions
        item = Item(
            organization_id=async_test_household.id,
            storage_location_id=async_test_storage_location.id,
            template_id=product_template_with_min.id,
            category_id=category_meat.id,
            name='Chicken',
            quantity=Decimal('0.5'),  # Below min_quantity
            expiry_date=date.today() + timedelta(days=3),  # Expiring soon
        )
        real_async_db_session.add(item)
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.commit()

        suggestions = await generate_suggestions(
            db=real_async_db_session,
            organization_id=async_test_household.id,
            include_low_stock=False,
            include_frequent=False,
            include_expiring=False,
        )

        assert len(suggestions) == 0

    async def test_suggestion_to_dict(self) -> None:
        """Test ShoppingSuggestion.to_dict() serialization."""
        template_id = uuid4()
        suggestion = ShoppingSuggestion(
            name='Test Product',
            item_id=uuid4(),
            template_id=template_id,
            category_id=uuid4(),
            quantity=5,
            source='auto_low_stock',
            priority=1,
            estimated_price=Decimal('19.99'),
            notes='Test notes',
        )

        result = suggestion.to_dict()

        assert result['name'] == 'Test Product'
        assert result['quantity'] == 5
        assert result['unit'] is None
        assert result['source'] == 'auto_low_stock'
        assert result['priority'] == 1
        assert result['estimated_price'] == Decimal('19.99')
        assert result['notes'] == 'Test notes'
        assert result['item_id'] is not None
        assert result['template_id'] == template_id
        assert result['category_id'] is not None
