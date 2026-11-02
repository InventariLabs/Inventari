"""One document, several hands on it at the same moment.

Confirm and cancel read the document without taking its row, so the status
they decided on could already be gone: a cancel that read CONFIRMED could
stamp CANCELLED over a completion that had just issued the stock — or wait,
holding the anchors, for the completion's locks, the two doors meeting in
opposite orders until the database killed one with a deadlock; two confirms
could both reserve what one document takes; a cancel that read DRAFT could
close a document a confirm had just promised stock to, and the promise
stayed on the shelf with nobody left to release it.

Every door now takes the document's row first — the row completion already
locks, in the same order — and decides only under that lock. These tests
stage the meetings the old code lost: one door is held at its step until
the other has got where the collision happens, the way
``test_two_documents_take_their_shelves_in_one_order`` holds its two
documents, and what is asserted is the shelf and the document afterwards,
not which door returned what.
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
from app.core.contracts._system_dtos import AuditAction
from app.core.testing import ModuleTestHelper, ShelfRow
from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.stock_reservation import StockReservation
from app.models.storage_location import StorageLocation
from app.modules.warehouse import _document_workflow_transitions as transitions
from app.modules.warehouse.document_profile_service import get_or_create_profile
from app.modules.warehouse.models import Document, DocumentLine, DocumentStatus
from tests.integration._shelf import put_on_shelf

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: Which of the two concurrent doors the running task is.
_WHO: contextvars.ContextVar[str] = contextvars.ContextVar('who')

#: The shelf holds ten; a line through the door takes one.
_ON_SHELF = Decimal('10')
_TAKEN = Decimal('1')


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


class _Shelf:
    """One shelf holding ten of one product, a record of it."""

    org_id: uuid.UUID
    user_id: uuid.UUID
    shelf_id: uuid.UUID
    template_id: uuid.UUID
    record_id: uuid.UUID


async def _shelf_with_one_product(db: AsyncSession) -> _Shelf:
    shelf = _Shelf()
    org = Organization(
        name=f'One row {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'warehouse'],
    )
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'row_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    location = StorageLocation(
        organization_id=org.id, created_by=user.id, name='Dry store'
    )
    db.add(location)
    await db.flush()
    template = ProductTemplate(
        organization_id=org.id, name='Rice', sku=f'Rice-{uuid.uuid4().hex[:8]}'
    )
    db.add(template)
    await db.flush()
    record = await put_on_shelf(
        db,
        user,
        template,
        location.id,
        _ON_SHELF,
        purchase_price=Decimal('2'),
    )
    # The doors read the profile; made here so the concurrent tasks below
    # do not race on creating it instead.
    await get_or_create_profile(db, org.id)
    await db.commit()
    shelf.org_id = org.id
    shelf.user_id = user.id
    shelf.shelf_id = location.id
    shelf.template_id = template.id
    shelf.record_id = record.id
    return shelf


async def _dispatch(
    db: AsyncSession, shelf: _Shelf, status: DocumentStatus
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
    db.add(
        DocumentLine(
            document_id=doc.id,
            line_number=1,
            name='Rice',
            product_template_id=shelf.template_id,
            item_id=shelf.record_id,
            quantity=_TAKEN,
            expected_quantity=_TAKEN,
            # Done only once it is confirmed: a draft still expects all of
            # it, which is what confirmation reserves.
            done_quantity=Decimal('0' if status is DocumentStatus.DRAFT else '1'),
        )
    )
    await db.commit()
    return doc.id


async def _run_two(first: Any, second: Any) -> tuple[Any, ...]:
    """Run two doors at once, each on a connection of its own."""
    engine = create_async_engine(_async_test_url(), echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def on_its_own_connection(work: Any) -> Any:
        async with factory() as session:
            outcome = await work(session)
            # What the request-scoped session does when the door returns.
            await session.commit()
            return outcome

    try:
        return tuple(
            await asyncio.gather(
                on_its_own_connection(first),
                on_its_own_connection(second),
                return_exceptions=True,
            )
        )
    finally:
        await engine.dispose()


def _assert_nothing_but_a_refusal(outcomes: tuple[Any, ...]) -> None:
    """The only error a door may hand back is its own no.

    A door that went through returns quietly (a document, or nothing); a
    door that was told no raises ``ValueError``. A deadlock, a
    serialization abort or anything else the database said means the doors
    met in the wrong order.
    """
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            assert isinstance(outcome, ValueError), outcomes


async def _document_status(db: AsyncSession, doc_id: uuid.UUID) -> str:
    status = await db.scalar(
        select(Document.status)
        .where(Document.id == doc_id)
        .execution_options(populate_existing=True)
    )
    assert status is not None
    return status


async def _quant(db: AsyncSession, shelf: _Shelf) -> ShelfRow:
    """The shelf's one group, as its records and reservation rows say now."""
    group = await db.scalar(
        select(ShelfRow).where(ShelfRow.product_template_id == shelf.template_id)
    )
    assert group is not None, 'the records of the shelf are gone'
    return group


