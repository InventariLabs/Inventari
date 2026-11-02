from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_any_permission,
    require_org,
    require_permission,
)
from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
)
from app.core.modules import require_module
from app.i18n.service import get_current_lang, get_error_message
from app.schemas.pagination import PaginatedResponse

from ._documents_router import router as documents_router
from ._error_mapping import map_approval_errors
from .approvals_api import approvals_api
from .approvals_dtos import ApprovalRequestDTO, ApprovalWorkflowDTO
from .models import ApprovalWorkflow
from .schemas import (
    ApprovalRequestSchema,
    ApproveRequest,
    RejectRequest,
    RequestApproval,
    WaitingOnTarget,
    WorkflowConfigured,
    WorkflowCreate,
    WorkflowDeletionResult,
    WorkflowSchema,
    WorkflowUpdate,
    WorkflowWaiting,
)

router = APIRouter(dependencies=[Depends(require_module('approvals'))])


def _require_module_permission(
    permission: str, error_key: str
) -> Callable[[UserContextDTO], None]:
    """Gate on a permission the module declares in its manifest.

        These are the first module permissions the product actually enforces
    . They replace a gate on the ``admin``/``manager`` role names: a role
        name is not an authority, and the previous check meant a manager could approve
        anything anywhere while a dedicated approver could approve nothing.

        Admins keep the bypass built into ``UserContextDTO.has_permission``, so an
        organization that has granted nothing is still administrable. Everyone else
        needs the grant, which ``default_roles`` hands to matching roles when the
        module is enabled.
    """

    def check(user: UserContextDTO) -> None:
        if not user.has_permission(permission):
            raise ForbiddenException(
                get_error_message(error_key, get_current_lang()),
            )

    return check


#: Creating and editing workflows, and what switching one off would release.
_CONFIGURE = require_permission(
    'approvals:configure', message_key='approvals_manage_admin_only'
)

#: Raising a request for a target.
_WRITE = require_permission('approvals:write', message_key='approvals_write_forbidden')

#: One workflow's definition: its stages, approvers and scope. Configuring
#: implies reading, as the workflow list already admits.
_READ = require_any_permission(
    'approvals:read', 'approvals:configure', message_key='approvals_read_forbidden'
)


def _may_read_all_approvals(user: UserContextDTO) -> bool:
    """Whether this user sees the whole organization's approval traffic.

    Without the grant a member still sees their own requests and anything
    waiting on their decision — the org-wide queue, with its amounts,
    partners and approver names, is what ``approvals:read`` unlocks.
    """
    return user.has_permission('approvals:read')


#: Approving or rejecting a request.
#:
#: The workflow stage ``role`` field is an arbitrary label (see
#: ``approvals/models.py``) — never validated against user roles. Without this
#: gate, a regular user with org membership could call /approve and either
#: silently advance the request into a stage they shouldn't see, or hit a 500
#: from a downstream constraint. Gateway the check at the HTTP boundary so
#: the bug surfaces as 403.
_require_approver_action = _require_module_permission(
    'approvals:approve', 'approvals_action_admin_only'
)


async def _require_decision_possible(
    db: AsyncSession,
    org_id: UUID,
    request_id: UUID,
    user: UserContextDTO,
) -> None:
    """Admit a user to /approve or /reject only when a decision by them is
    possible at all.

    The approve grant decides on every open stage. A person *named* on the
    stage the request sits at decides through delegation, with the read
    grant alone as the floor — being named is the authority the workflow
    form promises, and without it an organization without managers could
    never resolve its own flows. Anyone else gets the same 403 as before.
    The service still applies its own rules behind this door (own request,
    stage membership), so passing here decides nothing by itself.
    """
    from .services import get_request_enriched

    result = await get_request_enriched(
        db,
        org_id,
        request_id,
        viewer_id=user.id,
        viewer_has_approve_grant=user.has_permission('approvals:approve'),
        viewer_has_read_grant=user.has_permission('approvals:read'),
    )
    if result is None:
        raise NotFoundException(resource='approval_request')
    if not result.get('viewer_can_decide'):
        _require_approver_action(user)


