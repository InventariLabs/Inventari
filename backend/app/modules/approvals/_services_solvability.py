"""One answer to "can this stage ever be decided?".

The workflow form lets an administrator name approvers, leave a stage open to
"anyone with the grant", and pick a role label that carries no authority at
all (see ``roleLabels.ts`` — ``role`` is a free-form label, never validated
against RBAC). Nothing stopped the genuine dead ends from being saved: an
open stage in an organization where nobody holds ``approvals:approve``, a
stage naming people who cannot see approvals, and — the default shape of a
fresh solo organization — an open stage where the only holder of the grant
is the requester the door refuses a self-decision to. All three produce a
request parked where nobody can act on it — and such a request used to look
exactly like an empty queue.

The rule is the decision door's own, so that this module can neither refuse
what the door would accept nor accept what it would refuse. An open stage is
decided by anyone holding ``approvals:approve``. A stage naming people is
decided by one of them, who reach it through delegation with
``approvals:read`` alone as the floor — naming is the authority the form
promises — or with the approve grant, which decides on any stage it is named
on. ``_services_decisions.stage_accepts_approver`` and the router's
``_require_decision_possible`` are the door this mirrors.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api import core_api

from .models import ApprovalWorkflow

#: The grant that decides on any stage, open or named.
APPROVE_GRANT = 'approvals:approve'

#: The floor for a person the stage names (delegation).
READ_GRANT = 'approvals:read'

#: Why a stage has nobody who can decide it, in stable codes: the frontend
#: turns each one into a sentence beside the request it holds up.
NO_APPROVER_IN_ORGANIZATION = 'no_approver_in_organization'
NAMED_APPROVERS_CANNOT_DECIDE = 'named_approvers_cannot_decide'
ONLY_THE_REQUESTER_CAN_DECIDE = 'only_the_requester_can_decide'


def named_approvers(stage: dict[str, Any]) -> list[UUID]:
    """The people a stage names. An empty list is an open stage."""
    named: list[UUID] = []
    for raw in stage.get('approver_user_ids') or []:
        if not str(raw).strip():
            continue
        try:
            named.append(raw if isinstance(raw, UUID) else UUID(str(raw)))
        except ValueError:
            continue
    return named


def stage_label(stage: dict[str, Any]) -> str:
    """What to call a stage in a refusal — its label, its role, or its order."""
    return str(stage.get('label') or stage.get('role') or f'#{stage.get("order", "?")}')


def cannot_be_decided_reason(
    stage: dict[str, Any],
    *,
    org_has_approver: bool,
    deciders: Collection[UUID],
    requester_id: UUID | None = None,
    approver_holders: Collection[UUID] | None = None,
    requester_may_decide_own: bool = False,
) -> str | None:
    """Why nobody could decide this stage, or ``None`` when somebody can.

    Pure on purpose: the callers differ in how many stages they ask about —
    a save asks about one workflow, the queue asks about every request it
    lists — and only the fetching should differ, not the rule.

    The requester-keyed arguments stay ``None`` where no request exists yet
    (a workflow being saved): the dead end they describe needs an author.
    """
    named = named_approvers(stage)
    if not named:
        if not org_has_approver:
            return NO_APPROVER_IN_ORGANIZATION
        # The third dead end, and the default shape of a fresh solo
        # organization: the stage is open, somebody holds the grant — and
        # that somebody is the requester alone. The decision door refuses a
        # self-decision (unless the organization opted in and the requester
        # is an admin), so the request parks while every surface reads it as
        # merely waiting its turn.
        if (
            requester_id is not None
            and approver_holders is not None
            and not requester_may_decide_own
            and all(holder == requester_id for holder in approver_holders)
        ):
            return ONLY_THE_REQUESTER_CAN_DECIDE
        return None
    if any(user_id in deciders for user_id in named):
        return None
    return NAMED_APPROVERS_CANNOT_DECIDE


async def workflow_dead_ends_async(
    db: AsyncSession,
    org_id: UUID,
    workflows: Sequence[ApprovalWorkflow],
) -> dict[UUID, tuple[bool, str | None]]:
    """Whether every stage of each workflow has somebody who could decide it.

    The same rule the save refuses under and the request reports under,
    asked about whole definitions: the list is the earliest screen a dead
    end can be seen on, before it parks somebody's document. The
    requester-keyed third dead end needs an author, so it is not answered
    here — a definition is judged without one.

    Batched like the request-side version: one permission lookup for every
    named approver of every workflow, and one for the organization's
    holders, so the cost does not grow with the number of rows.
    """
    stages = [stage for workflow in workflows for stage in (workflow.stages or [])]
    every_named: list[UUID] = [
        user_id for stage in stages for user_id in named_approvers(stage)
    ]
    deciders = await deciders_async(db, org_id, list(dict.fromkeys(every_named)))
    has_open_stage = any(not named_approvers(stage) for stage in stages)
    org_has_approver = (
        await org_has_approver_async(db, org_id) if has_open_stage else True
    )

    answers: dict[UUID, tuple[bool, str | None]] = {}
    for workflow in workflows:
        reason: str | None = None
        for stage in workflow.stages or []:
            reason = cannot_be_decided_reason(
                stage, org_has_approver=org_has_approver, deciders=deciders
            )
            if reason is not None:
                break
        answers[workflow.id] = (reason is None, reason)
    return answers


async def org_has_approver_async(db: AsyncSession, org_id: UUID) -> bool:
    """Whether anybody in the organization holds the approve grant."""
    return await core_api.roles.has_holder_async(
        db, organization_id=org_id, permission=APPROVE_GRANT
    )


async def deciders_async(
    db: AsyncSession, org_id: UUID, user_ids: Sequence[UUID]
) -> set[UUID]:
    """Which of these people can decide, in one batch.

    Either grant is enough for the people a stage names: the approve grant
    decides on any stage, and the read grant is the floor that lets a named
    person through the door.
    """
    if not user_ids:
        return set()
    held = await core_api.roles.permissions_for_users_async(
        db, organization_id=org_id, user_ids=list(user_ids)
    )
    return {
        user_id
        for user_id, permissions in held.items()
        if APPROVE_GRANT in permissions or READ_GRANT in permissions
    }
