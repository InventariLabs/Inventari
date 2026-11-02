"""Two receipts confirmed in the same instant cannot both take the whole order.

The pre-post check reads what the order line allows and what other documents have
already claimed, then lets the document through. Two confirmations landing
together each read the line before the other had written against it, and
each saw the whole order still free. The order line is now locked for the
rest of the transaction when its ceiling is read, so the second reader
waits for the first to finish -- and then finds the order spoken for.

The two documents are built inside their own transactions here, unnumbered
by the numbering service: two drafts already on the books count against
each other whatever the order, and the numbering counter's own lock would
otherwise serialise the two by accident. The first side asks the guard and
holds its transaction open -- the confirmation service commits on its way
out, which would hand the second side an ordinary refusal and prove
nothing about the lock. This is the shape the guard has to hold on its own.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.storage_type import StorageType
from app.modules.purchase_orders.models import PurchaseOrder, PurchaseOrderLine
from app.modules.warehouse._document_workflow_transitions import confirm_document
from app.modules.warehouse.document_profile_service import get_or_create_profile
from app.modules.warehouse.models import Document, DocumentLine, DocumentStatus
from app.modules.warehouse.pre_post_checks import run_pre_post_checks_async

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

ORDERED = Decimal('10')


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


class _Order:
    def __init__(self) -> None:
        self.org_id: uuid.UUID
        self.user_id: uuid.UUID
        self.location_id: uuid.UUID
        self.template_id: uuid.UUID
        self.po_line_id: uuid.UUID


async def _confirmed_order(db: AsyncSession) -> _Order:
    """One confirmed order of ten, and everything a receipt against it needs."""
    fixture = _Order()
    org = Organization(
        name=f'At once {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'warehouse', 'purchase_orders'],
    )
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'atonce_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    storage_type = StorageType(
        name='Dock', type_code=f'DOCK_{uuid.uuid4().hex[:6]}', behavior_mode='NONE'
    )
    db.add(storage_type)
    await db.flush()
    location = StorageLocation(
        name='Dock 1',
        organization_id=org.id,
        storage_type_id=storage_type.id,
        created_by=user.id,
    )
    template = ProductTemplate(
        organization_id=org.id, name='Olive oil', sku=f'OO-{uuid.uuid4().hex[:8]}'
    )
    db.add_all([location, template])
    await db.flush()
    order = PurchaseOrder(
        organization_id=org.id,
        number=f'PO/T/{uuid.uuid4().hex[:6]}',
        status='CONFIRMED',
        created_by=user.id,
    )
    db.add(order)
    await db.flush()
    line = PurchaseOrderLine(
        purchase_order_id=order.id,
        product_template_id=template.id,
        name='Olive oil',
        quantity_ordered=ORDERED,
        line_number=1,
    )
    db.add(line)
    # Confirmation reads the profile; created here so that the two
    # transactions below do not race on creating it instead.
    await get_or_create_profile(db, org.id)
    await db.flush()
    await db.commit()

    fixture.org_id = org.id
    fixture.user_id = user.id
    fixture.location_id = location.id
    fixture.template_id = template.id
    fixture.po_line_id = line.id
    return fixture


async def _draft_for_the_whole_order(db: AsyncSession, order: _Order) -> Document:
    doc = Document(
        organization_id=order.org_id,
        type='IN',
        number=f'IN/T/{uuid.uuid4().hex[:6]}',
        status=DocumentStatus.DRAFT.value,
        target_location_id=order.location_id,
        created_by=order.user_id,
    )
    db.add(doc)
    await db.flush()
    db.add(
        DocumentLine(
            document_id=doc.id,
            line_number=1,
            name='Olive oil',
            product_template_id=order.template_id,
            quantity=ORDERED,
            expected_quantity=ORDERED,
            done_quantity=Decimal('0'),
            source_po_line_id=order.po_line_id,
        )
    )
    await db.flush()
    db.expire(doc, ['lines'])
    return doc


class TestTwoReceiptsAtOnceTakeTheOrderOnce:
    async def test_the_second_confirmation_waits_and_is_refused(
        self, real_async_db_session: AsyncSession
    ) -> None:
        order = await _confirmed_order(real_async_db_session)
        engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        first = factory()
        second = factory()
        try:
            # The first receipt passes the guard and holds its transaction
            # open, the way a confirmation does until it commits.
            doc_a = await _draft_for_the_whole_order(first, order)
            await first.refresh(doc_a, attribute_names=['lines'])
            await run_pre_post_checks_async(
                first, order.org_id, doc_a, 'confirm', confirmed_by=None
            )
            doc_a.status = DocumentStatus.CONFIRMED.value
            await first.flush()

            async def confirm_the_second() -> None:
                doc_b = await _draft_for_the_whole_order(second, order)
                await confirm_document(second, order.org_id, doc_b.id, order.user_id)
                await second.commit()

            waiting = asyncio.create_task(confirm_the_second())
            await asyncio.sleep(0.3)
            # Not refused yet and not let through: it is waiting on the line.
            assert not waiting.done()

            await first.commit()
            with pytest.raises(ValueError, match='order'):
                await waiting
            await second.rollback()
        finally:
            await first.close()
            await second.close()
            await engine.dispose()

        confirmed = await real_async_db_session.scalar(
            select(func.count(Document.id))
            .join(DocumentLine, DocumentLine.document_id == Document.id)
            .where(
                DocumentLine.source_po_line_id == order.po_line_id,
                Document.status == DocumentStatus.CONFIRMED.value,
            )
        )
        assert confirmed == 1
