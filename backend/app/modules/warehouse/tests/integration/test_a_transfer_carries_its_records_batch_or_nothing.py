"""A transfer carries the batch its record holds, or nothing.

A transfer moves a record, and the record is one batch: the movement
carries that batch. When the batch's free stock on the shelf could not
cover the line — the rest of it promised to an issue already confirmed —
the transfer fell back to the removal order, which handed over another
batch. The record of the first batch changed shelves and the ledger moved
the second: the shelf held fewer of the promised batch than the issue
reserved, and more of the other than the ledger said.

The transfer is now refused in that case, and the promise stands. The
fallback remains for a batch the shelf does not hold at all — a record
naming a batch its quant was never given, the shape an older receipt left.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api
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
from app.modules.warehouse.schemas import DocumentCreate, DocumentLineCreate
from tests.integration._shelf import put_on_shelf

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _by_batch(
    db: AsyncSession, template_id: uuid.UUID
) -> dict[tuple[uuid.UUID | None, uuid.UUID | None], Decimal]:
    rows = await db.execute(
        select(Item.storage_location_id, Item.lot_id, func.sum(Item.quantity))
        .where(Item.template_id == template_id, Item.is_deleted.is_(False))
        .group_by(Item.storage_location_id, Item.lot_id)
    )
    return {(shelf, lot): Decimal(qty) for shelf, lot, qty in rows.all()}


async def _moved(
    db: AsyncSession, template_id: uuid.UUID, source: uuid.UUID, target: uuid.UUID
) -> dict[uuid.UUID | None, Decimal]:
    rows = await db.execute(
        select(StockMove.lot_id, func.sum(StockMove.quantity))
        .where(
            StockMove.product_template_id == template_id,
            StockMove.from_location_id == source,
            StockMove.to_location_id == target,
        )
        .group_by(StockMove.lot_id)
    )
    return {lot: Decimal(qty) for lot, qty in rows.all()}


async def test_a_transfer_whose_batch_is_promised_elsewhere_is_refused(
    real_async_db_session: AsyncSession,
) -> None:
    db = real_async_db_session
    org = Organization(
        name=f'Batch or nothing {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'warehouse'],
    )
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'batch_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    shelves: list[uuid.UUID] = []
    for name in ('Chiller', 'Back room'):
        location = StorageLocation(
            organization_id=org.id, created_by=user.id, name=name
        )
        db.add(location)
        await db.flush()
        shelves.append(location.id)
    source, target = shelves
    template = ProductTemplate(
        organization_id=org.id,
        name='Kefir',
        sku=f'kefir-{uuid.uuid4().hex[:8]}',
        removal_strategy='FEFO',
    )
    db.add(template)
    await db.flush()
    records: dict[str, Any] = {}
    for batch, days in (('K-EARLY', 5), ('K-LATE', 30)):
        expires = date.today() + timedelta(days=days)
        lot_id = await core_api.stock.get_or_create_lot_async(
            db, org.id, template.id, batch, expiry_date=expires
        )
        records[batch] = await put_on_shelf(
            db, user, template, source, 20, lot_id=lot_id, expiry_date=expires
        )
    await get_or_create_profile(db, org.id)
    await db.commit()
    org_id, user_id, template_id = org.id, user.id, template.id
    early_record, early_lot = records['K-EARLY'].id, records['K-EARLY'].lot_id

    async def confirmed(data: DocumentCreate) -> uuid.UUID:
        doc = await create_document(db, org_id, data, user_id)
        await confirm_document(db, org_id, doc.id, user_id)
        return doc.id

    # An issue of fifteen, first-expiring first: fifteen of the early batch are promised.
    await confirmed(
        DocumentCreate(
            type='OUT',
            source_location_id=source,
            lines=[
                DocumentLineCreate(
                    item_id=early_record,
                    product_template_id=template_id,
                    expected_quantity=Decimal('15'),
                )
            ],
        )
    )
    # Ten of the early batch's record to the back room; five of that batch are
    # free. The confirmation reserves the record's own batch, so it is
    # refused there already; a completion meeting the same shortfall refuses
    # all the same.
    refusal: ValueError | None = None
    try:
        transfer = await confirmed(
            DocumentCreate(
                type='INT',
                source_location_id=source,
                target_location_id=target,
                lines=[
                    DocumentLineCreate(
                        item_id=early_record, expected_quantity=Decimal('10')
                    )
                ],
            )
        )
        await complete_document(db, org_id, transfer, user_id)
    except ValueError as exc:
        refusal = exc
        await db.rollback()

    db.expire_all()
    shelved = await _by_batch(db, template_id)
    moved = await _moved(db, template_id, source, target)
    # The records and the ledger agree batch by batch: here nothing moved.
    assert (shelved.get((target, early_lot)), moved) == (None, {}), (
        shelved,
        moved,
        refusal,
    )
    assert shelved[(source, early_lot)] == Decimal('20')
    assert refusal is not None
