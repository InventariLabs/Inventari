"""A document's transitions write inside the caller's transaction and never commit.

Confirming reserves the stock, completing posts it, cancelling gives the
reservation back. Each used to commit as it finished, so a request that failed
after the service returned (the response could not be built, a later step of
the same request was refused) found the document already moved and the stock
already posted, with nothing left to roll back.

The transitions flush instead and the request-scoped session commits once. A
failure after the point where the commit used to be therefore takes the
document, the movement and the reservation back together.
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
    cancel_document,
    complete_document,
    confirm_document,
)
from app.modules.warehouse.document_profile_service import get_or_create_profile
from app.modules.warehouse.models import Document, DocumentStatus
from app.modules.warehouse.schemas import (
    DocumentComplete,
    DocumentCreate,
    DocumentLineCreate,
)
from tests.integration._shelf import put_on_shelf

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class _Scene:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.commits = 0

    async def build(self) -> None:
        db = self.db
        org = Organization(
            name=f'Transitions {uuid.uuid4().hex[:6]}',
            enabled_modules=['core', 'items', 'locations', 'warehouse'],
        )
        db.add(org)
        await db.flush()
        user = await ModuleTestHelper.create_user_async(
            db, org, email=f'moves_{uuid.uuid4().hex[:8]}@test.com', role='admin'
        )
        shelves: list[uuid.UUID] = []
        for name in ('Aisle 1', 'Aisle 2'):
            location = StorageLocation(
                organization_id=org.id, created_by=user.id, name=name
            )
            db.add(location)
            await db.flush()
            shelves.append(location.id)
        template = ProductTemplate(
            organization_id=org.id,
            name='Barley',
            sku=f'barley-{uuid.uuid4().hex[:8]}',
        )
        db.add(template)
        await db.flush()
        record = await put_on_shelf(db, user, template, shelves[0], 20)
        await get_or_create_profile(db, org.id)
        await db.commit()
        self.org_id, self.user_id = org.id, user.id
        self.template_id, self.record_id = template.id, record.id
        self.source, self.target = shelves

        doc = await create_document(
            db,
            self.org_id,
            DocumentCreate(
                type='INT',
                source_location_id=self.source,
                target_location_id=self.target,
                lines=[
                    DocumentLineCreate(
                        item_id=self.record_id, expected_quantity=Decimal('5')
                    )
                ],
            ),
            self.user_id,
        )
        await db.commit()
        self.doc_id = doc.id

        real_commit = db.commit

        async def counting_commit() -> None:
            self.commits += 1
            await real_commit()

        db.commit = counting_commit  # type: ignore[method-assign]

    async def the_request_fails_afterwards(self) -> None:
        """What the request-scoped session does when the endpoint raises."""
        await self.db.rollback()
        self.db.expire_all()

    async def status(self) -> str:
        return str(
            await self.db.scalar(
                select(Document.status).where(Document.id == self.doc_id)
            )
        )

    async def moved(self) -> Decimal:
        total = await self.db.scalar(
            select(func.coalesce(func.sum(StockMove.quantity), 0)).where(
                StockMove.product_template_id == self.template_id,
                StockMove.from_location_id == self.source,
                StockMove.to_location_id == self.target,
            )
        )
        return Decimal(total or 0)

    async def on_source(self) -> Decimal:
        total = await self.db.scalar(
            select(func.coalesce(func.sum(Item.quantity), 0)).where(
                Item.template_id == self.template_id,
                Item.storage_location_id == self.source,
                Item.is_deleted.is_(False),
            )
        )
        return Decimal(total or 0)


async def test_a_failure_after_confirming_leaves_the_draft_a_draft(
    real_async_db_session: AsyncSession,
) -> None:
    scene = _Scene(real_async_db_session)
    await scene.build()

    await confirm_document(
        real_async_db_session, scene.org_id, scene.doc_id, scene.user_id
    )
    assert await scene.status() == DocumentStatus.CONFIRMED.value
    await scene.the_request_fails_afterwards()

    assert scene.commits == 0
    assert await scene.status() == DocumentStatus.DRAFT.value


async def test_a_failure_after_completing_leaves_the_stock_where_it_was(
    real_async_db_session: AsyncSession,
) -> None:
    scene = _Scene(real_async_db_session)
    await scene.build()
    db = real_async_db_session
    await confirm_document(db, scene.org_id, scene.doc_id, scene.user_id)
    await db.commit()
    scene.commits = 0

    await complete_document(
        db,
        scene.org_id,
        scene.doc_id,
        scene.user_id,
        DocumentComplete(complete_as_planned=True),
    )
    assert await scene.status() == DocumentStatus.COMPLETED.value
    await scene.the_request_fails_afterwards()

    assert scene.commits == 0
    assert await scene.status() == DocumentStatus.CONFIRMED.value
    assert await scene.moved() == Decimal('0')
    assert await scene.on_source() == Decimal('20')


async def test_a_failure_after_cancelling_keeps_the_document_and_its_reservation(
    real_async_db_session: AsyncSession,
) -> None:
    scene = _Scene(real_async_db_session)
    await scene.build()
    db = real_async_db_session
    await confirm_document(db, scene.org_id, scene.doc_id, scene.user_id)
    await db.commit()
    scene.commits = 0

    await cancel_document(db, scene.org_id, scene.doc_id, scene.user_id)
    assert await scene.status() == DocumentStatus.CANCELLED.value
    await scene.the_request_fails_afterwards()

    assert scene.commits == 0
    assert await scene.status() == DocumentStatus.CONFIRMED.value