async def _reservation_count(db: AsyncSession, doc_id: uuid.UUID) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(StockReservation)
        .where(StockReservation.document_id == doc_id)
    )
    assert count is not None
    return count


@pytest.mark.parametrize('order', ['cancel_reads_first', 'complete_locks_first'])
async def test_cancel_and_complete_at_once_never_cancel_issued_stock(
    real_async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    order: str,
) -> None:
    db = real_async_db_session
    shelf = await _shelf_with_one_product(db)
    doc_id = await _dispatch(db, shelf, DocumentStatus.CONFIRMED)

    cancel_read = asyncio.Event()
    doc_locked = asyncio.Event()

    real_get_or_raise = transitions.get_or_raise
    real_for_update = transitions._get_doc_for_update
    real_wms_check = transitions._check_no_active_wms_sessions

    async def get_or_raise_marking_the_read(
        db: AsyncSession, org_id: uuid.UUID, doc_id_: uuid.UUID
    ) -> Any:
        doc = await real_get_or_raise(db, org_id, doc_id_)
        if _WHO.get(None) == 'cancel':
            cancel_read.set()
        return doc

    async def for_update_marking_the_lock(
        db: AsyncSession, org_id: uuid.UUID, doc_id_: uuid.UUID
    ) -> Any:
        doc = await real_for_update(db, org_id, doc_id_)
        if _WHO.get(None) == 'complete':
            doc_locked.set()
        return doc

    async def wms_check_letting_the_cancel_read_first(
        db: AsyncSession, org_id: uuid.UUID, doc_id_: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        await real_wms_check(db, org_id, doc_id_, user_id)
        if _WHO.get(None) == 'complete':
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(cancel_read.wait(), timeout=2)

    async def read_then_wait_for_the_lock(
        db: AsyncSession, org_id: uuid.UUID, doc_id_: uuid.UUID
    ) -> Any:
        doc = await real_get_or_raise(db, org_id, doc_id_)
        if _WHO.get(None) == 'cancel':
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(doc_locked.wait(), timeout=2)
        return doc

    # 'cancel_reads_first' stages the quiet theft: the cancel reads
    # CONFIRMED and stands down its guard before the completion has even
    # locked the row. 'complete_locks_first' stages the deadlock: the
    # completion holds the row while the cancel picks up the anchors, and
    # each waits for what the other holds.
    monkeypatch.setattr(transitions, 'get_or_raise', get_or_raise_marking_the_read)
    monkeypatch.setattr(transitions, '_get_doc_for_update', for_update_marking_the_lock)
    monkeypatch.setattr(
        transitions,
        '_check_no_active_wms_sessions',
        wms_check_letting_the_cancel_read_first,
    )
    if order == 'complete_locks_first':
        monkeypatch.setattr(transitions, 'get_or_raise', read_then_wait_for_the_lock)

    async def go_cancel(session: AsyncSession) -> None:
        _WHO.set('cancel')
        await transitions.cancel_document(session, shelf.org_id, doc_id, shelf.user_id)

    async def go_complete(session: AsyncSession) -> None:
        _WHO.set('complete')
        await transitions.complete_document(
            session, shelf.org_id, doc_id, shelf.user_id
        )

    outcomes = await _run_two(go_cancel, go_complete)

    _assert_nothing_but_a_refusal(outcomes)
    status = await _document_status(db, doc_id)
    quant = await _quant(db, shelf)
    issued = quant.quantity == _ON_SHELF - _TAKEN
    assert status in (
        DocumentStatus.COMPLETED.value,
        DocumentStatus.CANCELLED.value,
    ), status
    assert not (status == DocumentStatus.CANCELLED.value and issued), (
        f'a cancelled document stands where {quant.quantity} was issued'
    )


async def test_two_confirms_at_once_reserve_once(
    real_async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = real_async_db_session
    shelf = await _shelf_with_one_product(db)
    doc_id = await _dispatch(db, shelf, DocumentStatus.DRAFT)

    arrived = {'first': asyncio.Event(), 'second': asyncio.Event()}
    real_reserve = transitions._reserve_quants_for_doc

    async def reserve_then_wait_for_the_other(db: AsyncSession, doc: Document) -> None:
        await real_reserve(db, doc)
        me = _WHO.get(None)
        if me is None or arrived[me].is_set():
            return
        arrived[me].set()
        other = 'second' if me == 'first' else 'first'
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(arrived[other].wait(), timeout=2)

    monkeypatch.setattr(
        transitions, '_reserve_quants_for_doc', reserve_then_wait_for_the_other
    )

    async def go_confirm(session: AsyncSession, name: str) -> Any:
        _WHO.set(name)
        return await transitions.confirm_document(
            session, shelf.org_id, doc_id, shelf.user_id
        )

    async def first(session: AsyncSession) -> Any:
        return await go_confirm(session, 'first')

    async def second(session: AsyncSession) -> Any:
        return await go_confirm(session, 'second')

    outcomes = await _run_two(first, second)

    # Both hands come away settled: one confirmed, the other either told so
    # or refused — nobody left mid-air.
    _assert_nothing_but_a_refusal(outcomes)
    status = await _document_status(db, doc_id)
    assert status == DocumentStatus.CONFIRMED.value, status
    reservations = await _reservation_count(db, doc_id)
    assert reservations == 1, f'{reservations} reservations for one confirmation'
    # The outbox row is a production artefact — in TESTING the confirmed
    # event is buffered and dispatched inline, so the persistent witness
    # of the confirmation is its audit entry, which the second (idempotent)
    # confirm never writes.
    confirmed_audits = await db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.target_type == 'document',
            AuditLog.target_id == doc_id,
            AuditLog.action == AuditAction.UPDATE.value,
            AuditLog.snapshot['new_status'].as_string()
            == DocumentStatus.CONFIRMED.value,
        )
    )
    assert confirmed_audits == 1, f'{confirmed_audits} confirmed events'
    quant = await _quant(db, shelf)
    assert quant.reserved_quantity == _TAKEN, quant.reserved_quantity


