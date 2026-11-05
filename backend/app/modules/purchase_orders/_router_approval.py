"""PO approval proxy router — thin delegation to the approvals module.

Mirrors the document approval routes (``approvals/_documents_router.py``),
which have since moved into the approvals module. The approvals module decides
HOW (stages, approvers, notifications); this router decides WHEN and
how the PO state machine reacts:

- POST   /api/v1/purchase-orders/{po_id}/request-approval — park a DRAFT
  PO in PENDING_APPROVAL and create a manual request
- POST   /api/v1/purchase-orders/{po_id}/approve — approve the active
  request; PO flips PENDING_APPROVAL → CONFIRMED
- POST   /api/v1/purchase-orders/{po_id}/reject — reject; PO returns to
  DRAFT so the requester can edit and re-submit
- GET    /api/v1/purchase-orders/{po_id}/approval — active request
- GET    /api/v1/purchase-orders/{po_id}/approval-requirement — what
  confirming would do, and whether anybody could decide it

Graceful degradation: if the approvals module is disabled,
``request_approval`` is a no-op-safe call through ``approvals_api``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.dtos import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import NotFoundException
from app.i18n.service import get_current_lang
from app.modules.approvals.approvals_api import approvals_api
from app.modules.approvals.schemas import (
    ApprovalRequestSchema,
    ApproveRequest,
    AskForApproval,
    RejectRequest,
)

from ._service_approval import (
    approve_purchase_order,
    reject_purchase_order,
    request_purchase_order_approval,
)
from ._service_crud import get_purchase_order
from ._service_workflow import confirm_approval_requirement
from .schemas import PurchaseOrderApprovalRequirement


async def _get_po_or_404(db: AsyncSession, org_id: UUID, po_id: UUID) -> Any:
    po = await get_purchase_order(db, org_id, po_id)
    if not po:
        raise NotFoundException('purchase_order', get_current_lang())
    return po


def register_approval_routes(router: APIRouter) -> None:
    @router.post('/{po_id}/request-approval', response_model=ApprovalRequestSchema)
    async def request_approval_endpoint(
        po_id: UUID,
        body: AskForApproval = AskForApproval(),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        po = await _get_po_or_404(db, org_id, po_id)
        return await request_purchase_order_approval(
            db, org_id, po, current_user.id, body.notes
        )

    @router.post(
        '/{po_id}/approve',
        response_model=ApprovalRequestSchema,
        dependencies=[require_permission('approvals:approve')],
    )
    async def approve_endpoint(
        po_id: UUID,
        body: ApproveRequest = ApproveRequest(),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        po = await _get_po_or_404(db, org_id, po_id)
        request_obj = await approve_purchase_order(
            db, org_id, po, current_user.id, body.notes
        )
        return request_obj

    @router.post(
        '/{po_id}/reject',
        response_model=ApprovalRequestSchema,
        dependencies=[require_permission('approvals:approve')],
    )
    async def reject_endpoint(
        po_id: UUID,
        body: RejectRequest = RejectRequest(),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        po = await _get_po_or_404(db, org_id, po_id)
        return await reject_purchase_order(db, org_id, po, current_user.id, body.notes)

    @router.get(
        '/{po_id}/approval-requirement',
        response_model=PurchaseOrderApprovalRequirement,
    )
    async def get_approval_requirement_endpoint(
        po_id: UUID,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> PurchaseOrderApprovalRequirement:
        po = await _get_po_or_404(db, org_id, po_id)
        return await confirm_approval_requirement(db, org_id, po, current_user.id)

    @router.get('/{po_id}/approval', response_model=ApprovalRequestSchema | None)
    async def get_approval_endpoint(
        po_id: UUID,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> Any:
        await _get_po_or_404(db, org_id, po_id)
        pending = await approvals_api.list_requests(
            db, org_id, target_type='purchase_order'
        )
        matching = [r for r in pending if r.target_id == po_id]
        return matching[0] if matching else None
