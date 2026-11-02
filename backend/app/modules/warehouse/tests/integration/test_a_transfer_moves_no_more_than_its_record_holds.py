"""A transfer line cannot move more than the record it names holds.

A transfer line names a record, and the record goes to the other shelf with
the line's quantity. A line asking for more than the record held moved the
record whole, while the movement took the line's full quantity off the
shelf: six units of records changed shelves and the ledger said ten. The
shelf's other records still held the four the ledger had moved away, and
every reservation against the target was counted against stock the records
did not have.

The line is refused instead, before anything moves, and says how much the
record holds. The same happens when the record shrank after the document
was confirmed — an issue took from it in between — which is how the
concurrency probe met it.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.modules.warehouse._document_workflow_crud import create_document
from app.modules.warehouse._document_workflow_transitions import (
    complete_document,
    confirm_document,
)
from app.modules.warehouse.document_profile_service import get_or_create_profile
from app.modules.warehouse.schemas import (
    DocumentComplete,
    DocumentCreate,
    DocumentLineCreate,
)
from tests.integration._shelf import put_on_shelf

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _on_shelf(
    db: AsyncSession, template_id: uuid.UUID, shelf: uuid.UUID
) -> Decimal:
    total = await db.scalar(
        select(func.coalesce(func.sum(Item.quantity), 0)).where(
            Item.template_id == template_id,
            Item.storage_location_id == shelf,
            Item.is_deleted.is_(False),
        )
    )
    return Decimal(total or 0)


async def test_a_line_larger_than_its_record_is_refused_and_nothing_moves(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    org = Organization(
        name=f'Transfer ceiling {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'warehouse'],
    )
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'ceiling_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    shelves: list[uuid.UUID] = []
    for name in ('Aisle 1', 'Aisle 2'):
        location = StorageLocation(
            organization_id=org.id, created_by=user.id, name=name
        )
        db.add(location)
        await db.flush()
        shelves.append(location.id)
    source, target = shelves
    template = ProductTemplate(
        organization_id=org.id, name='Barley', sku=f'barley-{uuid.uuid4().hex[:8]}'
    )
    db.add(template)
    await db.flush()
    small = await put_on_shelf(db, user, template, source, 6)
    await put_on_shelf(db, user, template, source, 20)
    await get_or_create_profile(db, org.id)
    await db.commit()
    org_id, user_id, template_id = org.id, user.id, template.id

    doc = await create_document(
        db,
        org_id,
        DocumentCreate(
            type='INT',
            source_location_id=source,
            target_location_id=target,
            lines=[
                DocumentLineCreate(item_id=small.id, expected_quantity=Decimal('10'))
            ],
        ),
        user_id,
    )
    await confirm_document(db, org_id, doc.id, user_id)

    refusal: ValueError | None = None
    try:
        await complete_document(
            db, org_id, doc.id, user_id, DocumentComplete(complete_as_planned=True)
        )
    except ValueError as exc:
        refusal = exc
        await db.rollback()

    db.expire_all()
    moved = await db.scalar(
        select(func.coalesce(func.sum(StockMove.quantity), 0)).where(
            StockMove.product_template_id == template_id,
            StockMove.from_location_id == source,
            StockMove.to_location_id == target,
        )
    )
    assert (
        await _on_shelf(db, template_id, source),
        await _on_shelf(db, template_id, target),
        Decimal(moved or 0),
    ) == (Decimal('26'), Decimal('0'), Decimal('0'))
    assert refusal is not None
    assert 'Barley' in str(refusal) and '6' in str(refusal), str(refusal)
