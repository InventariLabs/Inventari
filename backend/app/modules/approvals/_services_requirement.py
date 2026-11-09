"""Whether a request not yet raised would park where somebody can decide it.

A request already parked answers this through its enriched form
(``_services_enrichment._solvability_by_request``). The question that matters
earlier is the one asked before the click: confirming a document raises the
request, and the dialog behind the button has to say whether the stage it
will land on has anybody who could decide it — otherwise it promises the
approval queue for a request that will never reach one.

The rule is the same ``cannot_be_decided_reason`` the request side uses, asked
about every stage the request would have to pass and answered with the first
one nobody can decide: stages naming the requester alone are decided on their
behalf the moment the request is raised (``_services_skip``), so they are
walked past here as well.
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
    #: What the first stage nobody can decide is called.
    stage_label: str | None = None


async def first_stage_verdict_async(
    db: AsyncSession, org_id: UUID, target_type: str, requester_id: UUID
) -> FirstStageVerdict | None:
    """The verdict on every stage a new request of this requester would pass.

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
    # Every stage the request would have to pass, not only the first one it
    # waits at: a later stage nobody can decide parks the request just as
    # surely, one approval later. The first such stage is the one named.
    holders: set[UUID] | None = None
    may_decide_own: bool | None = None
    for stage in ordered:
        if [str(u) for u in (stage.get('approver_user_ids') or [])] == [me]:
            continue
        named = named_approvers(stage)
        deciders = await deciders_async(db, org_id, named)
        if not named and holders is None:
            holders = await core_api.roles.holders_of_permission_async(
                db, organization_id=org_id, permission=APPROVE_GRANT
            )
        # Asked only when the answer can matter — the requester is named on
        # this stage, or is the one holder of the grant on an open one.
        if may_decide_own is None and (
            requester_id in named or (not named and holders == {requester_id})
        ):
            may_decide_own = await _may_decide_on_own_request(db, org_id, requester_id)
        reason = cannot_be_decided_reason(
            stage,
            org_has_approver=bool(holders) if not named else True,
            deciders=deciders,
            requester_id=requester_id,
            approver_holders=None if named else holders,
            requester_may_decide_own=bool(may_decide_own),
        )
        if reason is not None:
            return FirstStageVerdict(
                solvable=False,
                undecidable_reason=reason,
                stage_label=stage_label(stage),
            )
    # Every stage can be decided, or is the requester's alone (decided at
    # once, nothing waits).
    return FirstStageVerdict(solvable=True)
