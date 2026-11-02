"""Cancelling a run waits for a completion that is already under way.

Completing a run locks its row and moves it out of DRAFT; cancelling it only
read the row. A cancel that read DRAFT just before a completion committed
therefore went on to write CANCELLED over a run whose stock had already
moved, and both requests answered success. The cancel now locks the row as
the completion does, so whichever commits second finds the run no longer a
draft and is refused.

Here one transaction holds the run as a completion would, and the cancel
that arrives meanwhile must wait for it and then be refused.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.contracts import UserContextDTO
from app.core.exceptions import ServiceRejectionError
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.maker.models import ProductionOrder
from app.modules.maker.production_service import _lock_draft_order, cancel_order

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


async def test_a_cancel_arriving_during_a_completion_is_refused(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    org = Organization(
        name=f'Cancel race {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'maker'],
    )
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'cancel_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    shelf = StorageLocation(organization_id=org.id, created_by=user.id, name='Bench')
    output = ProductTemplate(organization_id=org.id, name='Jam')
    db.add_all([shelf, output])
    await db.flush()
    order = ProductionOrder(
        organization_id=org.id,
        output_template_id=output.id,
        recipe_id=None,
        planned_qty=Decimal('1'),
        output_storage_location_id=shelf.id,
        status='DRAFT',
        created_by=user.id,
    )
    db.add(order)
    await db.commit()
    org_id, user_id, order_id = org.id, user.id, order.id

    engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as completing, factory() as cancelling:
            # The completion's first move: the run is locked and leaves DRAFT.
            held = await _lock_draft_order(completing, org_id, order_id)
            held.status = 'COMPLETED'
            await completing.flush()

            cancel = asyncio.create_task(
                cancel_order(
                    cancelling,
                    org_id,
                    order_id,
                    UserContextDTO(id=user_id, organization_id=org_id),
                )
            )
            await asyncio.sleep(0.3)
            assert not cancel.done(), 'the cancel did not wait for the completion'
            await completing.commit()

            with pytest.raises(ServiceRejectionError):
                await cancel
            await cancelling.rollback()
    finally:
        await engine.dispose()
