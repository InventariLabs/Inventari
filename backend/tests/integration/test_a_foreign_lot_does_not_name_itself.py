"""Refusing a batch must not describe a batch the caller cannot see.

``assert_lot_consumable_async`` fetched the lot by bare id and put its name
and status into the refusal. Someone guessing an id therefore learned three
things about another organization's batch: that the row exists, what they
call it, and what state it is in. Outside this organization the answer is now
the same as for a lot that does not exist — nothing.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.user import User
from app.services._stock_quant_query import assert_lot_consumable_async


@pytest.fixture
async def other_org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(name='Elsewhere', enabled_modules=['core'])
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(org)
    return org


async def _quarantined_lot(db: AsyncSession, org_id, name: str) -> StockLot:
    template = ProductTemplate(organization_id=org_id, name=f'{name} product')
    db.add(template)
    await db.flush()

    lot = StockLot(
        organization_id=org_id,
        product_template_id=template.id,
        name=name,
        status='QUARANTINE',
    )
    db.add(lot)
    await db.flush()
    await db.refresh(lot)
    return lot


@pytest.mark.integration
@pytest.mark.asyncio
class TestTheRefusalStaysInsideTheOrganization:
    async def test_a_lot_of_another_organization_says_nothing(
        self,
        real_async_db_session: AsyncSession,
        other_org: Organization,
        async_test_user: User,
    ) -> None:
        theirs = await _quarantined_lot(
            real_async_db_session, other_org.id, 'THEIR-SECRET-BATCH'
        )

        # No exception: from here, that lot is indistinguishable from one that
        # never existed. The caller fails on the missing quant instead.
        await assert_lot_consumable_async(
            real_async_db_session, theirs.id, async_test_user.organization_id
        )

    async def test_my_own_quarantined_lot_is_still_refused_by_name(
        self,
        real_async_db_session: AsyncSession,
        async_test_user: User,
    ) -> None:
        mine = await _quarantined_lot(
            real_async_db_session, async_test_user.organization_id, 'MY-BATCH'
        )

        with pytest.raises(ValueError, match='MY-BATCH'):
            await assert_lot_consumable_async(
                real_async_db_session, mine.id, async_test_user.organization_id
            )

    async def test_a_lot_that_never_existed_is_not_this_functions_business(
        self, real_async_db_session: AsyncSession, async_test_user: User
    ) -> None:
        await assert_lot_consumable_async(
            real_async_db_session, uuid4(), async_test_user.organization_id
        )