@router.get('/workflows', response_model=PaginatedResponse[WorkflowSchema])
async def list_workflows(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> PaginatedResponse[dict[str, Any]]:
    # The same contract as GET /requests: a role without the grants gets a
    # 200 with what it may see — for definitions, nothing — never a refusal
    # its sibling list does not get either — one module, one behaviour.
    # Configuring still implies reading: an editor handed
    # ``approvals:configure`` alone can open the workflows it edits.
    if not (
        current_user.has_permission('approvals:read')
        or current_user.has_permission('approvals:configure')
    ):
        return PaginatedResponse.from_full_list([], offset=offset, limit=limit)
    from .services import list_workflows as svc_list_workflows

    workflows = await svc_list_workflows(db, org_id)
    return PaginatedResponse.from_full_list(workflows, offset=offset, limit=limit)


@router.get('/workflows/configured', response_model=WorkflowConfigured)
async def get_workflow_configured(
    target_type: str = Query(..., min_length=1, max_length=64),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> WorkflowConfigured:
    """Whether a request for ``target_type`` would land anywhere.

    Deliberately not gated on ``approvals:read``: the accounts that need
    this answer are the ones composing a request, and a role may hold the
    target module's write right without any read grant over approvals —
    for those, the workflow list says nothing and the refusal behind the
    button arrived only after the click. The answer is one bit about the
    configuration, the same bit the request endpoint itself reveals by
    accepting or refusing.

    Declared above ``/workflows/{workflow_id}`` on purpose: below it,
    ``configured`` is parsed as a workflow id and answered 422.
    """
    workflow = await approvals_api.get_active_workflow(db, org_id, target_type)
    return WorkflowConfigured(
        configured=workflow is not None and bool(workflow.stages or []),
    )


@router.post(
    '/workflows',
    response_model=WorkflowSchema,
    status_code=201,
    dependencies=[_CONFIGURE],
)
@map_approval_errors('workflow', conflict=True)
async def create_workflow_endpoint(
    data: WorkflowCreate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ApprovalWorkflowDTO:
    # ``mode='json'`` serialises UUID objects to strings so the JSONB column
    # can store ``approver_user_ids`` without a TypeError.
    if data.is_active:
        from .target_scopes import ensure_scope_unchanged_async

        await ensure_scope_unchanged_async(
            db, org_id, data.target_type, data.expected_scope
        )
    stages_dict = [s.model_dump(mode='json') for s in data.stages]
    from ._services_validation import validate_workflow_decidable

    await validate_workflow_decidable(
        db,
        org_id,
        stages_dict,
        allow_undecidable=data.allow_undecidable_stages,
    )
    return await approvals_api.create_workflow(
        db,
        org_id,
        data.target_type,
        data.name,
        stages_dict,
        data.is_active,
        requester_scope=data.requester_scope.model_dump(mode='json'),
        created_by=current_user.id,
    )


@router.patch(
    '/workflows/{workflow_id}', response_model=WorkflowSchema, dependencies=[_CONFIGURE]
)
@map_approval_errors('workflow', conflict=True)
async def update_workflow_endpoint(
    workflow_id: UUID,
    data: WorkflowUpdate,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ApprovalWorkflowDTO:
    if data.is_active:
        # Switched on: only under the rule the reader saw. A workflow that
        # is already on keeps the check only when the caller sends a scope.
        from .services import get_workflow_by_id
        from .target_scopes import ensure_scope_unchanged_async

        workflow = await get_workflow_by_id(db, org_id, workflow_id)
        # An archived workflow is refused by the service, with its own reason;
        # a scope that moved since must not answer for it first.
        if (
            workflow is not None
            and workflow.archived_at is None
            and (not workflow.is_active or data.expected_scope is not None)
        ):
            await ensure_scope_unchanged_async(
                db, org_id, workflow.target_type, data.expected_scope
            )
    stages_dict = (
        [s.model_dump(mode='json') for s in data.stages]
        if data.stages is not None
        else None
    )
    if stages_dict is not None:
        from ._services_validation import validate_workflow_decidable

        await validate_workflow_decidable(
            db,
            org_id,
            stages_dict,
            allow_undecidable=data.allow_undecidable_stages,
        )
    return await approvals_api.update_workflow(
        db,
        org_id,
        workflow_id,
        data.name,
        stages_dict,
        data.is_active,
        released_by=current_user.id,
        requester_scope=(
            data.requester_scope.model_dump(mode='json')
            if data.requester_scope is not None
            else None
        ),
    )


@router.delete(
    '/workflows/{workflow_id}',
    response_model=WorkflowDeletionResult,
    dependencies=[_CONFIGURE],
)
@map_approval_errors('workflow', conflict=True)
async def delete_workflow_endpoint(
    workflow_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> WorkflowDeletionResult:
    """Delete a workflow, or archive it when it already carries history.

    The response says which happened so the UI can be honest about it — the
    approvals taken under a workflow outlive the workflow itself.
    """
    outcome = await approvals_api.delete_workflow(
        db, org_id, workflow_id, released_by=current_user.id
    )
    return WorkflowDeletionResult(**outcome)


@router.get(
    '/workflows/{workflow_id}/waiting',
    response_model=WorkflowWaiting,
    dependencies=[_CONFIGURE],
)
@map_approval_errors('workflow')
async def get_workflow_waiting_endpoint(
    workflow_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> WorkflowWaiting:
    """What switching this workflow off or deleting it would release.

    The dialogs read it before asking: how many documents, orders and
    checkouts wait, and whether settings still demand an approval.
    """
    from ._services_workflow import waiting_on_workflow
    from .services import get_workflow_by_id
    from .target_scopes import describe_scope_async

    workflow = await get_workflow_by_id(db, org_id, workflow_id)
    if workflow is None:
        raise NotFoundException(resource='workflow')
    waiting = await waiting_on_workflow(db, org_id, workflow_id)
    # The settings that still demand an approval are the ones the scope the
    # workflow list shows already names: one answer, from the module that
    # owns the gate.
    scope = await describe_scope_async(db, org_id, workflow.target_type)
    return WorkflowWaiting(
        total=sum(count for _, count in waiting),
        waiting=[WaitingOnTarget(target_type=t, count=c) for t, c in waiting],
        settings_requiring_approval=scope.required_by_settings if scope else [],
    )


@router.get(
    '/workflows/{workflow_id}', response_model=WorkflowSchema, dependencies=[_READ]
)
async def get_workflow_endpoint(
    workflow_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ApprovalWorkflow:
    from .services import get_workflow_by_id

    workflow = await get_workflow_by_id(db, org_id, workflow_id)
    if workflow is None:
        raise NotFoundException(resource='workflow')
    return workflow


@router.get('/requests', response_model=PaginatedResponse[ApprovalRequestSchema])
async def list_requests_endpoint(
    target_type: str | None = Query(None),
    status_filter: str | None = Query(
        None,
        alias='status',
        description='One state, or a comma-separated set (e.g. PENDING,IN_PROGRESS).',
    ),
    search: str | None = Query(None, max_length=100),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> PaginatedResponse[ApprovalRequestSchema]:
    from .services import list_requests_enriched

    scoped_to = None if _may_read_all_approvals(current_user) else current_user.id
    items, total = await list_requests_enriched(
        db,
        org_id,
        target_type,
        status_filter,
        search=search,
        limit=limit,
        offset=offset,
        visible_to_user_id=scoped_to,
        include_awaiting_decision=current_user.has_permission('approvals:approve'),
        viewer_id=current_user.id,
        viewer_has_approve_grant=current_user.has_permission('approvals:approve'),
        viewer_has_read_grant=current_user.has_permission('approvals:read'),
    )
    return PaginatedResponse[ApprovalRequestSchema].from_slice(
        items=cast(list[ApprovalRequestSchema], items),
        offset=offset,
        limit=limit,
        total=total,
    )


@router.post(
    '/requests',
    response_model=ApprovalRequestSchema,
    status_code=201,
    dependencies=[_WRITE],
)
@map_approval_errors('approval_request', conflict=True)
async def create_request_endpoint(
    data: RequestApproval,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ApprovalRequestDTO:
    """Create an approval request for a target entity."""
    return await approvals_api.request_approval(
        db,
        org_id,
        data.target_type,
        data.target_id,
        current_user.id,
        meta_data=data.meta_data,
    )


@router.get('/requests/{request_id}', response_model=ApprovalRequestSchema)
async def get_request_endpoint(
    request_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ApprovalRequestSchema:
    from .services import get_request_enriched

    result = await get_request_enriched(
        db,
        org_id,
        request_id,
        viewer_id=current_user.id,
        viewer_has_approve_grant=current_user.has_permission('approvals:approve'),
        viewer_has_read_grant=current_user.has_permission('approvals:read'),
    )
    if result is None:
        raise NotFoundException(resource='approval_request')
    if not _may_read_all_approvals(current_user) and str(
        result.get('created_by') or ''
    ) != str(current_user.id):
        # Someone else's request. Approvers may still open what is waiting on
        # them; everyone else is told no rather than shown the amounts.
        if not current_user.has_permission('approvals:approve'):
            raise ForbiddenException(
                get_error_message('approvals_read_forbidden', get_current_lang())
            )
    return ApprovalRequestSchema.model_validate(result)


@router.post('/requests/{request_id}/approve', response_model=ApprovalRequestSchema)
@map_approval_errors('approval_request')
async def approve_stage_endpoint(
    request_id: UUID,
    body: ApproveRequest = ApproveRequest(),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ApprovalRequestSchema:
    await _require_decision_possible(db, org_id, request_id, current_user)
    from .services import _enrich_request

    result = await approvals_api.approve_stage(
        db, org_id, request_id, current_user.id, body.notes
    )
    return ApprovalRequestSchema.model_validate(await _enrich_request(db, result))


@router.post('/requests/{request_id}/reject', response_model=ApprovalRequestSchema)
@map_approval_errors('approval_request')
async def reject_request_endpoint(
    request_id: UUID,
    body: RejectRequest = RejectRequest(),
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ApprovalRequestSchema:
    await _require_decision_possible(db, org_id, request_id, current_user)
    from .services import _enrich_request

    result = await approvals_api.reject_request(
        db, org_id, request_id, current_user.id, body.notes
    )
    return ApprovalRequestSchema.model_validate(await _enrich_request(db, result))


@router.post('/requests/{request_id}/cancel', response_model=ApprovalRequestSchema)
@map_approval_errors('approval_request')
async def cancel_request_endpoint(
    request_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
    org_id: UUID = Depends(require_org),
) -> ApprovalRequestSchema:
    from .services import _enrich_request

    result = await approvals_api.cancel_request(db, org_id, request_id, current_user.id)
    return ApprovalRequestSchema.model_validate(await _enrich_request(db, result))


# The approval doors of a warehouse document. They reach the document only
# through ``warehouse_api``, imported when a request arrives, and answer only
# where the warehouse is on.
router.include_router(documents_router)
