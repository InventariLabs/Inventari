"""One number for "needs attention", read from one place.

The inventory dashboard's heading and the statistics health card answer
the same question — expired records, records expiring inside the horizon,
and products that reached their threshold. They used to compute it apart:
the dashboard from three capped item lists, the statistics card from the
overview endpoint. On the same data the two could disagree, and the
running-low share silently stopped at the list's hundred-row cap.

The counts live in one service function now. The endpoint the dashboard
reads and the overview the statistics screen reads both call it, so the
two screens cannot drift again. Here we pin that the endpoint answers
with the overview's own numbers, that a product is one shortage however
many records it is kept in (a hundred and fifty of them do not fall off a
page cap), and that the module-data filter narrows every number the way
the item list's own filter does.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.module_scope import get_claimed_context_tags
from app.models import Item, ProductTemplate, User
from app.models.category import Category
from app.models.storage_location import StorageLocation
from app.services.analytics.overview import (
    get_health_counts_async,
    get_overview_async,
)
from app.services.items._query_get import get_items, get_items_aggregates
from tests.integration._shelf import anchor_pending_records

pytestmark = pytest.mark.integration


def _product(
    db: AsyncSession | object,
    organization_id: uuid.UUID,
    name: str,
    minimum: float = 10,
) -> ProductTemplate:
    product = ProductTemplate(
        id=uuid.uuid4(),
        organization_id=organization_id,
        name=name,
        min_quantity=minimum,
    )
    db.add(product)  # type: ignore[attr-defined]
    return product


def _record(
    db: AsyncSession | object,
    organization_id: uuid.UUID,
    location_id: uuid.UUID,
    *,
    name: str,
    quantity: float = 1,
    template_id: uuid.UUID | None = None,
    expiry_date: date | None = None,
    category_id: uuid.UUID | None = None,
) -> Item:
    item = Item(
        organization_id=organization_id,
        storage_location_id=location_id,
        template_id=template_id,
        name=name,
        quantity=quantity,
        expiry_date=expiry_date,
        category_id=category_id,
    )
    db.add(item)  # type: ignore[attr-defined]
    return item


async def _seed_three_kinds_of_attention(
    db: AsyncSession, user: User, location: StorageLocation
) -> ProductTemplate:
    """One expired record, two expiring, one short product on the shelf."""
    today = date.today()
    short = _product(db, user.organization_id, f'Flour {uuid.uuid4().hex[:6]}')
    await db.flush()
    _record(
        db,
        user.organization_id,
        location.id,
        name='Past its date',
        expiry_date=today - timedelta(days=1),
    )
    _record(
        db,
        user.organization_id,
        location.id,
        name='Dates today',
        expiry_date=today,
    )
    _record(
        db,
        user.organization_id,
        location.id,
        name='Expires this week',
        expiry_date=today + timedelta(days=3),
    )
    _record(
        db,
        user.organization_id,
        location.id,
        name=short.name,
        template_id=short.id,
        quantity=2,
    )
    await db.run_sync(anchor_pending_records)
    await db.flush()
    return short


class TestTheCountsAreOneComputation:
    async def test_the_service_reports_the_overview_numbers(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
    ) -> None:
        await _seed_three_kinds_of_attention(
            real_async_db_session, async_test_user, async_test_storage_location
        )

        counts = await get_health_counts_async(
            real_async_db_session, async_test_user.organization_id
        )
        overview = await get_overview_async(
            real_async_db_session, async_test_user.organization_id
        )

        assert (
            (counts.expired, counts.expiring_soon, counts.low_stock)
            == (
                overview.expired,
                overview.expiring_soon,
                overview.low_stock,
            )
            == (1, 2, 1)
        )

    async def test_a_hundred_and_fifty_records_of_one_short_product_count_once(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
    ) -> None:
        """The count is of products, uncapped — not of the page the card shows."""
        product = _product(
            real_async_db_session,
            async_test_user.organization_id,
            'Flour by the pallet',
            minimum=100,
        )
        await real_async_db_session.flush()
        for _ in range(150):
            _record(
                real_async_db_session,
                async_test_user.organization_id,
                async_test_storage_location.id,
                name=product.name,
                template_id=product.id,
                quantity=0.1,
            )
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.flush()

        counts = await get_health_counts_async(
            real_async_db_session, async_test_user.organization_id
        )
        _, record_total = await real_async_db_session.run_sync(
            lambda s: get_items(s, async_test_user, only_low_stock=True)
        )

        # The list holds a hundred and fifty records of this one product; the
        # count is one shortage. Reading the count off the list's page (or its
        # record total) is exactly the defect this task closes.
        assert record_total == 150
        assert counts.low_stock == 1

    async def test_hiding_module_data_narrows_every_number(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
    ) -> None:
        """A record a vertical module owns is hidden — and so is its product."""
        claimed = get_claimed_context_tags()
        assert claimed, 'no module claims a context tag in this build'
        module_category = Category(
            organization_id=async_test_user.organization_id,
            name=f'Module-owned {uuid.uuid4().hex[:6]}',
            context_tag=sorted(claimed)[0],
        )
        real_async_db_session.add(module_category)
        await real_async_db_session.flush()

        today = date.today()
        module_product = _product(
            real_async_db_session,
            async_test_user.organization_id,
            f'Module short {uuid.uuid4().hex[:6]}',
        )
        plain_product = _product(
            real_async_db_session,
            async_test_user.organization_id,
            f'Plain short {uuid.uuid4().hex[:6]}',
        )
        await real_async_db_session.flush()
        _record(
            real_async_db_session,
            async_test_user.organization_id,
            async_test_storage_location.id,
            name='Module record',
            expiry_date=today - timedelta(days=1),
            category_id=module_category.id,
        )
        _record(
            real_async_db_session,
            async_test_user.organization_id,
            async_test_storage_location.id,
            name='Plain record',
            expiry_date=today - timedelta(days=1),
        )
        _record(
            real_async_db_session,
            async_test_user.organization_id,
            async_test_storage_location.id,
            name=module_product.name,
            template_id=module_product.id,
            quantity=1,
            category_id=module_category.id,
        )
        _record(
            real_async_db_session,
            async_test_user.organization_id,
            async_test_storage_location.id,
            name=plain_product.name,
            template_id=plain_product.id,
            quantity=1,
        )
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.flush()

        everything = await get_health_counts_async(
            real_async_db_session, async_test_user.organization_id
        )
        visible = await get_health_counts_async(
            real_async_db_session,
            async_test_user.organization_id,
            exclude_module_contexts=True,
        )

        assert (everything.expired, everything.low_stock) == (2, 2)
        assert (visible.expired, visible.expiring_soon, visible.low_stock) == (
            1,
            0,
            1,
        )

    async def test_a_product_used_up_stays_counted_when_module_data_is_hidden(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
    ) -> None:
        """Its last record is not on a shelf, and that does not hide it.

        Consuming the last unit files the record under the virtual Consumed
        location, outside the shelves the visibility check used to look in.
        The tile counted the product (nothing left, minimum set) while the
        heading, asking with module data hidden, said none.
        """
        consumed = StorageLocation(
            organization_id=async_test_user.organization_id,
            created_by=async_test_user.id,
            name=f'Consumed {uuid.uuid4().hex[:6]}',
            usage='customer',
        )
        real_async_db_session.add(consumed)
        used_up = _product(
            real_async_db_session,
            async_test_user.organization_id,
            f'Spaghetti {uuid.uuid4().hex[:6]}',
            minimum=1,
        )
        await real_async_db_session.flush()
        _record(
            real_async_db_session,
            async_test_user.organization_id,
            consumed.id,
            name=used_up.name,
            template_id=used_up.id,
            quantity=0,
        )
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.flush()

        everything = await get_health_counts_async(
            real_async_db_session, async_test_user.organization_id
        )
        visible = await get_health_counts_async(
            real_async_db_session,
            async_test_user.organization_id,
            exclude_module_contexts=True,
        )

        assert everything.low_stock == visible.low_stock == 1


class TestTheEndpoint:
    def test_an_empty_organization_needs_nothing(self, client, auth_headers):
        response = client.get('/api/v1/items/attention-counts', headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == {
            'expired': 0,
            'expiring_soon': 0,
            'low_stock': 0,
            'records': 0,
        }

    def test_the_rows_endpoint_walks_the_same_filter_as_the_heading(
        self, client, auth_headers, db_session, test_user, test_storage_location
    ) -> None:
        claimed = get_claimed_context_tags()
        assert claimed, 'no module claims a context tag in this build'
        module_category = Category(
            organization_id=test_user.organization_id,
            name='Module-owned rows',
            context_tag=sorted(claimed)[0],
        )
        db_session.add(module_category)
        db_session.flush()
        ordinary = _product(db_session, test_user.organization_id, 'Rice')
        owned = _product(db_session, test_user.organization_id, 'Drill bits')
        db_session.flush()
        for product, category_id in ((ordinary, None), (owned, module_category.id)):
            _record(
                db_session,
                test_user.organization_id,
                test_storage_location.id,
                name=product.name,
                template_id=product.id,
                quantity=3,
                category_id=category_id,
            )
        anchor_pending_records(db_session)
        db_session.commit()

        rows = client.get('/api/v1/stats/low-stock', headers=auth_headers)
        visible_rows = client.get(
            '/api/v1/stats/low-stock',
            headers=auth_headers,
            params={'exclude_module_contexts': 'true'},
        )
        heading = client.get(
            '/api/v1/items/attention-counts',
            headers=auth_headers,
            params={'exclude_module_contexts': 'true'},
        )

        assert {r['template_id'] for r in rows.json()['items']} == {
            str(ordinary.id),
            str(owned.id),
        }
        assert [r['template_id'] for r in visible_rows.json()['items']] == [
            str(ordinary.id)
        ]
        assert heading.json()['low_stock'] == visible_rows.json()['total']

    def test_the_rows_page_and_the_total_is_the_headings_number(
        self, client, auth_headers, db_session, test_user, test_storage_location
    ) -> None:
        # Three short products with the same on-hand figure: the page boundary
        # is decided by the name and then the id, never by the database's whim.
        products = [
            _product(db_session, test_user.organization_id, name)
            for name in ('Barley', 'Barley', 'Oats')
        ]
        db_session.flush()
        for product in products:
            _record(
                db_session,
                test_user.organization_id,
                test_storage_location.id,
                name=product.name,
                template_id=product.id,
                quantity=1,
            )
        anchor_pending_records(db_session)
        db_session.commit()

        first = client.get(
            '/api/v1/stats/low-stock', headers=auth_headers, params={'limit': 2}
        ).json()
        rest = client.get(
            '/api/v1/stats/low-stock',
            headers=auth_headers,
            params={'limit': 2, 'offset': 2},
        ).json()
        heading = client.get('/api/v1/items/attention-counts', headers=auth_headers)

        assert first['total'] == rest['total'] == heading.json()['low_stock'] == 3
        assert (len(first['items']), first['has_more']) == (2, True)
        assert (len(rest['items']), rest['has_more']) == (1, False)
        paged = [r['template_id'] for r in first['items'] + rest['items']]
        assert len(set(paged)) == 3

    def test_the_endpoint_walks_the_module_filter_the_list_walks(
        self, client, auth_headers, db_session, test_user, test_storage_location
    ) -> None:
        claimed = get_claimed_context_tags()
        assert claimed, 'no module claims a context tag in this build'
        module_category = Category(
            organization_id=test_user.organization_id,
            name='Module-owned shelf',
            context_tag=sorted(claimed)[0],
        )
        db_session.add(module_category)
        db_session.flush()

        today = date.today()
        short = _product(db_session, test_user.organization_id, 'Ends of things')
        db_session.flush()
        _record(
            db_session,
            test_user.organization_id,
            test_storage_location.id,
            name='Past its date',
            expiry_date=today - timedelta(days=2),
        )
        _record(
            db_session,
            test_user.organization_id,
            test_storage_location.id,
            name='Module asset',
            expiry_date=today - timedelta(days=2),
            category_id=module_category.id,
        )
        _record(
            db_session,
            test_user.organization_id,
            test_storage_location.id,
            name=short.name,
            template_id=short.id,
            quantity=3,
        )
        anchor_pending_records(db_session)
        db_session.commit()

        everything = client.get('/api/v1/items/attention-counts', headers=auth_headers)
        visible = client.get(
            '/api/v1/items/attention-counts',
            headers=auth_headers,
            params={'exclude_module_contexts': 'true'},
        )

        assert everything.status_code == 200
        assert everything.json() == {
            'expired': 2,
            'expiring_soon': 0,
            'low_stock': 1,
            'records': 3,
        }
        assert visible.status_code == 200
        assert visible.json() == {
            'expired': 1,
            'expiring_soon': 0,
            'low_stock': 1,
            'records': 2,
        }


class TestTheListBehindTheNumber:
    """The tile opens the records that make up its number, not every record."""

    async def test_the_needs_attention_filter_lists_what_the_count_counts(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
    ) -> None:
        short = await _seed_three_kinds_of_attention(
            real_async_db_session, async_test_user, async_test_storage_location
        )
        _record(
            real_async_db_session,
            async_test_user.organization_id,
            async_test_storage_location.id,
            name='Fine for a month',
            expiry_date=date.today() + timedelta(days=30),
        )
        _record(
            real_async_db_session,
            async_test_user.organization_id,
            async_test_storage_location.id,
            name='Undated and plenty',
            quantity=5,
        )
        await real_async_db_session.run_sync(anchor_pending_records)
        await real_async_db_session.flush()

        items, total = await real_async_db_session.run_sync(
            lambda s: get_items(
                s,
                async_test_user,
                needs_attention=True,
                today=date.today(),
            )
        )
        counts = await get_health_counts_async(
            real_async_db_session, async_test_user.organization_id
        )

        assert {i.name for i in items} == {
            'Past its date',
            'Dates today',
            'Expires this week',
            short.name,
        }
        # One record per expiry and one record of the short product: the list
        # and the number agree.
        assert total == counts.expired + counts.expiring_soon + counts.low_stock

    async def test_a_product_used_up_is_listed_once(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
        async_test_storage_location: StorageLocation,
    ) -> None:
        """Using up the last unit moves the record off the shelves.

        The product is then short — the count says so — while the list read
        the shelves alone and left it out: three to attend to, two rows. The
        product joins the list by its last record, once however many it has
        used up before.
        """
        db = real_async_db_session
        org_id = async_test_user.organization_id
        consumed = StorageLocation(
            organization_id=org_id,
            created_by=async_test_user.id,
            name=f'Consumed {uuid.uuid4().hex[:6]}',
            usage='customer',
        )
        oats = _product(db, org_id, f'Oats {uuid.uuid4().hex[:6]}', minimum=1)
        stocked = _product(db, org_id, f'Rice {uuid.uuid4().hex[:6]}', minimum=5)
        db.add(consumed)
        await db.flush()
        for _ in range(3):
            _record(
                db,
                org_id,
                consumed.id,
                name=oats.name,
                quantity=0,
                template_id=oats.id,
            )
        # Short, with a record still on the shelf: that record stands for it.
        _record(
            db,
            org_id,
            async_test_storage_location.id,
            name=stocked.name,
            quantity=1,
            template_id=stocked.id,
        )
        _record(
            db,
            org_id,
            consumed.id,
            name=stocked.name,
            quantity=0,
            template_id=stocked.id,
        )
        await db.run_sync(anchor_pending_records)
        await db.flush()

        items, total = await db.run_sync(
            lambda s: get_items(
                s, async_test_user, needs_attention=True, today=date.today()
            )
        )
        counts = await get_health_counts_async(db, org_id)

        assert sorted((i.name, float(i.quantity)) for i in items) == sorted(
            [(oats.name, 0.0), (stocked.name, 1.0)]
        )
        assert total == counts.low_stock == 2
        # The footer under the list counts the same rows.
        footer = await db.run_sync(
            lambda s: get_items_aggregates(
                s,
                user_organization_id=org_id,
                needs_attention=True,
                today=date.today(),
            )
        )
        assert footer.count == 2

    async def test_the_low_stock_filter_names_a_product_used_up_too(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
    ) -> None:
        """The running-low tile counts it, and its list had no row to show."""
        db = real_async_db_session
        org_id = async_test_user.organization_id
        consumed = StorageLocation(
            organization_id=org_id,
            created_by=async_test_user.id,
            name=f'Consumed {uuid.uuid4().hex[:6]}',
            usage='customer',
        )
        oats = _product(db, org_id, f'Oats {uuid.uuid4().hex[:6]}', minimum=1)
        db.add(consumed)
        await db.flush()
        _record(
            db, org_id, consumed.id, name=oats.name, quantity=0, template_id=oats.id
        )
        await db.run_sync(anchor_pending_records)
        await db.flush()

        items, total = await db.run_sync(
            lambda s: get_items(s, async_test_user, only_low_stock=True)
        )
        counts = await get_health_counts_async(db, org_id)

        assert [i.name for i in items] == [oats.name]
        assert total == counts.low_stock == 1

    def test_the_list_endpoint_takes_the_filter(
        self, client, auth_headers, db_session, test_user, test_storage_location
    ) -> None:
        today = date.today()
        _record(
            db_session,
            test_user.organization_id,
            test_storage_location.id,
            name='Cheddar',
            expiry_date=today - timedelta(days=2),
        )
        _record(
            db_session,
            test_user.organization_id,
            test_storage_location.id,
            name='Rice',
            expiry_date=today + timedelta(days=200),
        )
        anchor_pending_records(db_session)
        db_session.commit()

        listed = client.get(
            '/api/v1/items',
            headers=auth_headers,
            params={'needs_attention': 'true'},
        )
        footer = client.get(
            '/api/v1/items/aggregates',
            headers=auth_headers,
            params={'needs_attention': 'true'},
        )

        assert listed.status_code == 200, listed.text
        assert [i['name'] for i in listed.json()['items']] == ['Cheddar']
        assert footer.json()['count'] == 1
