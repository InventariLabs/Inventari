from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import String, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.core.db_utils import escape_ilike, paginate_async
from app.core.logging import get_logger
from app.core.public_api import core_api
from app.core.public_api.users import UserProfileDTO

from ._services_decisions import _may_decide_on_own_request, stage_accepts_approver
from ._services_solvability import (
    APPROVE_GRANT,
    cannot_be_decided_reason,
    deciders_async,
    named_approvers,
)
from .approvals_dtos import ApprovalRequestDTO
from .models import OPEN_STATUSES, ApprovalRequest, ApprovalWorkflow
from .target_summaries import get_target_summary_provider, target_search_providers

logger = get_logger(__name__)


async def list_requests(
    db: AsyncSession,
    org_id: UUID,
    target_type: str | None = None,
    status: str | None = None,
    target_id: UUID | None = None,
    pending_for_user_id: UUID | None = None,
) -> list[ApprovalRequest]:
    """List approval requests with optional filters.

       ``pending_for_user_id`` returns only
       active (PENDING/IN_PROGRESS) requests where the current stage has
       an open approver list (anyone may approve) OR the user is in the
       assigned approver list. This powers the "To approve" queue
       in the warehouse module so approvers see only what they can act on.

       When ``pending_for_user_id`` is provided, an extra join with the
       workflow is issued to look up the current stage. The Python-side
       filter keeps the SQL portable (no JSONB dialect-specific ops) and
       is acceptable because the working set per user is bounded by the
       number of in-flight requests (typically tens, not thousands).

    requests the user raised themselves are left out — the decision
       services refuse them unless the organization allows admin self-approval,
       and a queue that lists what the API will reject is not a queue.
    """
    q = select(ApprovalRequest).where(
        ApprovalRequest.organization_id == org_id,
    )

    if target_type:
        q = q.where(ApprovalRequest.target_type == target_type)

    if status:
        q = q.where(ApprovalRequest.status == status)

    if target_id:
        q = q.where(ApprovalRequest.target_id == target_id)

    if pending_for_user_id is not None:
        # Restrict to non-terminal statuses.
        q = q.where(ApprovalRequest.status.in_(OPEN_STATUSES))

    result = await db.execute(q.order_by(ApprovalRequest.created_at.desc()))
    rows = list(result.scalars().all())

    if pending_for_user_id is None:
        return rows

    # Look up the current stage for each request to decide visibility.
    from .models import ApprovalWorkflow as _Workflow

    workflow_ids = {r.workflow_id for r in rows}
    if not workflow_ids:
        return []
    workflows = (
        (await db.execute(select(_Workflow).where(_Workflow.id.in_(workflow_ids))))
        .scalars()
        .all()
    )
    by_id = {w.id: w for w in workflows}

    may_decide_on_own = await _may_decide_on_own_request(
        db, org_id, pending_for_user_id
    )

    visible: list[ApprovalRequest] = []
    for r in rows:
        wf = by_id.get(r.workflow_id)
        if wf is None:
            continue
        if r.created_by == pending_for_user_id and not may_decide_on_own:
            continue
        if stage_accepts_approver(
            list(wf.stages or []), r.current_stage, pending_for_user_id
        ):
            visible.append(r)
    return visible


async def find_active_request(
    db: AsyncSession,
    org_id: UUID,
    target_type: str,
    target_id: UUID,
) -> ApprovalRequest | None:
    """Return the active request (PENDING or IN_PROGRESS) for a target, if any.

    Distinct from ``check_and_block``: this is a *query*, not a guard. Use it
    when you want to know whether a request exists before deciding whether
    to enforce approval (e.g. a CONFIRMED doc below threshold that someone
    manually sent to /request-approval).
    """
    result = await db.execute(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.organization_id == org_id,
            ApprovalRequest.target_type == target_type,
            ApprovalRequest.target_id == target_id,
            ApprovalRequest.status.in_(OPEN_STATUSES),
        )
        .order_by(ApprovalRequest.created_at.desc())
    )
    return result.scalars().first()


async def get_request(
    db: AsyncSession,
    org_id: UUID,
    request_id: UUID,
) -> ApprovalRequest | None:
    result = await db.execute(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.id == request_id,
            ApprovalRequest.organization_id == org_id,
        )
        .options(selectinload(ApprovalRequest.decisions))
    )
    return result.scalars().first()


