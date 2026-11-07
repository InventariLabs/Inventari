from datetime import UTC, datetime
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import acquire_advisory_lock
from app.core.logging import get_logger
from app.core.module_sdk import journal_config_change, record_settings

from ._audit import people_names_async
from ._services_approver_validation import ensure_approvers_in_org
from ._services_requesters import ensure_requesters_in_org, requester_labels_async
from ._services_solvability import workflow_dead_ends_async
from ._services_waiting import name_waiting, waiting_requests_async
from .exceptions import ApprovalError, ApprovalNotFoundError
from .models import OPEN_STATUSES, ApprovalRequest, ApprovalWorkflow
from .schemas import WorkflowSchema
from .target_scopes import describe_scope_async

logger = get_logger(__name__)

VALID_STATUSES = frozenset({*OPEN_STATUSES, 'APPROVED', 'REJECTED', 'CANCELLED'})
DECISION_VALUES = frozenset({'PENDING', 'APPROVED', 'REJECTED'})


async def _journal_workflow(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID | None,
    target_type: str,
    before: Any,
    after: Any,
) -> None:
    """Which targets stop and wait for an answer is decided here: journalled.

    Written in the change's own transaction, so the entry and the change it
    describes land together. The requests a change closes write their own
    rows; this one is about the rule they waited under.
    """
    before_map = record_settings(before) if before is not None else None
    after_map = record_settings(after) if after is not None else None
    await journal_config_change(
        db,
        org_id,
        user_id,
        module='approvals',
        subject=f'workflow:{target_type}',
        keys={'name', 'target_type', 'is_active', 'stages', 'requester_scope'},
        before=await _stages_by_name_async(db, org_id, before_map),
        after=await _stages_by_name_async(db, org_id, after_map),
    )


async def _stages_by_name_async(
    db: AsyncSession, org_id: UUID, settings: dict[str, Any] | None
) -> dict[str, Any] | None:
    """The workflow as the journal reads it: each stage by its order, its
    approvers by name.

    The stage list went in as written, so an approver change read
    ``Stages: {…"approver_user_ids":[]} → {…["b1235cdc-…"]}`` — a list the
    journal prints whole, holding an id nobody can look up. Keyed by order,
    the journal names the stage field that moved; by name, the person.
    """
    if not settings or not isinstance(settings.get('stages'), list):
        return settings
    stages = [stage for stage in settings['stages'] if isinstance(stage, dict)]
    ids = {str(uid) for stage in stages for uid in stage.get('approver_user_ids') or []}
    names = await people_names_async(db, org_id, [UUID(uid) for uid in sorted(ids)])
    return {
        **settings,
        'stages': {
            str(stage.get('order')): {
                **{
                    key: value
                    for key, value in stage.items()
                    if key not in {'order', 'approver_user_ids'}
                },
                'approvers': [
                    names.get(str(uid), str(uid))
                    for uid in stage.get('approver_user_ids') or []
                ],
            }
            for stage in stages
        },
    }


class _Waiting(NamedTuple):
    requests: int
    #: The labels a refusal names, from ``name_waiting``.
    documents: str


async def _requests_waiting_on(
    db: AsyncSession, org_id: UUID, workflow_id: UUID
) -> _Waiting | None:
    """What open requests still stand on a workflow, for the refusal to name.

    A change to the workflow is refused while any wait, and the sentence has
    to say how many and which, because the reader has to find them: it is the
    only thing the toast shows.
    """
    waiting = (await waiting_requests_async(db, org_id, [workflow_id])).get(
        workflow_id, []
    )
    if not waiting:
        return None
    return _Waiting(len(waiting), name_waiting(waiting))


async def get_active_workflow(
    db: AsyncSession, org_id: UUID, target_type: str
) -> ApprovalWorkflow | None:
    result = await db.execute(
        select(ApprovalWorkflow).where(
            ApprovalWorkflow.organization_id == org_id,
            ApprovalWorkflow.target_type == target_type,
            ApprovalWorkflow.is_active.is_(True),
            ApprovalWorkflow.archived_at.is_(None),
        )
    )
    return result.scalars().first()


