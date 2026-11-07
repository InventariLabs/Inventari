"""Switching a workflow off and raising a request for it cannot interleave.

A request committing between the check for waiting requests and the write of
``is_active = False`` would leave a pending request on an inactive workflow:
nobody could decide it and the target would stay parked. Both paths therefore
queue on the lock named after the organization and target type -- the
requester's side before it picks the active workflow, the administrator's
side before it reads who is waiting -- so whichever comes second sees what the
first committed.

The lock itself is PostgreSQL's; what this pins is the order each side takes it
in, which is the part a refactor can silently move.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User
from app.modules.approvals import _services_request, _services_workflow
from app.modules.approvals.services import (
    create_workflow,
    request_approval,
    update_workflow,
)

pytestmark = pytest.mark.integration


def _record_order(
    monkeypatch: pytest.MonkeyPatch, events: list[str], key_prefix: str
) -> None:
    """Note, in call order, each lock on the target-type key and each read after it."""
    real_lock = _services_workflow.acquire_advisory_lock

    async def lock(db: AsyncSession, key: str) -> None:
        if key.startswith(key_prefix):
            events.append('lock')
        await real_lock(db, key)

    monkeypatch.setattr(_services_workflow, 'acquire_advisory_lock', lock)
    monkeypatch.setattr(_services_request, 'acquire_advisory_lock', lock)

    real_waiting = _services_workflow._requests_waiting_on
    real_active = _services_request.get_active_workflow

    async def waiting(*args: Any, **kwargs: Any) -> Any:
        events.append('read waiting')
        return await real_waiting(*args, **kwargs)

    async def active(*args: Any, **kwargs: Any) -> Any:
        events.append('read active workflow')
        return await real_active(*args, **kwargs)

    monkeypatch.setattr(_services_workflow, '_requests_waiting_on', waiting)
    monkeypatch.setattr(_services_request, 'get_active_workflow', active)


async def test_the_administrator_locks_before_reading_who_waits(
    real_async_db_session: AsyncSession,
    async_approval_org: Organization,
    async_approver: User,
    single_stage_workflow_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, org = real_async_db_session, async_approval_org
    workflow = await create_workflow(
        db,
        org.id,
        single_stage_workflow_payload['target_type'],
        single_stage_workflow_payload['name'],
        single_stage_workflow_payload['stages'],
        is_active=True,
    )
    events: list[str] = []
    _record_order(monkeypatch, events, f'approval_workflow:{org.id}:')

    await update_workflow(
        db, org.id, workflow.id, is_active=False, released_by=async_approver.id
    )

    assert events == ['lock', 'read waiting']


async def test_the_requester_locks_before_choosing_the_workflow(
    real_async_db_session: AsyncSession,
    async_approval_org: Organization,
    async_requester: User,
    single_stage_workflow_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, org = real_async_db_session, async_approval_org
    await create_workflow(
        db,
        org.id,
        single_stage_workflow_payload['target_type'],
        single_stage_workflow_payload['name'],
        single_stage_workflow_payload['stages'],
        is_active=True,
    )
    events: list[str] = []
    _record_order(monkeypatch, events, f'approval_workflow:{org.id}:')

    await request_approval(db, org.id, 'document', uuid.uuid4(), async_requester.id)

    assert events == ['lock', 'read active workflow']
