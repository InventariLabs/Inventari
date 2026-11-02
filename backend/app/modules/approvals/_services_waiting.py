"""Which requests are waiting on a workflow, named the way a reader knows them.

A refusal that says "3 requests are running through it" leaves the reader
hunting for the three; the workflow list that warns about a dead end without
saying that a document is already parked on it leaves them guessing whether
the warning is theory or today's problem. Both want the same thing: the
open requests of a workflow, each with the label of what it is about — the
document number, the order number — which only the module that owns the
target knows, through the summary provider it registered.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import OPEN_STATUSES, ApprovalRequest
from .target_summaries import get_target_summary_provider

#: How many labels a sentence names before it settles for "and others".
NAMED_IN_A_SENTENCE = 3


@dataclass(frozen=True)
class WaitingRequest:
    request_id: UUID
    target_type: str
    target_id: UUID
    #: The number the target module prints on it, or the start of its id.
    label: str


def _label_of(summary: object | None, target_id: UUID) -> str:
    for field in ('number', 'name', 'title'):
        value = getattr(summary, field, None)
        if value:
            return str(value)
    return str(target_id)[:8]


async def waiting_requests_async(
    db: AsyncSession, org_id: UUID, workflow_ids: Sequence[UUID]
) -> dict[UUID, list[WaitingRequest]]:
    """The open requests of each workflow, oldest first, labelled.

    One query for every workflow asked about and one provider call per target
    type, so a list of workflows costs the same as a list of one.
    """
    if not workflow_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(ApprovalRequest)
                .where(
                    ApprovalRequest.organization_id == org_id,
                    ApprovalRequest.workflow_id.in_(list(workflow_ids)),
                    ApprovalRequest.status.in_(OPEN_STATUSES),
                )
                .order_by(ApprovalRequest.created_at, ApprovalRequest.id)
            )
        )
        .scalars()
        .all()
    )

    ids_by_type: dict[str, list[UUID]] = defaultdict(list)
    for row in rows:
        ids_by_type[row.target_type].append(row.target_id)
    summaries: dict[tuple[str, UUID], object] = {}
    for target_type, target_ids in ids_by_type.items():
        provider = get_target_summary_provider(target_type)
        if provider is None:
            continue
        found = await provider(db, org_id, list(dict.fromkeys(target_ids)))
        summaries.update({(target_type, key): value for key, value in found.items()})

    waiting: dict[UUID, list[WaitingRequest]] = defaultdict(list)
    for row in rows:
        waiting[row.workflow_id].append(
            WaitingRequest(
                request_id=row.id,
                target_type=row.target_type,
                target_id=row.target_id,
                label=_label_of(
                    summaries.get((row.target_type, row.target_id)), row.target_id
                ),
            )
        )
    return dict(waiting)


def name_waiting(waiting: Sequence[WaitingRequest]) -> str:
    """The labels for a sentence: the first few, then an ellipsis for the rest."""
    named = ', '.join(item.label for item in waiting[:NAMED_IN_A_SENTENCE])
    return f'{named}, …' if len(waiting) > NAMED_IN_A_SENTENCE else named