async def get_workflow_by_id(
    db: AsyncSession, org_id: UUID, workflow_id: UUID
) -> ApprovalWorkflow | None:
    result = await db.execute(
        select(ApprovalWorkflow).where(
            ApprovalWorkflow.id == workflow_id,
            ApprovalWorkflow.organization_id == org_id,
        )
    )
    return result.scalars().first()


async def list_workflows(db: AsyncSession, org_id: UUID) -> list[dict[str, Any]]:
    """Every workflow of the organization, each with the dead-end verdict.

    The verdict belongs beside the definition, not only beside the request
    that hits it: whether a stage can ever be decided is a property of the
    definition, and the list is where an administrator can still fix it —
    after a document has parked on it, it is somebody else's screen.

    An archived workflow is not on it: it was deleted, and what remains of it
    is the history its requests read.
    """
    result = await db.execute(
        select(ApprovalWorkflow)
        .where(
            ApprovalWorkflow.organization_id == org_id,
            ApprovalWorkflow.archived_at.is_(None),
        )
        # A page boundary holds only over an order that does not change
        # between two reads.
        .order_by(ApprovalWorkflow.created_at, ApprovalWorkflow.id)
    )
    workflows = list(result.scalars().all())
    dead_ends = await workflow_dead_ends_async(db, org_id, workflows)
    # Asked once per target type, not per row: the answer is about the
    # module's settings, which every workflow of that type shares.
    scopes = {
        target_type: await describe_scope_async(db, org_id, target_type)
        for target_type in {workflow.target_type for workflow in workflows}
    }
    waiting = await waiting_requests_async(
        db, org_id, [wf.id for wf in workflows if not dead_ends[wf.id][0]]
    )
    requesters = await requester_labels_async(db, org_id, workflows)
    items: list[dict[str, Any]] = []
    for workflow in workflows:
        solvable, reason = dead_ends[workflow.id]
        item = WorkflowSchema.model_validate(workflow).model_dump()
        item['solvable'] = solvable
        item['undecidable_reason'] = reason
        scope = scopes[workflow.target_type]
        item['scope'] = scope.model_dump() if scope is not None else None
        item['requesters'] = [label.model_dump() for label in requesters[workflow.id]]
        item['waiting_requests'] = [
            {
                'request_id': w.request_id,
                'target_type': w.target_type,
                'target_id': w.target_id,
                'label': w.label,
            }
            for w in waiting.get(workflow.id, [])
        ]
        items.append(item)
    return items


async def _preserve_stage_history(
    db: AsyncSession,
    workflow: ApprovalWorkflow,
    stages: list[dict[str, Any]],
) -> ApprovalWorkflow:
    """Keep a used definition frozen when either save path changes stages."""
    if stages == workflow.stages or not await _request_count(db, workflow.id):
        return workflow

    replacement = ApprovalWorkflow(
        organization_id=workflow.organization_id,
        target_type=workflow.target_type,
        name=workflow.name,
        stages=stages,
        is_active=workflow.is_active,
        requester_scope=workflow.requester_scope,
    )
    workflow.archived_at = datetime.now(UTC)
    workflow.updated_at = workflow.archived_at
    workflow.is_active = False
    # Free the live target-type slot before inserting the replacement.
    await db.flush()
    db.add(replacement)
    return replacement


