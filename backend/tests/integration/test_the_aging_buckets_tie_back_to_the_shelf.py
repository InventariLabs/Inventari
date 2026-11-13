"""What the aging buckets add up to is what a reader can still count.

The buckets used to age everything that ever arrived: ten received and four
later dispatched still showed ten, so their sum tied back to nothing anybody
could verify by walking the racks. Issues now consume the receipts oldest
business date first — but the suite could not tell: every case in it received
stock and never issued any, so a version that ignored issues altogether went
on passing.

Two things this pins down. The buckets net off what left, and a report cut at
a past date does not see an issue made after it — otherwise a back-dated
report would keep changing as the warehouse carried on working.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import insert, update

from app.core.public_api import core_api
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove

AS_OF = datetime(2026, 6, 23, tzinfo=UTC)


async def _move(
    db,
    org_id,
    template_id,
    *,
    quantity: Decimal,
    at: datetime,
    to_location_id=None,
    from_location_id=None,
) -> None:
    """One receipt (to_location) or one issue (from_location), stamped."""
    move = await core_api.stock_moves.create_async(
        db,
        organization_id=org_id,
        product_template_id=template_id,
        to_location_id=to_location_id,
        from_location_id=from_location_id,
        quantity=quantity,
    )
    await db.execute(
        update(StockMove)
        .where(StockMove.id == move.id)
        .values(created_at=at, completed_at=at)
    )


def _total(buckets) -> Decimal:
    return sum((b.quantity for b in buckets), Decimal('0'))


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheAgingBucketsTieBackToTheShelf:
    async def _template(self, db, org_id) -> ProductTemplate:
        template = ProductTemplate(
            organization_id=org_id,
            name='Aging Net',
            sku=f'SKU-NET-{uuid.uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        return template

    async def test_what_left_is_not_aged(
        self,
        real_async_db_session,
        async_test_household,
        async_test_storage_location,
    ):
        db = real_async_db_session
        template = await self._template(db, async_test_household.id)

        await _move(
            db,
            async_test_household.id,
            template.id,
            quantity=Decimal('10'),
            at=AS_OF - timedelta(days=10),
            to_location_id=async_test_storage_location.id,
        )
        await _move(
            db,
            async_test_household.id,
            template.id,
            quantity=Decimal('4'),
            at=AS_OF - timedelta(days=2),
            from_location_id=async_test_storage_location.id,
        )
        await db.commit()

        buckets = await core_api.stock_moves.aggregate_aging_buckets_async(
            db,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            as_of=AS_OF,
        )
        # Six, not ten: the buckets say what is on the shelf, and the shelf
        # holds what arrived minus what left.
        assert _total(buckets) == Decimal('6')

    async def test_the_oldest_receipt_gives_up_its_stock_first(
        self,
        real_async_db_session,
        async_test_household,
        async_test_storage_location,
    ):
        db = real_async_db_session
        template = await self._template(db, async_test_household.id)

        # 7 received 120 days ago, 5 received 10 days ago, 8 issued since.
        # The old receipt is exhausted and the young one gives up one unit.
        await _move(
            db,
            async_test_household.id,
            template.id,
            quantity=Decimal('7'),
            at=AS_OF - timedelta(days=120),
            to_location_id=async_test_storage_location.id,
        )
        await _move(
            db,
            async_test_household.id,
            template.id,
            quantity=Decimal('5'),
            at=AS_OF - timedelta(days=10),
            to_location_id=async_test_storage_location.id,
        )
        await _move(
            db,
            async_test_household.id,
            template.id,
            quantity=Decimal('8'),
            at=AS_OF - timedelta(days=1),
            from_location_id=async_test_storage_location.id,
        )
        await db.commit()

        buckets = {
            b.label: b.quantity
            for b in await core_api.stock_moves.aggregate_aging_buckets_async(
                db,
                organization_id=async_test_household.id,
                product_template_id=template.id,
                as_of=AS_OF,
            )
        }
        assert sum(buckets.values(), Decimal('0')) == Decimal('4')
        # Nothing is left of the batch that arrived first, so nothing in the
        # oldest bucket — the stock on the shelf is young.
        assert buckets['180+'] == Decimal('0')
        assert buckets['91-180'] == Decimal('0')
        assert buckets['0-30'] == Decimal('4')

    async def test_a_back_dated_report_does_not_see_a_later_issue(
        self,
        real_async_db_session,
        async_test_household,
        async_test_storage_location,
    ):
        db = real_async_db_session
        template = await self._template(db, async_test_household.id)

        await _move(
            db,
            async_test_household.id,
            template.id,
            quantity=Decimal('10'),
            at=AS_OF - timedelta(days=10),
            to_location_id=async_test_storage_location.id,
        )
        # The warehouse carried on working after the cutoff.
        await _move(
            db,
            async_test_household.id,
            template.id,
            quantity=Decimal('4'),
            at=AS_OF + timedelta(days=3),
            from_location_id=async_test_storage_location.id,
        )
        await db.commit()

        buckets = await core_api.stock_moves.aggregate_aging_buckets_async(
            db,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            as_of=AS_OF,
        )
        # A report about the 23rd says the same thing in December: on that
        # day the ten were still there.
        assert _total(buckets) == Decimal('10')

    async def test_a_product_with_more_receipts_than_a_page_still_ties_back(
        self,
        real_async_db_session,
        async_test_household,
        async_test_storage_location,
    ):
        """What is left is the newest stock, however many receipts came first.

        The receipts were read oldest first and cut at a thousand before the
        issues were netted off them, so the receipts that still stood on the
        shelf — the newest — were the ones cut. 1,005 single units received
        and the first 1,000 issued left five on the shelf and none in the
        buckets.
        """
        db = real_async_db_session
        template = await self._template(db, async_test_household.id)
        received = 1005
        start = AS_OF - timedelta(days=received + 10)
        await db.execute(
            insert(StockMove),
            [
                {
                    'id': uuid.uuid4(),
                    'organization_id': async_test_household.id,
                    'product_template_id': template.id,
                    'to_location_id': async_test_storage_location.id,
                    'quantity': Decimal('1'),
                    'state': 'done',
                    'created_at': start + timedelta(days=day),
                    'completed_at': start + timedelta(days=day),
                }
                for day in range(received)
            ],
        )
        await _move(
            db,
            async_test_household.id,
            template.id,
            quantity=Decimal('1000'),
            at=AS_OF - timedelta(days=1),
            from_location_id=async_test_storage_location.id,
        )
        await db.commit()

        buckets = {
            b.label: b.quantity
            for b in await core_api.stock_moves.aggregate_aging_buckets_async(
                db,
                organization_id=async_test_household.id,
                product_template_id=template.id,
                as_of=AS_OF,
            )
        }
        # The last five receipts, 11 to 15 days old.
        assert buckets['0-30'] == Decimal('5')
        assert sum(buckets.values(), Decimal('0')) == Decimal('5')

        entries = await core_api.stock_moves.list_receipts_for_aging_async(
            db,
            organization_id=async_test_household.id,
            product_template_id=template.id,
            as_of=AS_OF,
        )
        assert [e.days_in_stock for e in entries] == [15, 14, 13, 12, 11]
