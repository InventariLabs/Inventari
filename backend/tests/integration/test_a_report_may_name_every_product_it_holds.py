"""A report over a big warehouse names tens of thousands of products at once.

The occupancy map and the stock-as-of report resolve every product they hold
in one read. With one bind parameter per id the driver refuses the statement
past 32 767 of them, and both screens answered 500 on an organization of 100 000
products. The ids travel as one array instead.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.services._product_template_reads import list_templates_by_ids_async

pytestmark = pytest.mark.integration

#: Past the driver's limit on the arguments of one statement.
_MORE_THAN_THE_DRIVER_ALLOWS = 40_000


async def test_more_ids_than_the_driver_has_parameters_are_resolved(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    org = Organization(name='Big warehouse')
    db.add(org)
    await db.flush()
    template = ProductTemplate(organization_id=org.id, name='Flour')
    db.add(template)
    await db.flush()

    ids = [uuid4() for _ in range(_MORE_THAN_THE_DRIVER_ALLOWS)] + [template.id]

    found = await list_templates_by_ids_async(db, org.id, ids)

    assert [t.id for t in found] == [template.id]
