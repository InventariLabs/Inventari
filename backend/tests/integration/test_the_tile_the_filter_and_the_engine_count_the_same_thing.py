"""One organization, one question about stock, one answer.

Three places answer "is this product running out": the dashboard tile, the
product list's "Running low" filter, and the purchasing engine that
proposes what to buy. Two of them compared the threshold against **each
stock record separately**; the third summed the product's stock and
compared once.

For a product held in six places — 8, 7, 8, 5, 2 and 4 units against a
minimum of 10 — the first two answered "six shortages" and the third
answered "none". Thirty-four units against a minimum of ten is not six
shortages.

The threshold is not a per-record quantity and never was.
``ProductTemplate.min_quantity`` is one value per product, and the module
that adds per-location thresholds on top of it says so in the docstring of
its own table: *"Per-location granularity is the main value-add over the
flat ProductTemplate.min_quantity field, which is org-global."* Comparing
an org-global number against one record is a level-of-aggregation error,
not a second opinion.

It is also an unstable one: an ``Item`` row is not a group of stock. A
group is one (org, product, location, lot, owner), which the records' view
sums; ``Item`` carries no such uniqueness, and two receipts of the same
hand-typed name into the same place leave two rows. So the count of
"shortages" moved with how a name had been typed at goods-in.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Item, ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.services.analytics.overview import get_overview_async
from app.services.items._query_get import get_items
from tests.integration._shelf import anchor_pending_records

SPREAD = [8, 7, 8, 5, 2, 4]  # 34 in total
MINIMUM = 10


async def _product_spread_over_rows(
    db: AsyncSession,
    user: User,
    location: StorageLocation,
    quantities: list[int],
    minimum: int,
    name: str = 'Wheat Flour 550',
) -> ProductTemplate:
    """One product, one threshold, its stock split over several records."""
    product = ProductTemplate(
        organization_id=user.organization_id,
        name=f'{name} {uuid.uuid4().hex[:6]}',
        min_quantity=minimum,
    )
    db.add(product)
    await db.flush()

    for quantity in quantities:
        db.add(
            Item(
                organization_id=user.organization_id,
                storage_location_id=location.id,
                template_id=product.id,
                name=product.name,
                quantity=quantity,
            )
        )
    await db.run_sync(anchor_pending_records)
    await db.flush()
    return product


async def _put_stock_at_the_customer(
    db: AsyncSession,
    user: User,
    product: ProductTemplate,
    quantity: int,
) -> None:
    """A record of *product* standing outside the shelves — out on loan, say."""
    customer = StorageLocation(
        organization_id=user.organization_id,
        created_by=user.id,
        name=f'Customer counter {uuid.uuid4().hex[:6]}',
        usage='customer',
    )
    db.add(customer)
    await db.flush()
    db.add(
        Item(
            organization_id=user.organization_id,
            storage_location_id=customer.id,
            template_id=product.id,
            name=product.name,
            quantity=quantity,
        )
    )
    await db.run_sync(anchor_pending_records)
    await db.flush()


@pytest.mark.integration
class TestStockSplitOverRecordsIsNotAShortage:
    async def test_the_tile_counts_the_product_once_it_is_actually_short(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        await _product_spread_over_rows(
            real_async_db_session,
            async_test_user,
            async_test_storage_location,
            SPREAD,
            MINIMUM,
        )

        overview = await get_overview_async(
            real_async_db_session, async_test_user.organization_id
        )

        # 34 against a minimum of 10 is not a shortage at all, let alone six.
        assert overview.low_stock == 0

    async def test_the_filter_lists_nothing_for_a_product_that_is_stocked(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        product = await _product_spread_over_rows(
            real_async_db_session,
            async_test_user,
            async_test_storage_location,
            SPREAD,
            MINIMUM,
        )

        items, _total = await real_async_db_session.run_sync(
            lambda s: get_items(s, async_test_user, only_low_stock=True)
        )

        assert not [item for item in items if item.template_id == product.id]

    async def test_a_product_really_below_its_threshold_is_counted_once(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        # The discriminating half: the same shape of data, a total that is
        # genuinely short. It must appear — once for the product, not once
        # for each place it is kept in.
        product = await _product_spread_over_rows(
            real_async_db_session,
            async_test_user,
            async_test_storage_location,
            [1, 1, 1],  # 3 against a minimum of 10
            MINIMUM,
            name='Short Product',
        )

        overview = await get_overview_async(
            real_async_db_session, async_test_user.organization_id
        )
        items, _total = await real_async_db_session.run_sync(
            lambda s: get_items(s, async_test_user, only_low_stock=True)
        )

        assert overview.low_stock == 1
        listed = [item for item in items if item.template_id == product.id]
        # The list's unit is a record, so it shows the records the reader
        # would go and look at — but the *count* above is products.
        assert len(listed) == 3

    async def test_the_tile_and_the_purchasing_engine_agree(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        # The engine already summed; this pins the two together so neither
        # can drift back on its own.
        from app.modules.shopping_lists.shopping_suggestions_service import (
            generate_suggestions,
        )

        await _product_spread_over_rows(
            real_async_db_session,
            async_test_user,
            async_test_storage_location,
            SPREAD,
            MINIMUM,
        )

        overview = await get_overview_async(
            real_async_db_session, async_test_user.organization_id
        )
        suggestions = await generate_suggestions(
            real_async_db_session,
            async_test_user.organization_id,
            include_low_stock=True,
            include_frequent=False,
            include_expiring=False,
        )

        assert overview.low_stock == len(suggestions) == 0


@pytest.mark.integration
class TestActiveStockOutsideTheShelfSuppressesTheShortage:
    """The tile, the filter, statistics and the engine read one rule.

    The engine refused a product with active stock outside the shelves —
    something already on its way is not something to order — and kept that
    condition to itself. On the reviewing shape — a minimum of 40 with one
    row moved to a customer location — the tile said "1 low stock" while
    the engine behind the tile's own button proposed nothing.
    """

    async def test_the_tile_the_filter_and_the_engine_all_stay_quiet(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        from app.modules.shopping_lists.shopping_suggestions_service import (
            generate_suggestions,
        )

        product = await _product_spread_over_rows(
            real_async_db_session,
            async_test_user,
            async_test_storage_location,
            [1, 1, 1],
            MINIMUM,
            name='Out on loan',
        )
        await _put_stock_at_the_customer(
            real_async_db_session, async_test_user, product, quantity=8
        )

        overview = await get_overview_async(
            real_async_db_session, async_test_user.organization_id
        )
        items, _total = await real_async_db_session.run_sync(
            lambda s: get_items(s, async_test_user, only_low_stock=True)
        )
        suggestions = await generate_suggestions(
            real_async_db_session,
            async_test_user.organization_id,
            include_low_stock=True,
            include_frequent=False,
            include_expiring=False,
        )

        assert overview.low_stock == 0
        assert not [item for item in items if item.template_id == product.id]
        assert suggestions == []

    async def test_an_emptied_record_outside_does_not_suppress_the_shortage(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        # "Active" is the word: a consumed record (quantity zero) sitting
        # outside is not stock coming back, and the shortage stands.
        from app.modules.shopping_lists.shopping_suggestions_service import (
            generate_suggestions,
        )

        product = await _product_spread_over_rows(
            real_async_db_session,
            async_test_user,
            async_test_storage_location,
            [1, 1, 1],
            MINIMUM,
            name='Consumed outside',
        )
        await _put_stock_at_the_customer(
            real_async_db_session, async_test_user, product, quantity=0
        )

        overview = await get_overview_async(
            real_async_db_session, async_test_user.organization_id
        )
        items, _total = await real_async_db_session.run_sync(
            lambda s: get_items(s, async_test_user, only_low_stock=True)
        )
        suggestions = await generate_suggestions(
            real_async_db_session,
            async_test_user.organization_id,
            include_low_stock=True,
            include_frequent=False,
            include_expiring=False,
        )

        assert overview.low_stock == 1
        assert len([item for item in items if item.template_id == product.id]) == 3
        assert [s.template_id for s in suggestions] == [product.id]
