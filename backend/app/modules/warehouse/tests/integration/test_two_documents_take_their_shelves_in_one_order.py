"""Two dispatches of the same products, lines in opposite order, both complete.

Completing a document locked its own row and then walked the lines in
order, each line locking the stock it took when it got to it. Nothing
ordered two documents against each other before their first line: one
dispatching rice then flour, the other flour then rice, took one product
each and then waited for the other's — and the database broke the circle by
aborting one completion, which the person saw as an error on a document
nothing was wrong with.

Confirming the two did the same, one reservation per line.

A document now locks the stock of every product it names before its first
line, in the order every multi-group operation shares, so the second
document waits for the first instead of meeting it halfway.

Each document is held after its first line until the other has finished its
first line too, or for two seconds: the interleaving that closed the circle.
With the stock locked up front the second one never gets there — it is
waiting for the first to finish, which is what the two seconds are for.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.testing import ModuleTestHelper, ShelfRow
from app.models.item import Item
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse import _document_workflow_crud, document_stock_executor
from app.modules.warehouse._document_workflow_transitions import (
    complete_document,
    confirm_document,
)
from app.modules.warehouse.document_profile_service import get_or_create_profile
from app.modules.warehouse.models import Document, DocumentLine, DocumentStatus
from tests.integration._shelf import put_on_shelf

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: Which of the two completions the running task is.
_WHO: contextvars.ContextVar[str] = contextvars.ContextVar('who')


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


class _Shelf:
    """One shelf holding ten of each of two products, a record of each."""

    org_id: uuid.UUID
    user_id: uuid.UUID
    shelf_id: uuid.UUID
    records: dict[str, tuple[uuid.UUID, uuid.UUID]]


async def _shelf_with_two_products(db: AsyncSession) -> _Shelf:
    shelf = _Shelf()
    org = Organization(
        name=f'One order {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'warehouse'],
    )
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'order_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    location = StorageLocation(
        organization_id=org.id, created_by=user.id, name='Dry store'
    )
    db.add(location)
    await db.flush()
    shelf.records = {}
    for name in ('Rice', 'Flour'):
        template = ProductTemplate(
            organization_id=org.id, name=name, sku=f'{name}-{uuid.uuid4().hex[:8]}'
        )
        db.add(template)
        await db.flush()
        record = await put_on_shelf(
            db,
            user,
            template,
            location.id,
            Decimal('10'),
            purchase_price=Decimal('2'),
        )
        shelf.records[name] = (template.id, record.id)
    # Completion reads the profile; made here so that the two completions
    # below do not race on creating it instead.
    await get_or_create_profile(db, org.id)
    await db.commit()
    shelf.org_id, shelf.user_id, shelf.shelf_id = org.id, user.id, location.id
    return shelf


async def _dispatch(
    db: AsyncSession, shelf: _Shelf, names: list[str], status: DocumentStatus
) -> uuid.UUID:
    doc = Document(
        organization_id=shelf.org_id,
        type='OUT',
        number=f'OUT/T/{uuid.uuid4().hex[:6]}',
        status=status.value,
        source_location_id=shelf.shelf_id,
        created_by=shelf.user_id,
    )
    db.add(doc)
    await db.flush()
    for number, name in enumerate(names, start=1):
        template_id, record_id = shelf.records[name]
        db.add(
            DocumentLine(
                document_id=doc.id,
                line_number=number,
                name=name,
                product_template_id=template_id,
                item_id=record_id,
                quantity=Decimal('1'),
                expected_quantity=Decimal('1'),
                # Done only once it is confirmed: a draft still expects all
                # of it, which is what confirmation reserves.
                done_quantity=Decimal('0' if status is DocumentStatus.DRAFT else '1'),
            )
        )
    await db.commit()
    return doc.id


class _Door:
    """One way through a document that takes its lines one by one."""

    def __init__(
        self,
        name: str,
        starts_as: DocumentStatus,
        ends_as: DocumentStatus,
        module: ModuleType,
        step: str,
        walk: Callable[[AsyncSession, _Shelf, uuid.UUID], Awaitable[None]],
        left: tuple[Decimal, Decimal, Decimal],
    ) -> None:
        self.name = name
        self.starts_as = starts_as
        self.ends_as = ends_as
        self.module = module
        self.step = step
        self.walk = walk
        #: What stays on each shelf and on each record, and is held back.
        self.left = left


async def _complete(session: AsyncSession, shelf: _Shelf, doc_id: uuid.UUID) -> None:
    await complete_document(session, shelf.org_id, doc_id, shelf.user_id)


async def _confirm(session: AsyncSession, shelf: _Shelf, doc_id: uuid.UUID) -> None:
    await confirm_document(session, shelf.org_id, doc_id, shelf.user_id)


_DOORS = [
    _Door(
        'complete',
        DocumentStatus.CONFIRMED,
        DocumentStatus.COMPLETED,
        document_stock_executor,
        '_dispatch_item',
        _complete,
        (Decimal('8'), Decimal('8'), Decimal('0')),
    ),
    _Door(
        'confirm',
        DocumentStatus.DRAFT,
        DocumentStatus.CONFIRMED,
        _document_workflow_crud,
        'reserve_for_document_async',
        _confirm,
        (Decimal('10'), Decimal('10'), Decimal('2')),
    ),
]


@pytest.mark.parametrize('door', _DOORS, ids=[door.name for door in _DOORS])
async def test_two_documents_in_opposite_order_both_go_through(
    real_async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    door: _Door,
) -> None:
    db = real_async_db_session
    shelf = await _shelf_with_two_products(db)
    first = await _dispatch(db, shelf, ['Rice', 'Flour'], door.starts_as)
    second = await _dispatch(db, shelf, ['Flour', 'Rice'], door.starts_as)

    arrived = {'first': asyncio.Event(), 'second': asyncio.Event()}
    step = getattr(door.module, door.step)

    async def step_then_wait_for_the_other(*args: Any, **kwargs: Any) -> Any:
        result = await step(*args, **kwargs)
        me = _WHO.get(None)
        if me is None or arrived[me].is_set():
            return result
        arrived[me].set()
        other = 'second' if me == 'first' else 'first'
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(arrived[other].wait(), timeout=2)
        return result

    monkeypatch.setattr(door.module, door.step, step_then_wait_for_the_other)

    engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def go_through(name: str, doc_id: uuid.UUID) -> None:
        _WHO.set(name)
        async with factory() as session:
            await door.walk(session, shelf, doc_id)
            # What the request-scoped session does when the door returns.
            await session.commit()

    try:
        outcomes = await asyncio.gather(
            go_through('first', first),
            go_through('second', second),
            return_exceptions=True,
        )
    finally:
        await engine.dispose()

    assert outcomes == [None, None], outcomes
    statuses = (
        await db.scalars(
            select(Document.status)
            .where(Document.id.in_([first, second]))
            .execution_options(populate_existing=True)
        )
    ).all()
    assert statuses == [door.ends_as.value] * 2
    for template_id, record_id in shelf.records.values():
        quant = await db.scalar(
            select(ShelfRow).where(ShelfRow.product_template_id == template_id)
        )
        held = await db.scalar(
            select(Item.quantity)
            .where(Item.id == record_id)
            .execution_options(populate_existing=True)
        )
        assert quant is not None
        assert (quant.quantity, held, quant.reserved_quantity) == door.left