async def create_workflow(
    db: AsyncSession,
    org_id: UUID,
    target_type: str,
    name: str,
    stages: list[dict[str, Any]],
    is_active: bool = False,
    requester_scope: dict[str, Any] | None = None,
    created_by: UUID | None = None,
) -> ApprovalWorkflow:
    """Save a workflow for a target type, or rewrite the one already there.

    ``requester_scope`` is whose submissions it holds; ``None`` keeps the
    column's default, everyone — the API never sends ``None``, it makes the
    administrator choose. ``created_by`` is who the journal names.
    """
    # Saved off by default: a workflow holds nothing until somebody switches
    # it on, and the screen that does so says what it will hold. Saved on, a
    # workflow for documents whose profile names nothing held every confirmed
    # document from that moment — with nothing on the form to say so.
    if not stages:
        raise ApprovalError.translated('approval_workflow_needs_stage')

    # Copy to avoid mutating the caller's list/dicts when we auto-assign
    # ``order`` below.
    stages = [dict(s) for s in stages]
    for i, stage in enumerate(stages):
        if stage.get('order') is None:
            stage['order'] = i + 1

    await ensure_approvers_in_org(
        db,
        org_id,
        (uid for stage in stages for uid in stage.get('approver_user_ids') or []),
    )
    if requester_scope is not None:
        await ensure_requesters_in_org(db, org_id, requester_scope)

    # Serialize per (org, target_type) so the "does one already exist?"
    # check and the subsequent insert/update are atomic across concurrent
    # callers. A transaction-scoped advisory lock is lighter than a row
    # FOR UPDATE (it blocks no reads, only other writers on the same key)
    # and workflow creation is a rare admin operation, so serializing it
    # is cheap. The ``uq_workflow_org_target`` unique index remains as a
    # backstop defence-in-depth. ``delete_workflow`` takes the same key
    # before it archives, so an archive and a create never interleave.
    #
    # An archived workflow is not "one already": its stages are what its
    # requests were decided under, so the new workflow is a new row.
    await acquire_advisory_lock(db, f'approval_workflow:{org_id}:{target_type}')
    existing = await db.execute(
        select(ApprovalWorkflow).where(
            ApprovalWorkflow.organization_id == org_id,
            ApprovalWorkflow.target_type == target_type,
            ApprovalWorkflow.archived_at.is_(None),
        )
    )
    existing_workflow = existing.scalars().first()

    if existing_workflow:
        # If there are any in-flight requests, refuse to overwrite the
        # existing workflow's stages — re-shaping the stages while requests
        # are pending can leave them in a broken state (e.g. an approver
        # hits a stage that no longer exists, or skips an authorization
        # check because the restricted list was removed).  This mirrors
        # the guard in ``update_workflow``.
        waiting = await _requests_waiting_on(db, org_id, existing_workflow.id)
        if waiting:
            raise ApprovalError.translated(
                'approval_workflow_modify_blocked',
                count=waiting.requests,
                documents=waiting.documents,
            )
        before = record_settings(existing_workflow)
        existing_workflow = await _preserve_stage_history(db, existing_workflow, stages)
        existing_workflow.name = name
        existing_workflow.stages = stages
        existing_workflow.is_active = is_active
        if requester_scope is not None:
            existing_workflow.requester_scope = requester_scope
        existing_workflow.updated_at = datetime.now(UTC)
        await db.flush()
        await _journal_workflow(
            db, org_id, created_by, target_type, before, existing_workflow
        )
        return existing_workflow

    workflow = ApprovalWorkflow(
        organization_id=org_id,
        target_type=target_type,
        name=name,
        stages=stages,
        is_active=is_active,
        **({'requester_scope': requester_scope} if requester_scope is not None else {}),
    )
    db.add(workflow)
    await db.flush()
    await _journal_workflow(db, org_id, created_by, target_type, None, workflow)
    return workflow


