"""Whether a request not yet raised would park where somebody can decide it.

A request already parked answers this through its enriched form
(``_services_enrichment._solvability_by_request``). The question that matters
earlier is the one asked before the click: confirming a document raises the
request, and the dialog behind the button has to say whether the stage it
will land on has anybody who could decide it — otherwise it promises the
approval queue for a request that will never reach one.

The rule is the same ``cannot_be_decided_reason`` the request side uses, asked
about the first stage the requester would actually wait at: stages naming the
requester alone are decided on their behalf the moment the request is raised
(``_services_skip``), so they are walked past here as well.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

from ._services_decisions import _may_decide_on_own_request
from ._services_requesters import requester_in_scope_async
from ._services_solvability import (
    APPROVE_GRANT,
    cannot_be_decided_reason,
    deciders_async,
    named_approvers,
    stage_label,
)
from ._services_workflow import get_active_workflow


@dataclass(frozen=True)
class FirstStageVerdict:
    solvable: bool
    #: The stable code from ``_services_solvability`` when it is not.
    undecidable_reason: str | None = None
    #: What the stage is called, when there is a stage to blame.
    stage_label: str | None = None


async def first_stage_verdict_async(
    db: AsyncSession, org_id: UUID, target_type: str, requester_id: UUID
) -> FirstStageVerdict | None:
    """The verdict on the stage a new request of this requester would wait at.

    ``None`` when no active workflow with stages exists for the target type,
    or when the workflow does not hold this requester — there is no request
    to judge, and the caller has its own sentence for that.
    """
    workflow = await get_active_workflow(db, org_id, target_type)
    if workflow is None or not workflow.stages:
        return None
    if not await requester_in_scope_async(db, org_id, workflow, requester_id):
        return None

    ordered = sorted(workflow.stages, key=lambda s: s.get('order', 0))
    me = str(requester_id)
    stage = next(
        (
            s
            for s in ordered
            if [str(u) for u in (s.get('approver_user_ids') or [])] != [me]
        ),
        None,
    )
    if stage is None:
        # Every stage is the requester's alone: decided at once, nothing waits.
        return FirstStageVerdict(solvable=True)

    named = named_approvers(stage)
    deciders = await deciders_async(db, org_id, named)
    holders: set[UUID] | None = None
    if not named:
        holders = await core_api.roles.holders_of_permission_async(
            db, organization_id=org_id, permission=APPROVE_GRANT
        )
    may_decide_own = False
    if holders and holders == {requester_id}:
        may_decide_own = await _may_decide_on_own_request(db, org_id, requester_id)

    reason = cannot_be_decided_reason(
        stage,
        org_has_approver=bool(holders) if holders is not None else True,
        deciders=deciders,
        requester_id=requester_id,
        approver_holders=holders,
        requester_may_decide_own=may_decide_own,
    )
    return FirstStageVerdict(
        solvable=reason is None,
        undecidable_reason=reason,
        stage_label=stage_label(stage),
    )
