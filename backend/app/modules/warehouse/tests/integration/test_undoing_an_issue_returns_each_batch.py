"""Undoing an issue that drew across batches puts each batch back.

An issue (or a write-off) of two on a shelf holding one batchless and one of batch L-1 draws
one from each. Undoing it used to write a single correction line that named
no batch, so the quantity came back as one batchless record and the recall
trace of L-1 was gone. The issue now stands on one line per batch it took,
and the undo restates each of them.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_lot import StockLot
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.models.user import User
from app.modules.warehouse._document_workflow_transitions import post_new_document
from app.modules.warehouse.document_correction_service import undo_document
from app.modules.warehouse.document_profile_service import create_default_profile
from app.modules.warehouse.schemas import DocumentCreate, DocumentLineCreate

pytestmark = pytest.mark.integration


async def _held_by_batch(
    db: AsyncSession, org_id: UUID, template_id: UUID, shelf_id: UUID
) -> dict[str | None, Decimal]:
    rows = await db.execute(
        select(StockLot.name, Item.quantity)
        .select_from(Item)
        .outerjoin(StockLot, StockLot.id == Item.lot_id)
        .where(
            Item.organization_id == org_id,
            Item.template_id == template_id,
            Item.storage_location_id == shelf_id,
            Item.is_deleted.is_(False),
            Item.quantity > 0,
        )
    )
    return {name: Decimal(str(quantity)) for name, quantity in rows.all()}


async def _moved_by_batch(
    db: AsyncSession, org_id: UUID, template_id: UUID, shelf_id: UUID
) -> dict[str | None, Decimal]:
    """What the ledger says the shelf holds per batch: arrivals less departures."""
    rows = await db.execute(
        select(
            StockLot.name,
            func.sum(
                case(
                    (StockMove.to_location_id == shelf_id, StockMove.quantity),
                    else_=-StockMove.quantity,
                )
            ),
        )
        .select_from(StockMove)
        .outerjoin(StockLot, StockLot.id == StockMove.lot_id)
        .where(
            StockMove.organization_id == org_id,
            StockMove.product_template_id == template_id,
        )
        .group_by(StockLot.name)
    )
    return {name: Decimal(str(total)) for name, total in rows.all() if total}


async def _shelf_receiving(
    db: AsyncSession, batches: tuple[str | None, ...]
) -> tuple[Organization, User, ProductTemplate, StorageLocation]:
    """A shelf that received one unit of a product per batch, in the order given."""
    org = Organization(
        name=f'Undo batches {uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'warehouse'],
    )
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'undo-batches-{uuid4().hex[:8]}@test.com'
    )
    shelf = StorageLocation(organization_id=org.id, created_by=user.id, name='Shelf')
    template = ProductTemplate(
        organization_id=org.id, name='Rice', sku=f'Rice-{uuid4().hex[:8]}'
    )
    db.add_all([shelf, template])
    await db.flush()
    await create_default_profile(db, org.id)
    await db.commit()

    for batch in batches:
        await post_new_document(
            db,
            org.id,
            DocumentCreate(
                type='IN',
                target_location_id=shelf.id,
                lines=[
                    DocumentLineCreate(
                        product_template_id=template.id,
                        expected_quantity=Decimal('1'),
                        unit_price=Decimal('1.00'),
                        batch_number=batch,
                    )
                ],
            ),
            user.id,
        )
    return org, user, template, shelf


@pytest.mark.asyncio
@pytest.mark.parametrize('doc_type', ['OUT', 'SCRAP'])
async def test_undo_of_a_two_batch_issue_restores_each_batch(
    real_async_db_session: AsyncSession, doc_type: str
) -> None:
    db = real_async_db_session
    org, user, template, shelf = await _shelf_receiving(db, (None, 'L-1'))
    before = await _held_by_batch(db, org.id, template.id, shelf.id)
    assert before == {None: Decimal('1'), 'L-1': Decimal('1')}

    record = (
        await db.scalars(
            select(Item.id).where(
                Item.organization_id == org.id, Item.template_id == template.id
            )
        )
    ).first()
    issue = await post_new_document(
        db,
        org.id,
        DocumentCreate(
            type=doc_type,
            source_location_id=shelf.id,
            reason_code='DAMAGED' if doc_type == 'SCRAP' else None,
            lines=[
                DocumentLineCreate(
                    item_id=record,
                    product_template_id=template.id,
                    expected_quantity=Decimal('2'),
                    unit_price=Decimal('1.00'),
                )
            ],
        ),
        user.id,
    )
    assert await _held_by_batch(db, org.id, template.id, shelf.id) == {}

    await undo_document(db, org.id, issue.id, user.id)

    assert await _held_by_batch(db, org.id, template.id, shelf.id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize('doc_type', ['OUT', 'SCRAP'])
async def test_undo_of_a_one_batch_issue_from_another_record_restores_that_batch(
    real_async_db_session: AsyncSession, doc_type: str
) -> None:
    """The line names the batchless record, but the draw takes the batch.

    The batch arrived first, so the draw takes it. The line must stand on the
    record the goods left, or its undo would return the unit to the record the
    line names while the ledger credits the batch.
    """
    db = real_async_db_session
    org, user, template, shelf = await _shelf_receiving(db, ('L-1', None))
    before = await _held_by_batch(db, org.id, template.id, shelf.id)
    assert before == {None: Decimal('1'), 'L-1': Decimal('1')}
    batchless = await db.scalar(
        select(Item.id).where(
            Item.organization_id == org.id,
            Item.template_id == template.id,
            Item.lot_id.is_(None),
        )
    )
    issue = await post_new_document(
        db,
        org.id,
        DocumentCreate(
            type=doc_type,
            source_location_id=shelf.id,
            reason_code='DAMAGED' if doc_type == 'SCRAP' else None,
            lines=[
                DocumentLineCreate(
                    item_id=batchless,
                    product_template_id=template.id,
                    expected_quantity=Decimal('1'),
                    unit_price=Decimal('1.00'),
                )
            ],
        ),
        user.id,
    )
    assert await _held_by_batch(db, org.id, template.id, shelf.id) == {
        None: Decimal('1')
    }

    await undo_document(db, org.id, issue.id, user.id)

    assert await _held_by_batch(db, org.id, template.id, shelf.id) == before
    assert await _moved_by_batch(db, org.id, template.id, shelf.id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize('doc_type', ['OUT', 'SCRAP'])
async def test_undo_of_a_batchless_issue_from_a_batch_record_restores_batchless(
    real_async_db_session: AsyncSession, doc_type: str
) -> None:
    """The line names the batch's record, but the draw takes the batchless unit.

    The batchless unit arrived first and carries no date, so the draw takes it
    and the line has neither a date nor a batch to say so. It must still stand
    on the record the goods left, or its undo would credit the named batch.
    """
    db = real_async_db_session
    org, user, template, shelf = await _shelf_receiving(db, (None, 'L-1'))
    before = await _held_by_batch(db, org.id, template.id, shelf.id)
    assert before == {None: Decimal('1'), 'L-1': Decimal('1')}
    in_batch = await db.scalar(
        select(Item.id).where(
            Item.organization_id == org.id,
            Item.template_id == template.id,
            Item.lot_id.is_not(None),
        )
    )
    issue = await post_new_document(
        db,
        org.id,
        DocumentCreate(
            type=doc_type,
            source_location_id=shelf.id,
            reason_code='DAMAGED' if doc_type == 'SCRAP' else None,
            lines=[
                DocumentLineCreate(
                    item_id=in_batch,
                    product_template_id=template.id,
                    expected_quantity=Decimal('1'),
                    unit_price=Decimal('1.00'),
                )
            ],
        ),
        user.id,
    )
    assert await _held_by_batch(db, org.id, template.id, shelf.id) == {
        'L-1': Decimal('1')
    }

    await undo_document(db, org.id, issue.id, user.id)

    assert await _held_by_batch(db, org.id, template.id, shelf.id) == before
    assert await _moved_by_batch(db, org.id, template.id, shelf.id) == before
