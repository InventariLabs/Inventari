"""Two organizations stocking the same catalogue product see their own cost.

Valuation layers belong to an organization. The AVCO rate computed from them
was cached in one column on ``product_templates``, and a global template — the
whole default catalogue — is a single row every organization uses. So the
number there belonged to whichever organization had last taken a delivery: a
company could read a competitor's purchase cost off a catalogue product, and
value its own stock with it. Which one won came down to write order.

The readers were already org-scoped in the sense that mattered least: they
checked you were allowed to see *the template*. The figure itself was shared,
so the check did nothing.

Both readers are covered here — the single lookup and the batch one a BoM cost
rollup uses — because they read the column independently and would have had to
be fixed independently.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.services.valuation_service import ValuationService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

EXPENSIVE = Decimal('9.00')
CHEAP = Decimal('2.00')


async def _second_org(db: AsyncSession) -> Organization:
    org = Organization(name=f'Second {uuid4().hex[:8]}', currency='USD')
    db.add(org)
    await db.flush()
    return org


async def _catalogue_product(db: AsyncSession) -> ProductTemplate:
    """A global template: organization_id is NULL, so everybody uses this row."""
    template = ProductTemplate(
        organization_id=None,
        name='Catalogue Flour',
        sku=f'CF-{uuid4().hex[:8]}',
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)
    return template


@pytest.fixture
async def two_organizations_one_product(
    real_async_db_session: AsyncSession, async_test_household
):
    db = real_async_db_session
    other = await _second_org(db)
    shared = await _catalogue_product(db)

    # Same product, same day, different suppliers.
    await ValuationService._record_receipt_async(
        db, shared, Decimal('10'), EXPENSIVE, async_test_household.id
    )
    await ValuationService._record_receipt_async(
        db, shared, Decimal('10'), CHEAP, other.id
    )
    await db.flush()
    return db, async_test_household, other, shared


async def test_each_organization_reads_its_own_rate(
    two_organizations_one_product,
) -> None:
    db, mine, other, shared = two_organizations_one_product

    assert (
        await ValuationService.get_current_valuation_rate_async(db, mine.id, shared.id)
        == EXPENSIVE
    )
    assert (
        await ValuationService.get_current_valuation_rate_async(db, other.id, shared.id)
        == CHEAP
    )


async def test_the_batch_read_answers_the_same_way(
    two_organizations_one_product,
) -> None:
    """The BoM rollup's reader. It had its own copy of the column read."""
    db, mine, other, shared = two_organizations_one_product

    assert await ValuationService.get_valuation_rates_batch_async(
        db, mine.id, [shared.id]
    ) == {shared.id: EXPENSIVE}
    assert await ValuationService.get_valuation_rates_batch_async(
        db, other.id, [shared.id]
    ) == {shared.id: CHEAP}


async def test_write_order_no_longer_decides(
    two_organizations_one_product,
) -> None:
    """A later delivery elsewhere must not move this organization's figure.

    This is the shape the defect actually took: nobody set out to read somebody
    else's cost, they just took a delivery after them.
    """
    db, mine, other, shared = two_organizations_one_product

    await ValuationService._record_receipt_async(
        db, shared, Decimal('90'), Decimal('1.00'), other.id
    )
    await db.flush()

    assert (
        await ValuationService.get_current_valuation_rate_async(db, mine.id, shared.id)
        == EXPENSIVE
    )


async def test_an_organization_without_layers_has_no_rate(
    two_organizations_one_product,
) -> None:
    """Not a fallback to whatever the catalogue row happened to hold."""
    db, mine, other, shared = two_organizations_one_product
    third = await _second_org(db)

    assert (
        await ValuationService.get_current_valuation_rate_async(db, third.id, shared.id)
        is None
    )
    assert await ValuationService.get_valuation_rates_batch_async(
        db, third.id, [shared.id]
    ) == {shared.id: None}