async def list_requests_enriched(
    db: AsyncSession,
    org_id: UUID,
    target_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    visible_to_user_id: UUID | None = None,
    include_awaiting_decision: bool = False,
    viewer_id: UUID | None = None,
    viewer_has_approve_grant: bool | None = None,
    viewer_has_read_grant: bool | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List requests with workflow_stages + user names in O(1) queries.

       Performance: instead of N+1 (1 list query + 1 user lookup per request +
       1 workflow lookup per request + N user lookups per decision), this
       eager-loads decisions via ``selectinload`` (2 queries total) and batches
       the workflow + user lookups into a single IN-query each. Total: 4
       queries regardless of result size.

       ``search`` matches target UUID/type strings, (for documents) the
       target document number — resolved via ``warehouse_api`` to keep the
       module boundary clean — and whatever a registered search provider
       finds by the name the card shows (an asset's name). Returns ``(requests, total)`` so callers can
       build a paginated envelope.

       ``status`` accepts either one state or a comma-separated set of them.
       The decision queue defaults to the open states (``PENDING`` and
       ``IN_PROGRESS``), which a single-value filter cannot express.

       ``viewer_id`` names the person reading the list, so every request can
       carry ``viewer_can_decide`` — the same verdict the decision service will
    reach — instead of leaving the UI to re-derive it.

       ``visible_to_user_id`` narrows the result to what one person is entitled
       to see: their own requests, plus — when ``include_awaiting_decision`` is
       set — the ones currently waiting on their decision. Callers holding
    ``approvals:read`` leave it unset and see the whole organization;
       without it, every member could read the amounts, partners and approver
       names behind every request in the company.
    """
    conditions: list[ColumnElement[bool]] = [ApprovalRequest.organization_id == org_id]
    if target_type:
        conditions.append(ApprovalRequest.target_type == target_type)
    if status:
        wanted = [value.strip() for value in status.split(',') if value.strip()]
        conditions.append(ApprovalRequest.status.in_(wanted))
    if visible_to_user_id is not None:
        own = ApprovalRequest.created_by == visible_to_user_id
        if include_awaiting_decision:
            awaiting = await list_requests(
                db,
                org_id,
                target_type,
                pending_for_user_id=visible_to_user_id,
            )
            conditions.append(
                or_(own, ApprovalRequest.id.in_([r.id for r in awaiting]))
                if awaiting
                else own
            )
        else:
            conditions.append(own)

    if search:
        from app.modules.warehouse.warehouse_api import warehouse_api

        pattern = f'%{escape_ilike(search)}%'
        doc_ids = await warehouse_api.search_document_ids_by_number_async(
            db, org_id, search
        )
        matches = [
            ApprovalRequest.target_id.cast(String).ilike(pattern),
            ApprovalRequest.target_type.ilike(pattern),
            ApprovalRequest.target_id.in_(doc_ids),
        ]
        # The name the card shows, asked of the module that shows it.
        for searched_type, provider in target_search_providers().items():
            found = list(await provider(db, org_id, search))
            if found:
                matches.append(
                    and_(
                        ApprovalRequest.target_type == searched_type,
                        ApprovalRequest.target_id.in_(found),
                    )
                )
        conditions.append(or_(*matches))

    q = (
        select(ApprovalRequest)
        .where(*conditions)
        .options(selectinload(ApprovalRequest.decisions))
        .order_by(ApprovalRequest.created_at.desc())
    )
    if limit is not None:
        requests, total = await paginate_async(db, q, limit=limit, offset=offset)
    else:
        total = (
            await db.scalar(
                select(func.count()).select_from(ApprovalRequest).where(*conditions)
            )
        ) or 0
        result = await db.execute(q)
        requests = list(result.scalars().unique().all())
    if not requests:
        return [], total or 0

    workflow_ids = {r.workflow_id for r in requests}
    user_ids: set[UUID] = set()
    for r in requests:
        if r.created_by:
            user_ids.add(r.created_by)
        for d in r.decisions:
            if d.approver_id:
                user_ids.add(d.approver_id)

    workflows_by_id = await _batch_load_workflows(db, org_id, workflow_ids)
    users_by_id = await _batch_load_users(db, org_id, user_ids)
    target_summaries_by_id = await _batch_load_target_summaries(
        db, org_id, [(r.target_type, r.target_id) for r in requests]
    )

    viewer_may_decide_on_own = (
        await _may_decide_on_own_request(db, org_id, viewer_id)
        if viewer_id is not None
        else False
    )
    solvability = await _solvability_by_request(db, org_id, requests, workflows_by_id)

    return [
        _build_enriched_dict(
            r,
            workflows_by_id,
            users_by_id,
            target_summaries_by_id,
            viewer_id=viewer_id,
            viewer_may_decide_on_own=viewer_may_decide_on_own,
            viewer_has_approve_grant=viewer_has_approve_grant,
            viewer_has_read_grant=viewer_has_read_grant,
            solvability=solvability.get(r.id),
        )
        for r in requests
    ], total or 0


async def get_request_enriched(
    db: AsyncSession,
    org_id: UUID,
    request_id: UUID,
    viewer_id: UUID | None = None,
    viewer_has_approve_grant: bool | None = None,
    viewer_has_read_grant: bool | None = None,
) -> dict[str, Any] | None:
    request = await get_request(db, org_id, request_id)
    if request is None:
        return None

    workflow_ids = {request.workflow_id}
    user_ids: set[UUID] = set()
    if request.created_by:
        user_ids.add(request.created_by)
    for d in request.decisions:
        if d.approver_id:
            user_ids.add(d.approver_id)

    workflows_by_id = await _batch_load_workflows(db, org_id, workflow_ids)
    users_by_id = await _batch_load_users(db, org_id, user_ids)
    target_summaries_by_id = await _batch_load_target_summaries(
        db, org_id, [(request.target_type, request.target_id)]
    )
    solvability = await _solvability_by_request(db, org_id, [request], workflows_by_id)
    return _build_enriched_dict(
        request,
        workflows_by_id,
        users_by_id,
        target_summaries_by_id,
        viewer_id=viewer_id,
        viewer_may_decide_on_own=(
            await _may_decide_on_own_request(db, org_id, viewer_id)
            if viewer_id is not None
            else False
        ),
        viewer_has_approve_grant=viewer_has_approve_grant,
        viewer_has_read_grant=viewer_has_read_grant,
        solvability=solvability.get(request.id),
    )


async def _enrich_request(
    db: AsyncSession, request: ApprovalRequest | ApprovalRequestDTO
) -> dict[str, Any]:
    """Backwards-compat wrapper for callers that already loaded a single
    ApprovalRequest and want it enriched without going through
    ``list_requests_enriched``. Internally batches the lookups just like
    the bulk path so even single-request enrichment avoids per-field
    queries.
    """
    workflow_ids = {request.workflow_id}
    user_ids: set[UUID] = set()
    if request.created_by:
        user_ids.add(request.created_by)
    for d in request.decisions:
        if d.approver_id:
            user_ids.add(d.approver_id)

    workflows_by_id = await _batch_load_workflows(
        db, request.organization_id, workflow_ids
    )
    users_by_id = await _batch_load_users(db, request.organization_id, user_ids)
    target_summaries_by_id = await _batch_load_target_summaries(
        db, request.organization_id, [(request.target_type, request.target_id)]
    )
    solvability = await _solvability_by_request(
        db, request.organization_id, [request], workflows_by_id
    )
    return _build_enriched_dict(
        request,
        workflows_by_id,
        users_by_id,
        target_summaries_by_id,
        solvability=solvability.get(request.id),
    )


async def _batch_load_workflows(
    db: AsyncSession, org_id: UUID, workflow_ids: set[UUID]
) -> dict[UUID, ApprovalWorkflow]:
    """Load all referenced workflows in one IN-query (read-only, no FOR UPDATE)."""
    if not workflow_ids:
        return {}
    result = await db.execute(
        select(ApprovalWorkflow).where(
            ApprovalWorkflow.organization_id == org_id,
            ApprovalWorkflow.id.in_(workflow_ids),
        )
    )
    return {wf.id: wf for wf in result.scalars().all()}


async def _batch_load_users(
    db: AsyncSession, org_id: UUID, user_ids: set[UUID]
) -> dict[UUID, UserProfileDTO]:
    """Load all referenced users in one IN-query via CoreAPI.

    Tenant-safety: the lookup is scoped by *org_id*. The parent
    ApprovalRequest rows are org-scoped already, so this is belt-and-braces
    — but it is what keeps the guarantee inside CoreAPI rather than in a
    comment about the caller.
    """
    if not user_ids:
        return {}
    users = await core_api.users.get_by_ids_async(db, org_id, list(user_ids))
    return {u.id: u for u in users}


async def _solvability_by_request(
    db: AsyncSession,
    org_id: UUID,
    requests: Sequence[ApprovalRequest | ApprovalRequestDTO],
    workflows_by_id: dict[UUID, ApprovalWorkflow],
) -> dict[UUID, tuple[bool, str | None]]:
    """Whether each open request's current stage has anybody who could decide it.

       Batched: the named people of every stage in one permission lookup, and the
       organization's holders of the approve grant once for the whole page. A
       per-request lookup would make the queue cost grow with its length, which
       the enrichment exists to avoid.

       Returns nothing for requests that are not waiting on anybody — a decided
       request has no next stage to be stuck at, and the response says ``null``
    rather than inventing a verdict about it.
    """
    stages_by_request: dict[UUID, dict[str, Any]] = {}
    requests_by_id: dict[UUID, ApprovalRequest | ApprovalRequestDTO] = {}
    for request in requests:
        if request.status not in OPEN_STATUSES:
            continue
        workflow = workflows_by_id.get(request.workflow_id)
        if workflow is None:
            continue
        stage = next(
            (
                s
                for s in (workflow.stages or [])
                if s.get('order') == request.current_stage
            ),
            None,
        )
        if stage is not None:
            stages_by_request[request.id] = stage
            requests_by_id[request.id] = request

    if not stages_by_request:
        return {}

    named = [
        user_id
        for stage in stages_by_request.values()
        for user_id in named_approvers(stage)
    ]
    deciders = await deciders_async(db, org_id, list(dict.fromkeys(named)))
    # The holders of the grant, not just their existence: an open stage whose
    # only holder is the requester is the third dead end, and it takes the
    # set to tell it apart from "somebody could decide".
    approver_holders: set[UUID] | None = (
        await core_api.roles.holders_of_permission_async(
            db, organization_id=org_id, permission=APPROVE_GRANT
        )
        if any(not named_approvers(stage) for stage in stages_by_request.values())
        else None
    )
    org_has_approver = bool(approver_holders) if approver_holders is not None else True

    # The self-decision question only matters for the requester nobody else
    # can stand in for, so it is asked lazily — and once per author.
    may_decide_own: dict[UUID, bool] = {}

    answers: dict[UUID, tuple[bool, str | None]] = {}
    for request_id, stage in stages_by_request.items():
        requester_id = requests_by_id[request_id].created_by
        requester_may_decide_own = False
        if (
            approver_holders
            and all(holder == requester_id for holder in approver_holders)
            and requester_id in approver_holders
        ):
            if requester_id not in may_decide_own:
                may_decide_own[requester_id] = await _may_decide_on_own_request(
                    db, org_id, requester_id
                )
            requester_may_decide_own = may_decide_own[requester_id]
        reason = cannot_be_decided_reason(
            stage,
            org_has_approver=org_has_approver,
            deciders=deciders,
            requester_id=requester_id,
            approver_holders=approver_holders,
            requester_may_decide_own=requester_may_decide_own,
        )
        answers[request_id] = (reason is None, reason)
    return answers


async def _batch_load_target_summaries(
    db: AsyncSession,
    org_id: UUID,
    targets: list[tuple[str, UUID]],
) -> dict[UUID, Any]:
    """Batched target summaries, one call per target type that has a provider.

       Modules describe their own targets — see ``target_summaries`` — so this
       used to name ``warehouse_api`` and skip everything else in silence, which
    is why a purchase order reached the queue as a truncated UUID. A
       target type nobody registered still degrades to ``target_summary: None``.
    """
    ids_by_type: dict[str, list[UUID]] = {}
    for target_type, target_id in targets:
        ids_by_type.setdefault(target_type, []).append(target_id)

    summaries: dict[UUID, Any] = {}
    for target_type, target_ids in ids_by_type.items():
        provider = get_target_summary_provider(target_type)
        if provider is None:
            continue
        summaries.update(await provider(db, org_id, target_ids))
    return summaries


def _viewer_can_decide(
    request: ApprovalRequest | ApprovalRequestDTO,
    workflow: ApprovalWorkflow | None,
    viewer_id: UUID | None,
    may_decide_on_own: bool,
    viewer_has_approve_grant: bool | None = None,
    viewer_has_read_grant: bool | None = None,
) -> bool | None:
    """Whether *viewer_id* can decide on this request right now.

    ``None`` when nobody asked — callers that do not name a viewer get the
    field as null rather than a guess.

    The screen promises that naming an approver hands them the decision, so
    a person named on the stage the request sits at decides through
    *delegation*, with the read grant alone as the floor (they must be able
    to see what they are deciding on). The approve grant decides on every
    open stage as before. Callers that do not say which grants the viewer
    holds get the old stage-only verdict; the router says, so the field
    stays the same verdict the decision service will reach.
    """
    if viewer_id is None:
        return None
    if request.status not in OPEN_STATUSES:
        return False
    if request.created_by == viewer_id and not may_decide_on_own:
        return False
    if workflow is None:
        return False
    stages = list(workflow.stages or [])
    if not stage_accepts_approver(stages, request.current_stage, viewer_id):
        return False
    if viewer_has_approve_grant is None or viewer_has_approve_grant:
        return True
    if not viewer_has_read_grant:
        return False
    stage = next((s for s in stages if s.get('order') == request.current_stage), None)
    named = [str(u) for u in ((stage or {}).get('approver_user_ids') or [])]
    return bool(named) and str(viewer_id) in named


def _build_enriched_dict(
    request: ApprovalRequest | ApprovalRequestDTO,
    workflows_by_id: dict[UUID, ApprovalWorkflow],
    users_by_id: dict[UUID, UserProfileDTO],
    target_summaries_by_id: dict[UUID, Any] | None = None,
    *,
    viewer_id: UUID | None = None,
    viewer_may_decide_on_own: bool = False,
    viewer_has_approve_grant: bool | None = None,
    viewer_has_read_grant: bool | None = None,
    solvability: tuple[bool, str | None] | None = None,
) -> dict[str, Any]:
    creator = users_by_id.get(request.created_by) if request.created_by else None
    created_by_name = (
        creator.full_name or creator.email if creator is not None else None
    )

    workflow = workflows_by_id.get(request.workflow_id)
    workflow_stages = workflow.stages if workflow is not None else None

    decisions = []
    for d in request.decisions:
        approver = users_by_id.get(d.approver_id) if d.approver_id else None
        approver_name = (
            approver.full_name or approver.email if approver is not None else None
        )
        decisions.append(
            {
                'id': d.id,
                'stage_order': d.stage_order,
                'approver_id': d.approver_id,
                'approver_name': approver_name,
                'status': d.status,
                'notes': d.notes,
                'decided_at': d.decided_at,
                'created_at': d.created_at,
            }
        )

    target_summary = None
    if target_summaries_by_id:
        summary_dto = target_summaries_by_id.get(request.target_id)
        if summary_dto is not None:
            # Serialise to a JSON-compatible dict (UUID/Decimal -> str) so the
            # response_model ``ApprovalRequestSchema.target_summary: dict``
            # validates and the wire shape matches the TS interface
            # (total_value: string | null, not Decimal).
            target_summary = summary_dto.model_dump(mode='json')

    return {
        'id': request.id,
        'organization_id': request.organization_id,
        'workflow_id': request.workflow_id,
        'target_type': request.target_type,
        'target_id': request.target_id,
        'status': request.status,
        'current_stage': request.current_stage,
        'total_stages': request.total_stages,
        'created_by': request.created_by,
        'created_by_name': created_by_name,
        'meta_data': request.meta_data,
        'workflow_stages': workflow_stages,
        'decisions': decisions,
        'created_at': request.created_at,
        # Cancelling stamps both columns and the response schema declares
        # them, but they were never copied out — so a withdrawn request could
        # not say when it was withdrawn.
        'cancelled_by': request.cancelled_by,
        'cancelled_at': request.cancelled_at,
        'target_summary': target_summary,
        'viewer_can_decide': _viewer_can_decide(
            request,
            workflow,
            viewer_id,
            viewer_may_decide_on_own,
            viewer_has_approve_grant=viewer_has_approve_grant,
            viewer_has_read_grant=viewer_has_read_grant,
        ),
        # A request nobody can decide is not an empty queue: the stage it
        # waits at, and who is missing, travel with the request. ``None``
        # for the ones that are not waiting on anybody.
        'solvable': None if solvability is None else solvability[0],
        'undecidable_reason': None if solvability is None else solvability[1],
    }
