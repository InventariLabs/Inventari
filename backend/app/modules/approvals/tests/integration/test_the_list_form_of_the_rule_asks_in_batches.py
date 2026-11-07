"""A page of documents is asked about the approval rule in batches.

The list form of the rule is what a filtered To do calls for every row about
to start. It used to ask the sign-off and the active workflow once per
document, so the cost of the screen grew with the page. It now asks the
profile's verdict for all the documents at once and the workflow once, so a
bigger page costs the same queries as a small one.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User
from app.modules.approvals._services_workflow import create_workflow
from app.modules.approvals.document_gate import (
    document_needs_approval_async,
    documents_needing_approval_async,
)
from app.modules.warehouse.models.document import Document

pytestmark = pytest.mark.integration


@pytest.fixture
async def org(real_async_db_session: AsyncSession) -> Organization:
    org = Organization(
        name=f'Batch Org {uuid.uuid4().hex[:8]}',
        enabled_modules=['core', 'warehouse', 'approvals'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    return org


@pytest.fixture
async def confirmer(real_async_db_session: AsyncSession, org: Organization) -> User:
    user = User(
        email=f'batch-{uuid.uuid4().hex[:8]}@test.example',
        hashed_password='x',
        full_name='Batch Confirmer',
        organization_id=org.id,
        role='user',
        is_active=True,
    )
    real_async_db_session.add(user)
    await real_async_db_session.flush()
    return user


async def _documents(
    db: AsyncSession, org: Organization, user: User, count: int
) -> list[Document]:
    documents = [
        Document(
            organization_id=org.id,
            type='IN',
            number=f'IN/{uuid.uuid4().hex[:8]}',
            status='CONFIRMED',
            created_by=user.id,
            confirmed_by=user.id,
            total_net=Decimal('10'),
            currency='PLN',
        )
        for _ in range(count)
    ]
    db.add_all(documents)
    await db.flush()
    return documents


async def _switch_on_a_workflow(db: AsyncSession, org: Organization) -> None:
    stages: list[dict[str, Any]] = [
        {'order': 1, 'role': 'manager', 'label': 'Manager', 'approver_user_ids': []}
    ]
    await create_workflow(db, org.id, 'document', 'Batch Workflow', stages, True)


@pytest.fixture
def statements(real_async_db_session: AsyncSession) -> Iterator[list[str]]:
    seen: list[str] = []
    bind = real_async_db_session.get_bind()

    def count(*args: Any, **_kwargs: Any) -> None:
        seen.append(str(args[2]))

    event.listen(bind, 'before_cursor_execute', count)
    try:
        yield seen
    finally:
        event.remove(bind, 'before_cursor_execute', count)


class TestTheListFormOfTheRuleAsksInBatches:
    async def test_a_bigger_page_costs_the_same_queries(
        self,
        real_async_db_session: AsyncSession,
        org: Organization,
        confirmer: User,
        statements: list[str],
    ) -> None:
        db = real_async_db_session
        await _switch_on_a_workflow(db, org)
        few = await _documents(db, org, confirmer, 2)
        many = await _documents(db, org, confirmer, 12)
        # The first call writes the organization's default profile.
        await documents_needing_approval_async(db, org.id, [(few[0].id, confirmer.id)])

        statements.clear()
        small_answer = await documents_needing_approval_async(
            db, org.id, [(doc.id, confirmer.id) for doc in few]
        )
        small_cost = len(statements)
        statements.clear()
        big_answer = await documents_needing_approval_async(
            db, org.id, [(doc.id, confirmer.id) for doc in many]
        )
        big_cost = len(statements)

        assert small_answer == {doc.id for doc in few}
        assert big_answer == {doc.id for doc in many}
        assert big_cost == small_cost
        assert big_cost <= 10

    async def test_it_agrees_with_the_single_form_on_every_document(
        self,
        real_async_db_session: AsyncSession,
        org: Organization,
        confirmer: User,
    ) -> None:
        db = real_async_db_session
        documents = await _documents(db, org, confirmer, 3)
        pairs = [(doc.id, confirmer.id) for doc in documents]

        # No workflow, a silent profile: nothing is held.
        assert await documents_needing_approval_async(db, org.id, pairs) == set()

        await _switch_on_a_workflow(db, org)
        batch = await documents_needing_approval_async(db, org.id, pairs)
        single = {
            doc.id
            for doc in documents
            if await document_needs_approval_async(
                db, org.id, doc.id, requester_id=confirmer.id
            )
        }
        assert batch == single == {doc.id for doc in documents}