async def update_workflow(
    db: AsyncSession,
    org_id: UUID,
    workflow_id: UUID,
    name: str | None = None,
    stages: list[dict[str, Any]] | None = None,
    is_active: bool | None = None,
    released_by: UUID | None = None,
    requester_scope: dict[str, Any] | None = None,
) -> ApprovalWorkflow:
    """Edit a workflow.

    A new ``requester_scope`` applies from the next submission and is not
    refused while requests wait: those were raised, and they wait on their
    stages whoever the workflow holds now.

    Switching it off (``is_active=False``) while requests wait on it closes
    those requests as ``released_by`` and lets their targets go on as if no
    approval had been asked; without an actor to record the refusal stands.
    A change of stages stays refused while anything waits: the requests were
    raised against the stages as they were.

    With only past requests, changed stages archive this definition and
    return a replacement. Those requests keep reading their original stages.

    An archived workflow is refused whole — name, stages and switch alike:
    its requests read their stages from it, and switched on it would hold
    targets again from beside the workflow that replaced it.
    """
    await acquire_advisory_lock(db, f'approval_workflow:{workflow_id}')
    workflow = await get_workflow_by_id(db, org_id, workflow_id)
    if workflow is None:
        raise ApprovalNotFoundError.translated('approval_workflow_not_found')
    await acquire_advisory_lock(
        db, f'approval_workflow:{org_id}:{workflow.target_type}'
    )
    await db.refresh(workflow)
    if workflow.archived_at is not None:
        raise ApprovalError.translated('approval_workflow_archived')
    before = record_settings(workflow)

    if stages is not None and not stages:
        raise ApprovalError.translated('approval_workflow_needs_stage')

    if stages is not None:
        await ensure_approvers_in_org(
            db,
            org_id,
            (uid for stage in stages for uid in stage.get('approver_user_ids') or []),
        )

    if requester_scope is not None:
        await ensure_requesters_in_org(db, org_id, requester_scope)

    if stages is not None or is_active is False:
        waiting = await _requests_waiting_on(db, org_id, workflow_id)
        if waiting:
            if stages is not None or released_by is None:
                raise ApprovalError.translated(
                    'approval_workflow_modify_blocked',
                    count=waiting.requests,
                    documents=waiting.documents,
                )
            await release_waiting_requests(
                db, org_id, workflow_id, released_by, reason='workflow deactivated'
            )

    if stages is not None:
        stages = [dict(s) for s in stages]
        for i, stage in enumerate(stages):
            if stage.get('order') is None:
                stage['order'] = i + 1
        workflow = await _preserve_stage_history(db, workflow, stages)
        workflow.stages = stages
    if name is not None:
        workflow.name = name
    if is_active is not None:
        workflow.is_active = is_active
    if requester_scope is not None:
        workflow.requester_scope = requester_scope

    workflow.updated_at = datetime.now(UTC)
    await db.flush()
    await _journal_workflow(
        db, org_id, released_by, workflow.target_type, before, workflow
    )
    return workflow


async def _request_count(db: AsyncSession, workflow_id: UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(ApprovalRequest)
        .where(ApprovalRequest.workflow_id == workflow_id)
    )
    return result.scalar() or 0


