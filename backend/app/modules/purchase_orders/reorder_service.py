# architecture: allow_direct_db_access
# reason: eager-load ProductTemplate.uom for the response schema; CoreAPI has no relationship-loading API.
# module_writes: ReorderRule (module-local table)
"""Reorder rule service — CRUD + replenishment queries.

All functions are async and use ``db.flush()`` only (no commit) for
writes — the caller commits.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ServiceRejectionError
from app.models.product_template import ProductTemplate
from app.modules.purchase_orders._service_settings import UNSET, _Unset
from app.modules.purchase_orders.models import ReorderRule


class ReorderRuleAlreadyExistsError(Exception):
    """Raised when a duplicate ``(org, product, location)`` tuple would
    be inserted. The ``uq_po_reorder_rules_org_product_loc`` DB-level
    constraint still fires (defense in depth); this exception is the
    service-layer translation that the router maps to HTTP 409.

    Same pattern as :class:`ConnectionStillBoundError` in the AI
    Connections API — never let a raw ``sqlalchemy.exc.IntegrityError``
    bubble to the router.
    """


async def create_async(
    db: AsyncSession,
    *,
    organization_id: UUID,
    product_template_id: UUID,
    storage_location_id: UUID,
    min_quantity: Decimal = Decimal('0'),
    max_quantity: Decimal,
    safety_stock: Decimal = Decimal('0'),
    preferred_partner_id: UUID | None = None,
    notes: str | None = None,
) -> ReorderRule:
    """Create a new reorder rule.

    Raises:
        ValueError: on invalid input (max<min, negative stock).
        ReorderRuleAlreadyExistsError: when another rule already covers
            the same (organization, product, location) tuple. The DB-
            level ``uq_po_reorder_rules_org_product_loc`` constraint is
            the source of truth; we catch it and translate.
    """
    if max_quantity < min_quantity:
        raise ServiceRejectionError(
            'reorder_max_below_min',
            max_quantity=max_quantity,
            min_quantity=min_quantity,
        )
    if safety_stock < 0:
        raise ServiceRejectionError(
            'reorder_safety_stock_negative', safety_stock=safety_stock
        )
    if min_quantity < 0:
        raise ServiceRejectionError(
            'reorder_min_quantity_negative', min_quantity=min_quantity
        )

    rule = ReorderRule(
        organization_id=organization_id,
        product_template_id=product_template_id,
        storage_location_id=storage_location_id,
        min_quantity=min_quantity,
        max_quantity=max_quantity,
        safety_stock=safety_stock,
        preferred_partner_id=preferred_partner_id,
        notes=notes,
    )
    try:
        # A savepoint takes back only the refused INSERT: the caller's earlier
        # writes stay, and the session stays usable for what it does next.
        async with db.begin_nested():
            db.add(rule)
            await db.flush()
    except IntegrityError as e:
        raise ReorderRuleAlreadyExistsError(
            f'A reorder rule already exists for organization '
            f'{organization_id}, product {product_template_id}, '
            f'location {storage_location_id}.'
        ) from e
    await db.refresh(rule)
    loaded = await _load_rule_with_uom(db, rule.id, rule.organization_id)
    assert loaded is not None
    return loaded


async def _load_rule_with_uom(
    db: AsyncSession, rule_id: UUID, organization_id: UUID
) -> ReorderRule | None:
    """Re-read a rule with its unit eagerly loaded, scoped to its owner.

    The organization is required. It used to default to None, which read the
    rule by bare id -- fine for the two internal callers that had just
    written the row, and a cross-org read for anyone who copied the shape.
    """
    stmt = (
        select(ReorderRule)
        .options(
            selectinload(ReorderRule.product_template).selectinload(ProductTemplate.uom)
        )
        .where(
            ReorderRule.id == rule_id,
            ReorderRule.organization_id == organization_id,
        )
    )
    result: ReorderRule | None = await db.scalar(stmt)
    return result


async def get_async(
    db: AsyncSession,
    organization_id: UUID,
    rule_id: UUID,
) -> ReorderRule | None:
    return await _load_rule_with_uom(db, rule_id, organization_id)


async def list_for_org_async(
    db: AsyncSession,
    organization_id: UUID,
    *,
    product_template_id: UUID | None = None,
    storage_location_id: UUID | None = None,
) -> list[ReorderRule]:
    stmt = (
        select(ReorderRule)
        .options(
            selectinload(ReorderRule.product_template).selectinload(ProductTemplate.uom)
        )
        .where(ReorderRule.organization_id == organization_id)
    )
    if product_template_id is not None:
        stmt = stmt.where(ReorderRule.product_template_id == product_template_id)
    if storage_location_id is not None:
        stmt = stmt.where(ReorderRule.storage_location_id == storage_location_id)
    stmt = stmt.order_by(
        ReorderRule.product_template_id,
        ReorderRule.storage_location_id,
        ReorderRule.id,
    )
    return list((await db.scalars(stmt)).all())


async def update_async(
    db: AsyncSession,
    *,
    organization_id: UUID,
    rule_id: UUID,
    min_quantity: Decimal | None = None,
    max_quantity: Decimal | None = None,
    safety_stock: Decimal | None = None,
    preferred_partner_id: UUID | None | _Unset = UNSET,
    notes: str | None | _Unset = UNSET,
) -> ReorderRule | None:
    """Patch a rule; the nullable columns answer three ways.

    preferred_partner_id and notes are clearable: UNSET (the payload did
    not name the key) leaves the column alone, an explicit ``None``
    detaches the supplier / empties the note, a value sets it. Once a
    preferred supplier was chosen there was no way back to "any supplier".
    """
    rule = await get_async(db, organization_id, rule_id)
    if rule is None:
        return None

    if min_quantity is not None:
        rule.min_quantity = min_quantity
    if max_quantity is not None:
        rule.max_quantity = max_quantity
    if safety_stock is not None:
        rule.safety_stock = safety_stock
    if not isinstance(preferred_partner_id, _Unset):
        rule.preferred_partner_id = preferred_partner_id
    if not isinstance(notes, _Unset):
        rule.notes = notes

    new_min = rule.min_quantity
    new_max = rule.max_quantity
    if new_max < new_min:
        raise ServiceRejectionError(
            'reorder_max_below_min', max_quantity=new_max, min_quantity=new_min
        )
    if rule.safety_stock < 0:
        raise ServiceRejectionError(
            'reorder_safety_stock_negative', safety_stock=rule.safety_stock
        )

    await db.flush()
    await db.refresh(rule)
    loaded = await _load_rule_with_uom(db, rule.id, rule.organization_id)
    if loaded is None:
        return None
    return loaded


async def delete_async(
    db: AsyncSession,
    organization_id: UUID,
    rule_id: UUID,
) -> bool:
    rule = await get_async(db, organization_id, rule_id)
    if rule is None:
        return False
    await db.delete(rule)
    await db.flush()
    return True
