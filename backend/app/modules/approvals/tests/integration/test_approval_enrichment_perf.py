"""Performance regression tests for approval enrichment.

Regression for the N+1 query hell in ``list_requests_enriched``:
previously the function issued 1 list query + 1 user lookup per
request + 1 workflow lookup per request + 1 user lookup per decision
resulting in O(N) queries and O(4s) latency for 100 requests.

After the batch-load refactor, the same call must use a bounded number
of queries regardless of result size.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User
from app.modules.approvals._services_enrichment import list_requests_enriched
from app.modules.approvals._services_workflow import create_workflow
from app.modules.approvals.models import ApprovalDecision, ApprovalRequest

# ---------------------------------------------------------------------------
# Query counter: register a before_cursor_execute listener that increments
# a counter for every statement the session issues.
# ---------------------------------------------------------------------------


class _QueryCounter:
    def __init__(self) -> None:
        self.count = 0

    def reset(self) -> None:
        self.count = 0


@pytest.fixture
def query_counter() -> _QueryCounter:
    return _QueryCounter()


@pytest.fixture
def track_queries(
    real_async_db_session: AsyncSession, query_counter: _QueryCounter
) -> Iterator[None]:
    """Registers a SQLAlchemy ``before_cursor_execute`` listener on the
    bind engine so every statement the session issues increments the
    counter. Listener is removed on teardown.
    """
    bind = real_async_db_session.get_bind()

    def before_cursor_execute(*_args: Any, **_kwargs: Any) -> None:
        query_counter.count += 1

    event.listen(bind, 'before_cursor_execute', before_cursor_execute)
    try:
        yield
    finally:
        event.remove(bind, 'before_cursor_execute', before_cursor_execute)


# ---------------------------------------------------------------------------
# Fixtures: build an org + workflow + N requests with decisions.
# ---------------------------------------------------------------------------


@pytest.fixture
async def perf_org(real_async_db_session: AsyncSession) -> Organization:
    suffix = uuid.uuid4().hex[:8]
    org = Organization(
        name=f'Perf Org {suffix}',
        enabled_modules=['core', 'approvals'],
    )
    real_async_db_session.add(org)
    await real_async_db_session.flush()
    await real_async_db_session.refresh(org)
    return org


@pytest.fixture
async def perf_users(
    real_async_db_session: AsyncSession, perf_org: Organization
) -> list[User]:
    """Three users: one creator, two approvers."""
    users: list[User] = []
    for i in range(3):
        suffix = uuid.uuid4().hex[:8]
        user = User(
            email=f'perf-{i}-{suffix}@test.example',
            hashed_password='x',
            full_name=f'Perf User {i}',
            organization_id=perf_org.id,
            role='user',
            is_active=True,
        )
        real_async_db_session.add(user)
        users.append(user)
    await real_async_db_session.flush()
    for u in users:
        await real_async_db_session.refresh(u)
    return users


@pytest.fixture
async def perf_workflow(
    real_async_db_session: AsyncSession, perf_org: Organization
) -> Any:
    stages = [
        {'order': 1, 'role': 'manager', 'label': 'Manager', 'approver_user_ids': []},
    ]
    workflow = await create_workflow(
        real_async_db_session,
        perf_org.id,
        'document',
        'Perf Workflow',
        stages,
        True,
    )
    return workflow


@pytest.fixture
async def perf_requests(
    real_async_db_session: AsyncSession,
    perf_org: Organization,
    perf_users: list[User],
    perf_workflow: Any,
) -> list[ApprovalRequest]:
    """Build 20 requests, each with 3 decisions (60 decisions total)."""
    requests: list[ApprovalRequest] = []
    creator, approver1, approver2 = perf_users

    for _ in range(20):
        req = ApprovalRequest(
            organization_id=perf_org.id,
            workflow_id=perf_workflow.id,
            target_type='document',
            target_id=uuid.uuid4(),
            status='PENDING',
            current_stage=1,
            total_stages=1,
            created_by=creator.id,
        )
        real_async_db_session.add(req)
        await real_async_db_session.flush()
        for approver in (approver1, approver2, creator):
            dec = ApprovalDecision(
                approval_request_id=req.id,
                stage_order=1,
                approver_id=approver.id,
                status='PENDING',
            )
            real_async_db_session.add(dec)
        requests.append(req)

    await real_async_db_session.commit()
    return requests


# ---------------------------------------------------------------------------
# Regression test: query count is bounded.
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_requests_enriched_uses_bounded_queries(
    real_async_db_session: AsyncSession,
    perf_org: Organization,
    perf_requests: list[ApprovalRequest],
    query_counter: _QueryCounter,
    track_queries: None,
) -> None:
    """list_requests_enriched must NOT issue per-request queries.

    With 20 requests and 60 decisions, the previous N+1 implementation
    issued ~141 queries (1 + 20 user + 20 workflow + 60 decision-user).
    The batch-load implementation issues a bounded number (~5: list +
    selectinload decision + workflows batch + users batch + commit).
    """
    query_counter.reset()

    enriched, total = await list_requests_enriched(real_async_db_session, perf_org.id)

    assert total == 20
    assert len(enriched) == 20
    assert query_counter.count < 20, (
        f'Expected < 20 queries, got {query_counter.count}. N+1 regression detected.'
    )


@pytest.mark.integration
async def test_list_requests_enriched_returns_names(
    real_async_db_session: AsyncSession,
    perf_org: Organization,
    perf_requests: list[ApprovalRequest],
) -> None:
    """Sanity: the batch-loaded enrichment returns the same data shape
    as before, including user names for creators and approvers."""
    enriched, _ = await list_requests_enriched(real_async_db_session, perf_org.id)
    assert len(enriched) == 20
    for item in enriched:
        assert item['created_by_name'] == 'Perf User 0'
        assert len(item['decisions']) == 3
        for dec in item['decisions']:
            assert dec['approver_name'] is not None
        assert item['workflow_stages'] is not None
        assert item['workflow_stages'][0]['label'] == 'Manager'
