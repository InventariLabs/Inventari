"""The journal entry for an act on a purchase order that is not its creation.

Create and confirm write their own entries where they happen. Everything
else that changes an order or says something about it — an edit, a cancel,
an e-mail to the supplier, a line import, the three approval acts — goes
through here, so the entries share one shape: an UPDATE on the order whose
``before``/``after`` name only what moved, beside the order's number and,
when the act is not a field change, a word for what happened.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.public_api import core_api
from app.core.settings_diff import changed_settings_snapshot, journal_config_change

from .models import PurchaseOrder


def _line_text(line: Any) -> str:
    """One line with everything an edit can set on it.

    Name, quantity and price come first, as they always read; the rest is
    appended only when the line has it, so a line changed in any one of its
    fields prints differently and the edit is not mistaken for no edit.
    """
    text = f'{line.name} × {line.quantity_ordered.normalize():f}'
    if line.unit_price is not None:
        text += f' @ {line.unit_price.normalize():f}'
    if line.tax_rate is not None:
        text += f' · tax {line.tax_rate.normalize():f}%'
    for label, value in (
        ('product', line.product_template_id),
        ('unit', line.uom_id),
        ('reorder rule', line.source_reorder_rule_id),
    ):
        if value is not None:
            text += f' · {label} {value}'
    if line.notes:
        text += f' · note: {line.notes}'
    return text


async def edit_state(
    db: AsyncSession, org_id: UUID, po: PurchaseOrder
) -> dict[str, Any]:
    """What an edit can move, as the journal will print it.

    The supplier is written with its name, read in the same transaction, so
    a partner renamed next week does not rewrite this entry.
    """
    partner = (
        await core_api.partners.get_async(db, org_id, po.partner_id)
        if po.partner_id
        else None
    )
    return {
        'number': po.number,
        'partner_id': po.partner_id,
        'partner_name': partner.name if partner else None,
        'scheduled_date': po.scheduled_date,
        'currency': po.currency,
        'notes': po.notes,
        'lines': [_line_text(line) for line in po.lines],
    }


async def journal_order_act(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID | None,
    po: PurchaseOrder,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    act: dict[str, Any] | None = None,
) -> None:
    """Write one UPDATE entry on *po* for an act in the caller's transaction.

    ``before`` and ``after`` hold the same keys read on both sides of the
    act; the entry carries only the keys whose value moved. ``act`` names an
    act that moves nothing on the order (an e-mail sent, a stage approved) —
    such an act is the fact, so it is written even when no field moved. An
    edit that changed nothing writes no entry: a journal records changes,
    not keystrokes.
    """
    before = before or {}
    after = after or {}
    # The same comparison every journalled configuration write asks: a number
    # as a number, an empty text as an unfilled one. No secret lives on an
    # order, so nothing is masked.
    moved = changed_settings_snapshot(before, after, frozenset())
    if moved is None and not act:
        return
    snapshot: dict[str, Any] = {'number': po.number, **(act or {})}
    if moved is not None:
        snapshot.update(moved)
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.PURCHASE_ORDER,
        target_id=po.id,
        snapshot=snapshot,
    )


def pricelist_state(entry: Any) -> dict[str, Any]:
    """A supplier's price as the journal prints it, the unit with its symbol."""
    return {
        'unit_price': entry.unit_price,
        'currency': entry.currency,
        'uom_id': entry.uom_id,
        'uom_symbol': entry.uom.symbol if entry.uom else None,
        'min_quantity': entry.min_quantity,
        'valid_from': entry.valid_from,
        'valid_to': entry.valid_to,
        'notes': entry.notes,
    }


def reorder_state(rule: Any) -> dict[str, Any]:
    """A reorder rule's thresholds and its preferred supplier, by name."""
    return {
        'min_quantity': rule.min_quantity,
        'max_quantity': rule.max_quantity,
        'safety_stock': rule.safety_stock,
        'preferred_partner_id': rule.preferred_partner_id,
        'preferred_partner_name': (
            rule.preferred_partner.name if rule.preferred_partner else None
        ),
        'notes': rule.notes,
    }


async def journal_pricelist_change(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID | None,
    entry: Any,
    *,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    """A price a supplier offers steers every later order: journalled.

    Supplier and product are the entry's identity, so they ride beside the
    price on every entry, with the names they have now.
    """
    await journal_config_change(
        db,
        org_id,
        user_id,
        module='purchase_orders',
        subject='pricelist',
        keys={
            'unit_price',
            'currency',
            'uom_id',
            'uom_symbol',
            'min_quantity',
            'valid_from',
            'valid_to',
            'notes',
        },
        before=before,
        after=after,
        context={
            'partner_id': entry.partner_id,
            'partner_name': entry.partner.name if entry.partner else None,
            'product_template_id': entry.product_template_id,
            'product_template_name': (
                entry.product_template.name if entry.product_template else None
            ),
        },
    )


async def journal_reorder_rule_change(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID | None,
    rule: Any,
    *,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    """A reorder rule decides what the next replenishment asks for: journalled.

    The shelf and the product are the rule's identity, so they ride beside
    the thresholds on every entry, with the names they have now.
    """
    await journal_config_change(
        db,
        org_id,
        user_id,
        module='purchase_orders',
        subject='reorder-rule',
        keys={
            'min_quantity',
            'max_quantity',
            'safety_stock',
            'preferred_partner_id',
            'preferred_partner_name',
            'notes',
        },
        before=before,
        after=after,
        context={
            'location_id': rule.storage_location_id,
            'location_name': rule.storage_location.name
            if rule.storage_location
            else None,
            'product_template_id': rule.product_template_id,
            'product_template_name': (
                rule.product_template.name if rule.product_template else None
            ),
        },
    )
