"""A document's number is claimed late and in the document's own transaction.

The counter row is locked from the claim to the commit, and every document of
one prefix waits for that long. Two things follow, and each has a test:

- what a document does *before* it asks for its number must not be waited
  for by the others, so the number is drawn once confirmation has done its
  work rather than in front of it;
- the claim must not need a second connection while the document holds its
  first. A claim in a session of its own did, and a burst of documents larger
  than the pool all held one connection each and waited for another: the
  pool timed out and the requests failed. The pool here is bounded, which an
  unbounded one (``NullPool``) cannot show.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.testing import ModuleTestHelper
from app.models.organization import Organization
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.modules.warehouse import _document_workflow_transitions as transitions
from app.modules.warehouse._document_workflow_crud import create_document
from app.modules.warehouse._document_workflow_transitions import confirm_document
from app.modules.warehouse.document_profile_service import get_or_create_profile
from app.modules.warehouse.models import Document
from app.modules.warehouse.schemas import DocumentCreate, DocumentLineCreate

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: How long the work a document does before it asks for its number is made
#: to take: the stand-in for everything confirmation reads and checks ahead
#: of the claim.
SLOW_WORK_SECONDS = 0.4


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


async def _receiving_dock(
    db: AsyncSession,
) -> tuple[uuid.UUID, uuid.UUID, DocumentCreate]:
    org = Organization(
        name=f'Numbering {uuid.uuid4().hex[:6]}',
        enabled_modules=['core', 'items', 'locations', 'warehouse'],
    )
    db.add(org)
    await db.flush()
    user = await ModuleTestHelper.create_user_async(
        db, org, email=f'num_{uuid.uuid4().hex[:8]}@test.com', role='admin'
    )
    shelf = StorageLocation(organization_id=org.id, created_by=user.id, name='Dock')
    template = ProductTemplate(
        organization_id=org.id,
        name=f'Rice {uuid.uuid4().hex[:6]}',
        sku=f'RICE-{uuid.uuid4().hex[:8]}',
    )
    db.add_all([shelf, template])
    await db.flush()
    # Made here so the callers do not race on creating it instead.
    await get_or_create_profile(db, org.id)
    await db.commit()
    data = DocumentCreate(
        type='IN',
        target_location_id=shelf.id,
        lines=[
            DocumentLineCreate(product_template_id=template.id, expected_quantity=1)
        ],
    )
    return org.id, user.id, data


async def _issue_all(engine: Any, workers: int, ctx: tuple[Any, Any, Any]) -> list[Any]:
    org_id, user_id, data = ctx
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def issue() -> str:
        async with factory() as session:
            doc = await create_document(session, org_id, data.model_copy(), user_id)
            number = str(doc.number)
            # What the request-scoped session does when the door returns.
            await session.commit()
            return number

    try:
        return await asyncio.gather(
            *(issue() for _ in range(workers)), return_exceptions=True
        )
    finally:
        await engine.dispose()


async def _confirm_all(
    engine: Any, org_id: uuid.UUID, user_id: uuid.UUID, drafts: list[Document]
) -> list[Any]:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def confirm_one(doc: Document) -> Document:
        async with factory() as session:
            confirmed = await confirm_document(session, org_id, doc.id, user_id)
            # What the request-scoped session does when the door returns.
            await session.commit()
            return confirmed

    try:
        return await asyncio.gather(
            *(confirm_one(doc) for doc in drafts), return_exceptions=True
        )
    finally:
        await engine.dispose()


async def test_a_burst_larger_than_the_pool_gets_distinct_numbers(
    real_async_db_session: AsyncSession,
) -> None:
    ctx = await _receiving_dock(real_async_db_session)
    workers = 30
    engine = create_async_engine(
        _async_test_url(),
        pool_size=4,
        max_overflow=0,
        pool_timeout=10,
    )

    outcomes = await _issue_all(engine, workers, ctx)

    assert all(isinstance(o, str) for o in outcomes), outcomes
    assert len(set(outcomes)) == workers, outcomes


async def test_documents_do_not_queue_behind_work_done_before_the_number(
    real_async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id, user_id, data = await _receiving_dock(real_async_db_session)
    workers = 6
    # The drafts are written first: creation is not what is under test here,
    # and a draft costs the register no number until confirmation draws one.
    drafts = [
        await create_document(real_async_db_session, org_id, data.model_copy(), user_id)
        for _ in range(workers)
    ]
    await real_async_db_session.commit()

    guard = transitions._require_products_on_receipt_lines
    draw = transitions.generate_number
    #: What each document did, in order, keyed by the session it did it on.
    done: dict[AsyncSession, list[str]] = {}
    #: Start and end of each document's slow work, for the overlap below.
    phases: list[tuple[float, float]] = []

    async def slow_work(db: AsyncSession, *args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        await asyncio.sleep(SLOW_WORK_SECONDS)
        result = await guard(db, *args, **kwargs)
        phases.append((started, time.monotonic()))
        done.setdefault(db, []).append('work')
        return result

    async def noted_number(db: AsyncSession, *args: Any, **kwargs: Any) -> Any:
        done.setdefault(db, []).append('number')
        return await draw(db, *args, **kwargs)

    monkeypatch.setattr(transitions, '_require_products_on_receipt_lines', slow_work)
    monkeypatch.setattr(transitions, 'generate_number', noted_number)

    engine = create_async_engine(_async_test_url(), poolclass=NullPool)
    outcomes = await _confirm_all(engine, org_id, user_id, drafts)

    assert all(isinstance(o, Document) for o in outcomes), outcomes
    # Six claims of one counter, made concurrently, still hand out six
    # different numbers — the row serialises them, it does not repeat them.
    numbers = {o.number for o in outcomes}
    assert len(numbers) == workers, numbers
    # Every document did its work first and asked for its number afterwards:
    # the number is the last thing confirmation draws, and a claim standing
    # in front of the work would show the two the other way round.
    assert len(done) == workers, done
    assert all(steps == ['work', 'number'] for steps in done.values()), done
    # The work ran side by side as well: two documents were doing it at the
    # same time, so none waited for another's work to end before beginning
    # its own — a queue would leave one document in flight at a time.
    in_flight = max(sum(start <= at < end for start, end in phases) for at, _ in phases)
    assert in_flight >= 2, phases
