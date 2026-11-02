"""One answer to "can this workflow ever be decided?".

The workflow form promises that a named approver decides, and delegation
makes that true — but a stage is only decidable when at least one of its
named approvers can see approvals at all. A stage whose every named approver
holds neither grant used to save silently and produce requests nobody could
approve, reject, or sometimes even see: the deadlock an administrator built
by picking a colleague from a list that offered everyone in the organization.

The same silence surrounded the other dead end: a stage left open to "anyone
with the grant" in an organization that has granted it to nobody. Both are
refused now, each with its own sentence. ``allow_undecidable`` is the way
past — an administrator who has read what it costs and means it can save the
stage, and the request it produces says on every screen that nobody can
decide it (``_services_solvability``).
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ._services_solvability import (
    NAMED_APPROVERS_CANNOT_DECIDE,
    NO_APPROVER_IN_ORGANIZATION,
    cannot_be_decided_reason,
    deciders_async,
    named_approvers,
    org_has_approver_async,
    stage_label,
)
from .exceptions import ApprovalStageUnsolvableError

#: What each dead end is called when it is refused. Two sentences, because
#: the fix is different: name somebody, or grant somebody the right.
_REFUSALS = {
    NO_APPROVER_IN_ORGANIZATION: 'approval_stage_open_unsolvable',
    NAMED_APPROVERS_CANNOT_DECIDE: 'approval_stage_unsolvable',
}


async def validate_workflow_decidable(
    db: AsyncSession,
    org_id: UUID,
    stages: list[dict[str, Any]] | None,
    *,
    allow_undecidable: bool = False,
) -> None:
    """Refuse a stage nobody could decide, unless that was accepted.

    An open stage (no named list) is decidable by anyone holding the approve
    grant, so the organization's answer to "does anybody hold it?" decides
    whether the stage is a dead end. A named stage is decidable when at least
    one of the named people can decide — delegation's read floor included.
    The refusal names the stage, so the reader knows which one to fix.
    """
    if allow_undecidable:
        return
    stages = list(stages or [])
    if not stages:
        return

    every_named: list[UUID] = [
        user_id for stage in stages for user_id in named_approvers(stage)
    ]
    deciders = await deciders_async(db, org_id, every_named)
    has_open_stage = any(not named_approvers(stage) for stage in stages)
    org_has_approver = (
        await org_has_approver_async(db, org_id) if has_open_stage else True
    )

    for stage in stages:
        reason = cannot_be_decided_reason(
            stage, org_has_approver=org_has_approver, deciders=deciders
        )
        if reason is not None:
            raise ApprovalStageUnsolvableError.translated(
                _REFUSALS[reason], label=stage_label(stage)
            )