async def test_confirm_and_cancel_on_a_draft_leave_no_reservation_behind(
    real_async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = real_async_db_session
    shelf = await _shelf_with_one_product(db)
    doc_id = await _dispatch(db, shelf, DocumentStatus.DRAFT)

    confirm_done = asyncio.Event()
    real_notify_withdrawn = transitions.notify_withdrawn_async

    async def notify_withdrawn_then_wait_for_the_confirm(
        db: AsyncSession,
        org_id: uuid.UUID,
        doc_id: uuid.UUID,
        user_id: uuid.UUID | None,
    ) -> None:
        if _WHO.get(None) == 'cancel':
            # Hold the cancel here — past its read, past the point where a
            # DRAFT skips releasing — until the confirm has reserved and
            # committed.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(confirm_done.wait(), timeout=2)
        await real_notify_withdrawn(db, org_id, doc_id, user_id)

    monkeypatch.setattr(
        transitions,
        'notify_withdrawn_async',
        notify_withdrawn_then_wait_for_the_confirm,
    )

    async def go_confirm(session: AsyncSession) -> Any:
        _WHO.set('confirm')
        result = await transitions.confirm_document(
            session, shelf.org_id, doc_id, shelf.user_id
        )
        confirm_done.set()
        return result

    async def go_cancel(session: AsyncSession) -> None:
        _WHO.set('cancel')
        await transitions.cancel_document(session, shelf.org_id, doc_id, shelf.user_id)

    outcomes = await _run_two(go_confirm, go_cancel)

    _assert_nothing_but_a_refusal(outcomes)
    status = await _document_status(db, doc_id)
    assert status == DocumentStatus.CANCELLED.value, status
    reservations = await _reservation_count(db, doc_id)
    assert reservations == 0, (
        f'{reservations} reservations left on a cancelled document'
    )
    quant = await _quant(db, shelf)
    assert quant.reserved_quantity == 0, quant.reserved_quantity
