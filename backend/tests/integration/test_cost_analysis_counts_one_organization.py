"""Cost analysis answers for the organization that asked, and no other.

The SPENT tile showed the same figure to every tenant -- 13,229.98 in an
organization with two products, in one with many, and in an empty one --
because the two queries behind it summed the valuation ledger with no
organization in their WHERE clause. Neither function even took an
``organization_id``, although the caller had one and passed it to every
neighbouring query.

The waste percentage inherited the same defect from the other side: a
numerator scoped to one organization over a denominator scoped to all of
them is not a percentage of anything.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.models.item_history import ItemAction, ItemHistory
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_valuation_layer import StockValuationLayer
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.services.analytics.cost import get_cost_summary_async
from tests.integration._shelf import anchor_pending_records

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _organization(
    db: AsyncSession, name: str
) -> tuple[Organization, StorageLocation]:
    """An organization with somewhere to put things.

    The summary returns zeros for an organization with no storage locations,
    so an empty one still needs a shelf to reach the queries under test.
    """
    from app.core.testing import ModuleTestHelper

    org = Organization(
        name=f'{name} {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'stats'],
        currency='USD',
    )
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'cost_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    storage_type = StorageType(
        name='Shelf', type_code=f'SHELF_{uuid.uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    location = StorageLocation(
        name='Aisle 1',
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=user.id,
    )
    db.add(location)
    await db.flush()
    return org, location


async def _receipt(
    db: AsyncSession,
    org: Organization,
    value: str,
    currency: str | None = None,
) -> ProductTemplate:
    """One receipt in today's window, worth ``value``."""
    template = ProductTemplate(
        organization_id=org.id,
        name='Widget',
        sku=f'W-{uuid.uuid4().hex[:8]}',
    )
    db.add(template)
    await db.flush()
    db.add(
        StockValuationLayer(
            organization_id=org.id,
            product_template_id=template.id,
            quantity=Decimal('1'),
            remaining_qty=Decimal('1'),
            unit_cost=Decimal(value),
            total_value=Decimal(value),
            document_date=date.today(),
            currency=currency,
            direction='IN',
        )
    )
    await db.flush()
    return template


class TestTheSumBelongsToOneOrganization:
    async def test_spent_counts_only_this_organizations_receipts(
        self, real_async_db_session: AsyncSession
    ):
        db = real_async_db_session
        mine, _ = await _organization(db, 'Mine')
        theirs, _ = await _organization(db, 'Theirs')
        await _receipt(db, mine, '100.00')
        await _receipt(db, theirs, '900.00')

        summary = await get_cost_summary_async(db, mine.id)

        assert summary.total_spent == 100.0

    async def test_an_organization_with_no_receipts_spent_nothing(
        self, real_async_db_session: AsyncSession
    ):
        db = real_async_db_session
        empty, _ = await _organization(db, 'Empty')
        busy, _ = await _organization(db, 'Busy')
        await _receipt(db, busy, '900.00')

        summary = await get_cost_summary_async(db, empty.id)

        assert summary.total_spent == 0.0

    async def test_the_foreign_currency_count_is_this_organizations_too(
        self, real_async_db_session: AsyncSession
    ):
        db = real_async_db_session
        mine, _ = await _organization(db, 'Mine')
        theirs, _ = await _organization(db, 'Theirs')
        await _receipt(db, mine, '100.00', currency='PLN')
        await _receipt(db, theirs, '900.00', currency='EUR')
        await _receipt(db, theirs, '900.00', currency='EUR')

        summary = await get_cost_summary_async(db, mine.id)

        assert summary.excluded_other_currency_count == 1


async def _discarded_record(
    db: AsyncSession,
    org: Organization,
    location: StorageLocation,
    template: ProductTemplate,
    value: str,
) -> None:
    """A record thrown away, with the outgoing layer that prices it.

    The waste figure reads three things at once: the disposal in the
    record's history, the outgoing layer keyed by that record, and the
    record's own shelf. Anything less and the report reads zero for a
    reason that has nothing to do with tenancy.
    """
    item = Item(
        organization_id=org.id,
        storage_location_id=location.id,
        template_id=template.id,
        name='Widget',
        quantity=Decimal('0'),
    )
    db.add(item)
    await db.run_sync(anchor_pending_records)
    await db.flush()
    db.add(
        ItemHistory(
            organization_id=org.id,
            item_id=item.id,
            action=ItemAction.DISPOSED.value,
            changes={'qty': 1},
        )
    )
    db.add(
        StockValuationLayer(
            organization_id=org.id,
            product_template_id=template.id,
            item_id=item.id,
            quantity=Decimal('1'),
            remaining_qty=Decimal('0'),
            unit_cost=Decimal(value),
            total_value=Decimal(value),
            document_date=date.today(),
            direction='OUT',
            reason=ItemAction.DISPOSED.value,
        )
    )
    await db.flush()


class TestThePercentageDividesLikeForLike:
    async def test_waste_is_a_share_of_this_organizations_spending(
        self, real_async_db_session: AsyncSession
    ):
        """Half of what one organization bought was thrown away.

        A neighbour that bought nine times as much must not turn that half
        into five percent.
        """
        db = real_async_db_session
        mine, shelf = await _organization(db, 'Mine')
        theirs, _ = await _organization(db, 'Theirs')
        template = await _receipt(db, mine, '100.00')
        await _receipt(db, theirs, '900.00')
        await _discarded_record(db, mine, shelf, template, '50.00')

        summary = await get_cost_summary_async(db, mine.id)

        assert summary.waste_value_percentage == 50.0
