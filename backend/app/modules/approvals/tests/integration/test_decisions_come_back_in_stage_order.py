"""Reads of an approval request return its decisions in stage order.

A request opens with one decision row and each approval updates it and writes
the next stage's row, so a reader that takes the table's own order can see the
final stage before the first one -- PostgreSQL writes a row's new version
wherever the page has room. Reads that depended on that order named the first
stage's approver as the one that settled a two-stage request, and the enriched
trace could switch between reads. The relationship orders itself now, and the
relations below are rebuilt with the final stage first, so nothing but that
order can make these assertions pass.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.modules.approvals import services
from app.modules.approvals.models import ApprovalDecision


@pytest.mark.integration
class TestDecisionsComeBackInStageOrder:
    async def test_rows_written_out_of_stage_order_read_back_in_stage_order(
        self,
        real_async_db_session: AsyncSession,
        async_approval_org: Organization,
        async_make_user: Any,
    ) -> None:
        db = real_async_db_session
        requester = await async_make_user(
            email='stage-order-requester@example.com', role='user'
        )
        first_approver = await async_make_user(
            email='stage-order-first@example.com', role='manager'
        )
        final_approver = await async_make_user(
            email='stage-order-final@example.com', role='admin'
        )

        await services.create_workflow(
            db,
            async_approval_org.id,
            'document',
            'Two Stage Order',
            [
                {
                    'order': 1,
                    'role': 'manager',
                    'label': 'First',
                    'approver_user_ids': [str(first_approver.id)],
                },
                {
                    'order': 2,
                    'role': 'admin',
                    'label': 'Final',
                    'approver_user_ids': [str(final_approver.id)],
                },
            ],
            is_active=True,
        )
        request = await services.request_approval(
            db, async_approval_org.id, 'document', uuid.uuid4(), requester.id
        )
        request_id = request.id
        first_approver_id = first_approver.id
        final_approver_id = final_approver.id

        # Write the two decided rows the way the settling UPDATEs can leave
        # them: the final stage first in the table, the first stage after it.
        # The relation is rebuilt so the physical order below is certain, and
        # the physical order is the whole point -- an unordered read would
        # return it.
        await db.execute(text('TRUNCATE approval_decisions'))
        first_decided_at = datetime.now(UTC)
        db.add(
            ApprovalDecision(
                approval_request_id=request_id,
                stage_order=2,
                approver_id=final_approver_id,
                status='APPROVED',
                decided_at=first_decided_at + timedelta(seconds=1),
            )
        )
        await db.flush()
        db.add(
            ApprovalDecision(
                approval_request_id=request_id,
                stage_order=1,
                approver_id=first_approver_id,
                status='APPROVED',
                decided_at=first_decided_at,
            )
        )
        await db.flush()
        await db.commit()
        # The rows the request opened with are gone; the identity map would
        # hand the stale collection back to any read that returns this same
        # instance.
        db.expire(request)

        trace = await services.get_request_enriched(
            db, async_approval_org.id, request_id
        )
        assert trace is not None
        assert [decision['stage_order'] for decision in trace['decisions']] == [1, 2]
        assert [decision['approver_id'] for decision in trace['decisions']] == [
            first_approver_id,
            final_approver_id,
        ]

        listed, total = await services.list_requests_enriched(db, async_approval_org.id)
        assert total == 1
        assert [decision['stage_order'] for decision in listed[0]['decisions']] == [
            1,
            2,
        ]

        plain = await services.get_request(db, async_approval_org.id, request_id)
        assert plain is not None
        assert [decision.stage_order for decision in plain.decisions] == [1, 2]
