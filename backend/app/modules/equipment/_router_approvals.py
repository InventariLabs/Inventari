from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import UserContextDTO
from app.core.deps import get_async_db, get_current_user_context, require_org
from app.core.exceptions import ConflictException, NotFoundException, refusal_code
from app.core.public_api import core_api
from app.modules.approvals.approvals_api import approvals_api
from app.modules.approvals.exceptions import ApprovalError as ApprovalsApprovalError

from ._approval_checkout import checkout_request_meta
from .schemas import (
    ApprovalActionResponse,
    CheckoutApprovalAsk,
    EquipmentApprovalStatus,
)

router = APIRouter()

# The approvals target for an equipment asset. The frontend treats the item id
# as the approval target (see AssetDetailPage useApprovalStatus(id)).
_TARGET_TYPE = 'equipment_checkout'


async def _require_item(
    db: AsyncSession, org_id: UUID, item_id: UUID, *, include_archived: bool = False
) -> None:
    """Validate the item exists in the org, else raise NotFoundException.

    ``include_archived`` is for the status read — the card renders for an
    archived asset too. Requesting approval stays live-only: the ask is a
    write about an asset in service, and an archived one is not.
    """
    if include_archived:
        item = await core_api.items.get_any_async(db, org_id, item_id)
    else:
        item = await core_api.items.get_async(db, org_id, item_id)
    if item is None:
        raise NotFoundException('item')


@router.get('/{item_id}/approval-status', response_model=EquipmentApprovalStatus)
async def get_approval_status(
    item_id: UUID,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    org_id = require_org(current_user)
    await _require_item(db, org_id, item_id, include_archived=True)

    workflow = await approvals_api.get_active_workflow(db, org_id, _TARGET_TYPE)
    # A workflow that does not hold this person's checkouts is, for them, no
    # workflow: the screen offers the checkout instead of a request.
    has_workflow = workflow is not None and not await approvals_api.requester_exempt(
        db, org_id, _TARGET_TYPE, current_user.id
    )

    request_id: UUID | None = None
    status: str | None = None
    consumed = False
    if has_workflow:
        requests = await approvals_api.list_requests(
            db, org_id, target_type=_TARGET_TYPE, target_id=item_id
        )
        if requests:
            latest = requests[0]
            request_id = latest.id
            status = latest.status
            # APPROVED and spent is not the same as APPROVED and waiting: the
            # first opens a checkout, the second already opened one.
            consumed = latest.status == 'APPROVED' and latest.consumed_at is not None

    return EquipmentApprovalStatus(
        has_workflow=has_workflow,
        request_id=request_id,
        status=status,
        consumed=consumed,
    )


@router.post('/{item_id}/request-approval', response_model=ApprovalActionResponse)
async def request_approval(
    item_id: UUID,
    ask: CheckoutApprovalAsk | None = None,
    current_user: UserContextDTO = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_async_db, scope='function'),
) -> Any:
    """Ask for one checkout of the asset.

    ``ask`` is the checkout the approval is for — who gets the asset and
    until when — so the approver does not decide blind and the approval
    covers that checkout only. Without it the request names nobody and
    covers the next checkout, as requests raised elsewhere do.
    """
    org_id = require_org(current_user)
    await _require_item(db, org_id, item_id)

    meta_data = (
        await checkout_request_meta(
            db,
            org_id,
            assigned_to_name=ask.assigned_to_name,
            assignee_partner_id=ask.assignee_partner_id,
            checkout_location_id=ask.checkout_location_id,
            expected_return_at=ask.expected_return_at,
        )
        if ask is not None
        else None
    )
    try:
        request_obj = await approvals_api.request_approval(
            db,
            org_id,
            _TARGET_TYPE,
            item_id,
            current_user.id,
            meta_data,
        )
    except ApprovalsApprovalError as exc:
        raise ConflictException(
            code=refusal_code(exc, 'APPROVAL_ERROR'), message=str(exc)
        ) from exc

    return ApprovalActionResponse(
        request_id=str(request_obj.id), status=request_obj.status
    )
