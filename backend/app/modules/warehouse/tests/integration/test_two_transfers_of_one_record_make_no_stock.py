"""Two transfers of part of one record, completed at once, move only what exists.

A transfer that names less than its record holds splits the record: it rides
to the other shelf with the line's quantity, and what is left stays behind
as a record of its own. The split worked out that remainder from the record
the document had loaded along with its lines — before the stock was locked.
Two people each moving five off the same twenty therefore both split twenty:
the second, having waited for the first, still left fifteen behind, next to
the fifteen the first had left, and the shelves held ten more than anyone
had ever received.

Each completion here is held after it has read its document and before it
locks the stock until the other has got that far too, or for two seconds —
the interleaving that made the stock. The first to get the lock moves its
five; the record the second one names is no longer on the shelf it was to
leave, and that transfer is refused rather than carried out on a number
that stopped being true.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.testing import ModuleTestHelper
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_move import StockMove
from app.models.storage_location import StorageLocation
from app.modules.warehouse import _document_workflow_transitions
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

#: Which of the two completions the running task is.
_WHO: contextvars.ContextVar[str] = contextvars.ContextVar('who')


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


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


async def test_two_transfers_of_one_record_move_only_what_it_holds(
    real_async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = real_async_db_session
    org = Organization(
        name=f'Two transfers {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'warehouse'],
    )
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'carry_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    shelves = []
    for name in ('Aisle 1', 'Aisle 2'):
        shelf = StorageLocation(organization_id=org.id, created_by=user.id, name=name)
        db.add(shelf)
        await db.flush()
        shelves.append(shelf.id)
    source, target = shelves
    template = ProductTemplate(
        organization_id=org.id, name='Oats', sku=f'oats-{uuid.uuid4().hex[:8]}'
    )
    db.add(template)
    await db.flush()
    record = await put_on_shelf(db, user, template, source, 20)
    await get_or_create_profile(db, org.id)
    org_id, user_id, template_id, record_id = org.id, user.id, template.id, record.id

    transfers = []
    for _ in range(2):
        doc = await create_document(
            db,
            org_id,
            DocumentCreate(
                type='INT',
                source_location_id=source,
                target_location_id=target,
                lines=[
                    DocumentLineCreate(
                        item_id=record_id, expected_quantity=Decimal('5')
                    )
                ],
            ),
            user_id,
        )
        await confirm_document(db, org_id, doc.id, user_id)
        transfers.append(doc.id)
    # The two sessions below read what the setup kept, not what it staged.
    await db.commit()

    arrived = {'first': asyncio.Event(), 'second': asyncio.Event()}
    release = _document_workflow_transitions._release_quants_for_doc

    async def wait_for_the_other_then_lock(*args: Any, **kwargs: Any) -> Any:
        me = _WHO.get(None)
        if me is not None and not arrived[me].is_set():
            arrived[me].set()
            other = 'second' if me == 'first' else 'first'
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(arrived[other].wait(), timeout=2)
        return await release(*args, **kwargs)

    monkeypatch.setattr(
        _document_workflow_transitions,
        '_release_quants_for_doc',
        wait_for_the_other_then_lock,
    )

    engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def complete(name: str, doc_id: uuid.UUID) -> None:
        _WHO.set(name)
        # ``begin()`` commits when the door returns, as the request does.
        async with factory() as session, session.begin():
            await complete_document(
                session,
                org_id,
                doc_id,
                user_id,
                DocumentComplete(complete_as_planned=True),
            )

    try:
        outcomes = await asyncio.gather(
            complete('first', transfers[0]),
            complete('second', transfers[1]),
            return_exceptions=True,
        )
    finally:
        await engine.dispose()

    db.expire_all()
    left = await _on_shelf(db, template_id, source)
    arrived_there = await _on_shelf(db, template_id, target)
    ledger = await db.scalar(
        select(func.coalesce(func.sum(StockMove.quantity), 0)).where(
            StockMove.product_template_id == template_id,
            StockMove.from_location_id == source,
            StockMove.to_location_id == target,
        )
    )
    assert (left, arrived_there, Decimal(ledger or 0)) == (
        Decimal('15'),
        Decimal('5'),
        Decimal('5'),
    ), outcomes
    # One of the two carried its five; the other was told the record had gone.
    assert sum(outcome is None for outcome in outcomes) == 1, outcomes
    assert all(
        outcome is None or isinstance(outcome, ValueError) for outcome in outcomes
    ), outcomes