async def delete_workflow(
    db: AsyncSession,
    org_id: UUID,
    workflow_id: UUID,
    released_by: UUID | None = None,
) -> dict[str, Any]:
    """Remove a workflow — without erasing the decisions taken under it.

    Deleting used to cascade through every request and decision ever raised
    against the workflow, terminal ones included. Who approved a €40,000
    order, and when, is exactly the record an approval feature exists to
    leave behind; a settings screen must not be able to delete it.

    So a workflow that has history is archived and one that never ran is
    deleted outright, because leaving a mistyped draft on the list forever is
    its own kind of mess. Archived is a state of its own, not "inactive": the
    workflow leaves the list, nothing edits or switches it on again, and the
    next workflow for its target type is a new row, so the requests decided
    under it keep reading the stages they were decided under. Switching it
    off instead left it on the list unchanged, and the next workflow
    overwrote it in place.

    A workflow whose requests were all withdrawn, none decided, is archived
    too. A withdrawn request is still the record that its target was put up
    for approval and went on without one — a workflow switched off or
    deleted closes what waits on it exactly that way — and the requests list
    and the target's own approval badge read it. Archived, it costs nothing:
    it is off the list and holds no slot.

    Requests still waiting are closed as ``released_by`` first, and their
    targets go on as if no approval had been asked — which also makes the
    workflow one that has history, so it is archived. Without an actor to
    record, they block.

    Returns what happened so the caller can say it plainly.
    """
    await acquire_advisory_lock(db, f'approval_workflow:{workflow_id}')
    workflow = await get_workflow_by_id(db, org_id, workflow_id)
    if workflow is None:
        raise ApprovalNotFoundError.translated('approval_workflow_not_found')
    if workflow.archived_at is not None:
        raise ApprovalError.translated('approval_workflow_archived')
    # The key ``create_workflow`` takes: the archive frees the target type's
    # slot, and a create running beside it must see the row before or after,
    # never rewrite it halfway.
    await acquire_advisory_lock(
        db, f'approval_workflow:{org_id}:{workflow.target_type}'
    )

    await db.refresh(workflow)
    if workflow.archived_at is not None:
        raise ApprovalError.translated('approval_workflow_archived')
    before = record_settings(workflow)

    waiting = await _requests_waiting_on(db, org_id, workflow_id)
    if waiting:
        if released_by is None:
            raise ApprovalError.translated(
                'approval_workflow_delete_blocked',
                count=waiting.requests,
                documents=waiting.documents,
            )
        await release_waiting_requests(
            db, org_id, workflow_id, released_by, reason='workflow deleted'
        )

    history_count = await _request_count(db, workflow_id)
    if history_count:
        archived_at = datetime.now(UTC)
        workflow.is_active = False
        workflow.archived_at = archived_at
        workflow.updated_at = archived_at
        await db.flush()
        # Archived or deleted, the workflow leaves the list: the entry reads
        # the same, and the response says which it was.
        await _journal_workflow(
            db, org_id, released_by, workflow.target_type, before, None
        )
        return {'archived': True, 'requests_kept': history_count}

    await db.delete(workflow)
    await db.flush()
    await _journal_workflow(db, org_id, released_by, workflow.target_type, before, None)
    return {'archived': False, 'requests_kept': 0}


async def waiting_on_workflow(
    db: AsyncSession, org_id: UUID, workflow_id: UUID
) -> list[tuple[str, int]]:
    """How many requests wait on this workflow, per kind of target."""
    rows = await db.execute(
        select(ApprovalRequest.target_type, func.count())
        .where(
            ApprovalRequest.organization_id == org_id,
            ApprovalRequest.workflow_id == workflow_id,
            ApprovalRequest.status.in_(OPEN_STATUSES),
        )
        .group_by(ApprovalRequest.target_type)
        .order_by(ApprovalRequest.target_type)
    )
    return [(target_type, count) for target_type, count in rows.all()]


async def release_waiting_requests(
    db: AsyncSession,
    org_id: UUID,
    workflow_id: UUID,
    released_by: UUID,
    *,
    reason: str,
) -> int:
    """Close every open request of a workflow that is being switched off.

    Each one is cancelled as ``released_by`` with ``reason`` on the request and
    in the journal, its target is told (a document goes back to CONFIRMED, an
    order out of PENDING_APPROVAL) and its requester gets a notice. Runs in the
    caller's transaction.
    """
    from ._services_decisions import cancel_request
    from ._services_notify import notify_request_closed

    ids = (
        await db.scalars(
            select(ApprovalRequest.id)
            .where(
                ApprovalRequest.organization_id == org_id,
                ApprovalRequest.workflow_id == workflow_id,
                ApprovalRequest.status.in_(OPEN_STATUSES),
            )
            .order_by(ApprovalRequest.created_at, ApprovalRequest.id)
        )
    ).all()
    for request_id in ids:
        request = await cancel_request(
            db, org_id, request_id, released_by, cascade=True, reason=reason
        )
        await notify_request_closed(
            db,
            org_id,
            request.id,
            request.created_by,
            reason=reason,
            target=(request.target_type, request.target_id),
        )
    return len(ids)
