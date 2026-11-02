"""The number on the tile has a list behind it, and the list is products.

The tile counts products, so what a reader can open has to be products too:
which ones, how much is on the shelf, what the minimum is. A product used up
to nothing has no record on the shelf to list, yet it is the plainest
shortage there is.
"""

import uuid

import pytest

from app.core.module_scope import get_claimed_context_tags
from app.models import Category, Item, ProductTemplate
from app.models.storage_location import StorageLocation
from app.services.analytics.overview import (
    get_health_counts_async,
    get_overview_async,
)
from app.services.items.low_stock import low_stock_products_async
from tests.integration._shelf import anchor_pending_records


async def _product(db, user, name, minimum, shelf, location, outside=None):
    product = ProductTemplate(
        organization_id=user.organization_id,
        name=f'{name} {uuid.uuid4().hex[:6]}',
        min_quantity=minimum,
    )
    db.add(product)
    await db.flush()
    for quantity, place in [(shelf, location), *([outside] if outside else [])]:
        if quantity is None:
            continue
        db.add(
            Item(
                organization_id=user.organization_id,
                storage_location_id=place.id,
                template_id=product.id,
                name=product.name,
                quantity=quantity,
            )
        )
    await db.run_sync(anchor_pending_records)
    await db.flush()
    return product


@pytest.mark.integration
class TestLowStockProducts:
    async def test_each_short_product_comes_with_its_shelf_stock_and_minimum(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        low = await _product(
            real_async_db_session,
            async_test_user,
            'Rice',
            10,
            3,
            async_test_storage_location,
        )
        await _product(
            real_async_db_session,
            async_test_user,
            'Stocked',
            2,
            9,
            async_test_storage_location,
        )

        rows = await low_stock_products_async(
            real_async_db_session, async_test_user.organization_id
        )

        assert [(r.template_id, r.on_hand, r.minimum) for r in rows] == [
            (low.id, 3, 10)
        ]
        assert rows[0].item_id is not None

    async def test_a_product_used_up_is_listed_with_nothing_on_hand(
        self, real_async_db_session, async_test_user
    ) -> None:
        # The record sits in the virtual Consumed location, which is not a
        # shelf: the product has nothing on hand, and that is the shortage.
        consumed = StorageLocation(
            organization_id=async_test_user.organization_id,
            created_by=async_test_user.id,
            name=f'Consumed {uuid.uuid4().hex[:6]}',
            usage='customer',
        )
        real_async_db_session.add(consumed)
        await real_async_db_session.flush()
        product = await _product(
            real_async_db_session,
            async_test_user,
            'Spaghetti',
            1,
            0,
            consumed,
        )

        rows = await low_stock_products_async(
            real_async_db_session, async_test_user.organization_id
        )
        overview = await get_overview_async(
            real_async_db_session, async_test_user.organization_id
        )

        assert [(r.template_id, r.on_hand) for r in rows] == [(product.id, 0)]
        # The product still has its details: the list opens its last record
        # rather than leaving a used-up product with nowhere to go.
        assert rows[0].item_id is not None
        # The list and the tile are one answer.
        assert overview.low_stock == len(rows)


@pytest.mark.integration
class TestLowStockProductsWhenModuleDataIsHidden:
    """The heading, the tile and the rows are one set of products."""

    async def _module_category(self, db, user) -> Category:
        claimed = get_claimed_context_tags()
        assert claimed, 'no module claims a context tag in this build'
        category = Category(
            organization_id=user.organization_id,
            name=f'Module-owned {uuid.uuid4().hex[:6]}',
            context_tag=sorted(claimed)[0],
        )
        db.add(category)
        await db.flush()
        return category

    async def test_a_product_that_only_a_module_holds_is_left_out_and_not_counted(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        db, user = real_async_db_session, async_test_user
        category = await self._module_category(db, user)
        ordinary = await _product(db, user, 'Rice', 10, 3, async_test_storage_location)
        owned = await _product(
            db, user, 'Drill bits', 10, 1, async_test_storage_location
        )
        for item in (
            await db.execute(
                Item.__table__.select().where(Item.template_id == owned.id)
            )
        ).all():
            await db.execute(
                Item.__table__.update()
                .where(Item.id == item.id)
                .values(category_id=category.id)
            )

        everything = await low_stock_products_async(db, user.organization_id)
        visible = await low_stock_products_async(
            db, user.organization_id, exclude_module_contexts=True
        )
        counts = await get_health_counts_async(
            db, user.organization_id, exclude_module_contexts=True
        )

        assert {r.template_id for r in everything} == {ordinary.id, owned.id}
        assert [r.template_id for r in visible] == [ordinary.id]
        # The number the heading and the tile read is the rows' length.
        assert counts.low_stock == len(visible)

    async def test_the_row_opens_a_record_the_list_can_show(
        self, real_async_db_session, async_test_user, async_test_storage_location
    ) -> None:
        db, user = real_async_db_session, async_test_user
        category = await self._module_category(db, user)
        product = await _product(db, user, 'Mixed', 10, 2, async_test_storage_location)
        # A second record of the same product, filed under the module's
        # category, which sorts first when records are compared by id.
        owned = Item(
            id=uuid.UUID(int=0),
            organization_id=user.organization_id,
            storage_location_id=async_test_storage_location.id,
            template_id=product.id,
            name=product.name,
            quantity=1,
            category_id=category.id,
        )
        db.add(owned)
        await db.run_sync(anchor_pending_records)
        await db.flush()

        visible = await low_stock_products_async(
            db, user.organization_id, exclude_module_contexts=True
        )

        assert [r.template_id for r in visible] == [product.id]
        assert visible[0].item_id is not None
        assert visible[0].item_id != owned.id
