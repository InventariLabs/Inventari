"""Reorder rule REST endpoints.

Mounted at:
- POST   /api/v1/purchase-orders/reorder-rules
- GET    /api/v1/purchase-orders/reorder-rules
- GET    /api/v1/purchase-orders/reorder-rules/{rule_id}
- PATCH  /api/v1/purchase-orders/reorder-rules/{rule_id}
- DELETE /api/v1/purchase-orders/reorder-rules/{rule_id}

- GET    /api/v1/purchase-orders/replenishment/alerts
- GET    /api/v1/purchase-orders/replenishment/proposals/{rule_id}
- POST   /api/v1/purchase-orders/replenishment/proposals/{rule_id}/move

Mirrors ``_router_pricelist.py`` (same registration pattern). The
replenishment routes are here because the rules and the shortage they
raise are this module's; the warehouse only carries out the move
(``warehouse_api.post_reserve_replenishment_async``).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    DocumentStateDTO,
    ReplenishmentAlertDTO,
    ReplenishmentProposalDTO,
)
from app.core.contracts.dtos import UserContextDTO
from app.core.deps import (
    get_async_db,
    get_current_user_context,
    require_org,
    require_permission,
)
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    map_service_errors,
)
from app.core.module_sdk import PaginatedResponse
from app.i18n.service import get_current_lang
from app.modules.warehouse.warehouse_api import warehouse_api

from . import reorder_service
from ._journal import (
    journal_reorder_rule_change,
    reorder_state,
)
from ._service_settings import UNSET
from ._update_canon import refuse_named_nulls
from .purchase_orders_api import purchase_orders_api
from .schemas import ReorderRuleCreate, ReorderRuleSchema, ReorderRuleUpdate


def _apply_capacity_side(
    rule: ReorderRuleSchema,
    capacity: Decimal | None,
) -> ReorderRuleSchema:
    """Stamp the shelf's answer onto the rule. A pair with no capacity
    entry reads clean — no limit is not an overflow."""
    rule.capacity_max_quantity = capacity
    rule.over_capacity = bool(capacity is not None and rule.max_quantity > capacity)
    return rule


async def _with_capacity_side(
    db: AsyncSession,
    org_id: UUID,
    rule: ReorderRuleSchema,
) -> ReorderRuleSchema:
    """Answer the shelf alongside the rule: when replenishment wants more
    of the product than the location holds, the warning rides on the
    response instead of the two numbers disagreeing in silence."""
    capacity = await warehouse_api.putaway_capacity_for_pair_async(
        db,
        org_id,
        location_id=rule.location_id,
        product_template_id=rule.product_template_id,
    )
    return _apply_capacity_side(rule, capacity)


def register_reorder_routes(router: APIRouter) -> None:
    @router.get(
        '/replenishment/alerts',
        response_model=PaginatedResponse[ReplenishmentAlertDTO],
    )
    async def replenishment_alerts(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> PaginatedResponse[ReplenishmentAlertDTO]:
        """Products below their reorder threshold."""
        alerts = await purchase_orders_api.get_replenishment_alerts_async(db, org_id)
        return PaginatedResponse.from_full_list(alerts, offset=offset, limit=limit)

    @router.get(
        '/replenishment/proposals/{rule_id}',
        response_model=ReplenishmentProposalDTO,
    )
    async def get_replenishment_proposal(
        rule_id: UUID,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> ReplenishmentProposalDTO:
        """The reserve move this rule's alert proposes, lines prepared."""
        proposal = await purchase_orders_api.get_replenishment_proposal_async(
            db, org_id, rule_id
        )
        if proposal is None:
            raise NotFoundException('reorder_rule', get_current_lang())
        return proposal

    @router.post(
        '/replenishment/proposals/{rule_id}/move',
        response_model=DocumentStateDTO,
        status_code=status.HTTP_201_CREATED,
        dependencies=[require_permission('warehouse:write')],
    )
    @map_service_errors
    async def post_replenishment_proposal(
        rule_id: UUID,
        scanned_code: str | None = None,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> DocumentStateDTO:
        """Carry the proposal off the reserve shelf: one INT document, posted.

        The proposal is re-derived from live stock — a task rendered minutes
        ago is a hint, not the quantity to move. A query parameter rather
        than a body, so the To do action can post an empty form when the
        organization does not ask for a shelf scan.
        """
        proposal = await purchase_orders_api.get_replenishment_proposal_async(
            db, org_id, rule_id
        )
        if proposal is None:
            raise NotFoundException('reorder_rule', get_current_lang())
        return await warehouse_api.post_reserve_replenishment_async(
            db, org_id, current_user.id, proposal, scanned_code=scanned_code
        )

    @router.post(
        '/reorder-rules',
        response_model=ReorderRuleSchema,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_reorder_rule(
        data: ReorderRuleCreate,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> ReorderRuleSchema:
        try:
            rule = await reorder_service.create_async(
                db,
                organization_id=org_id,
                product_template_id=data.product_template_id,
                storage_location_id=data.location_id,
                min_quantity=data.min_quantity,
                max_quantity=data.max_quantity,
                safety_stock=data.safety_stock,
                preferred_partner_id=data.preferred_partner_id,
                notes=data.notes,
            )
        except reorder_service.ReorderRuleAlreadyExistsError as exc:
            raise ConflictException(
                code='REORDER_RULE_EXISTS', message=str(exc)
            ) from exc
        await journal_reorder_rule_change(
            db,
            org_id,
            current_user.id,
            rule,
            before=None,
            after=reorder_state(rule),
        )
        return await _with_capacity_side(
            db, org_id, ReorderRuleSchema.model_validate(rule)
        )

    @router.get(
        '/reorder-rules',
        response_model=PaginatedResponse[ReorderRuleSchema],
    )
    async def list_reorder_rules(
        product_template_id: UUID | None = Query(default=None),
        location_id: UUID | None = Query(default=None),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> PaginatedResponse[ReorderRuleSchema]:
        rules = await reorder_service.list_for_org_async(
            db,
            org_id,
            product_template_id=product_template_id,
            storage_location_id=location_id,
        )
        total = len(rules)
        out = [
            ReorderRuleSchema.model_validate(r) for r in rules[offset : offset + limit]
        ]
        # One read for the whole page: the same shelf answer the save
        # responses carry, without a per-rule query behind the list.
        capacities = await warehouse_api.putaway_capacity_map_async(
            db,
            org_id,
            pairs=[(rule.location_id, rule.product_template_id) for rule in out],
        )
        page = [
            _apply_capacity_side(
                rule,
                capacities.get((rule.location_id, rule.product_template_id)),
            )
            for rule in out
        ]
        return PaginatedResponse.from_slice(page, offset, limit, total)

    @router.get(
        '/reorder-rules/{rule_id}',
        response_model=ReorderRuleSchema,
    )
    async def get_reorder_rule(
        rule_id: UUID,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> ReorderRuleSchema:
        rule = await reorder_service.get_async(db, org_id, rule_id)
        if rule is None:
            raise NotFoundException('reorder_rule', get_current_lang())
        return await _with_capacity_side(
            db, org_id, ReorderRuleSchema.model_validate(rule)
        )

    @router.patch(
        '/reorder-rules/{rule_id}',
        response_model=ReorderRuleSchema,
    )
    async def update_reorder_rule(
        rule_id: UUID,
        data: ReorderRuleUpdate,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> ReorderRuleSchema:
        # Presence decides, as on the settings and pricelist endpoints:
        # a named null clears a nullable column, an unnamed key leaves it
        # alone. The three thresholds back NOT NULL columns, so naming
        # one with null is refused by name (§2b) before the service runs.
        refuse_named_nulls(data, {'min_quantity', 'max_quantity', 'safety_stock'})
        # Read the rule as it is before the service writes to the same row.
        existing = await reorder_service.get_async(db, org_id, rule_id)
        before = reorder_state(existing) if existing else None
        rule = await reorder_service.update_async(
            db,
            organization_id=org_id,
            rule_id=rule_id,
            min_quantity=data.min_quantity,
            max_quantity=data.max_quantity,
            safety_stock=data.safety_stock,
            preferred_partner_id=(
                data.preferred_partner_id
                if 'preferred_partner_id' in data.model_fields_set
                else UNSET
            ),
            notes=data.notes if 'notes' in data.model_fields_set else UNSET,
        )
        if rule is None:
            raise NotFoundException('reorder_rule', get_current_lang())
        await journal_reorder_rule_change(
            db,
            org_id,
            current_user.id,
            rule,
            before=before,
            after=reorder_state(rule),
        )
        return await _with_capacity_side(
            db, org_id, ReorderRuleSchema.model_validate(rule)
        )

    @router.delete(
        '/reorder-rules/{rule_id}',
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_reorder_rule(
        rule_id: UUID,
        current_user: UserContextDTO = Depends(get_current_user_context),
        db: AsyncSession = Depends(get_async_db, scope='function'),
        org_id: UUID = Depends(require_org),
    ) -> None:
        existing = await reorder_service.get_async(db, org_id, rule_id)
        before = reorder_state(existing) if existing else None
        removed = await reorder_service.delete_async(db, org_id, rule_id)
        if not removed or existing is None or before is None:
            raise NotFoundException('reorder_rule', get_current_lang())
        await journal_reorder_rule_change(
            db, org_id, current_user.id, existing, before=before, after=None
        )
