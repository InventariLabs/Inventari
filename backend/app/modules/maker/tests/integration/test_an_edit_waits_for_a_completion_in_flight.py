"""An edit that read a DRAFT run before it was completed must not rewrite it.

``update_order`` read the run without a row lock, checked ``DRAFT`` against
that read, and then wrote ``planned_qty``, ``production_date`` and ``notes``.
An edit that read the run just before a completion committed waited on the
completion's row lock for its UPDATE, and wrote onto the run once it was
``COMPLETED``: the planned quantity of a run whose stock had already moved
changed, and the answer was a 200.

The completion here is a second session that holds the row lock and has
turned the status, not yet committed — the moment the edit has to survive.
The edit must wait for it and then be refused, not slip its fields in.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.exceptions import ServiceRejectionError
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.modules.maker import production_service
from app.modules.maker._schemas_production import (
    ProductionOrderCreate,
    ProductionOrderUpdate,
)
from app.modules.maker.models import MakerRecipe, ProductionOrder

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_an_edit_waits_for_a_completion_in_flight(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    org = Organization(name='Edit Race Org', enabled_modules=['core', 'maker'])
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email='edit-race@example.com', role='admin'
    )
    storage_type = StorageType(
        name='Edit Race Storage', type_code='MAKER', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    location = StorageLocation(
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=user.id,
        name='Edit Race Loc',
    )
    template = ProductTemplate(
        organization_id=org.id, name='Edit Race Out', removal_strategy='FIFO'
    )
    db.add_all([location, template])
    await db.flush()
    db.add(
        MakerRecipe(
            organization_id=org.id,
            output_template_id=template.id,
            name='Edit Race Recipe',
            batch_yield_qty=Decimal('1'),
            is_default=True,
        )
    )
    await db.flush()
    ctx = UserContextDTO(id=user.id, organization_id=org.id, role='admin')
    order = await production_service.create_order(
        db,
        org.id,
        ProductionOrderCreate(
            output_template_id=template.id,
            planned_qty=Decimal('2'),
            output_location_id=location.id,
            confirm_shortage=True,
        ),
        ctx,
    )
    order_id, org_id = order.id, org.id
    await db.commit()

    engine = db.bind
    completer = AsyncSession(bind=engine)
    editor = AsyncSession(bind=engine)
    try:
        # The completion: lock the row and turn it, commit still pending.
        locked = (
            await completer.execute(
                select(ProductionOrder)
                .where(ProductionOrder.id == order_id)
                .with_for_update()
            )
        ).scalar_one()
        locked.status = 'COMPLETED'
        await completer.flush()

        # The edit reads the run before the completion commits — it still
        # sees DRAFT — and then asks to change it.
        seen = await production_service.get_order(editor, org_id, order_id)
        assert seen is not None and seen.status == 'DRAFT'
        edit = asyncio.create_task(
            production_service.update_order(
                editor,
                org_id,
                order_id,
                ProductionOrderUpdate(planned_qty=Decimal('9')),
                ctx,
            )
        )
        await asyncio.sleep(0.5)
        assert not edit.done(), 'the edit did not wait for the completion'

        await completer.commit()
        with pytest.raises(ServiceRejectionError):
            await asyncio.wait_for(edit, timeout=5)
        await editor.rollback()
    finally:
        await completer.close()
        await editor.close()

    await db.rollback()
    stored = await db.scalar(
        select(ProductionOrder.planned_qty).where(ProductionOrder.id == order_id)
    )
    assert stored == Decimal('2'), f'the completed run now plans {stored}'
