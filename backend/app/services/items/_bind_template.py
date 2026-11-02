"""Pointing a record at the product card it belongs to.

A record that predates its card (``template_id`` NULL) still moves goods
through documents, and the ledger — movements, cost layers — is keyed
by product. Binding the card is what lets such a record land in it. The
write is the link, and one thing more: a record that names no unit takes its
card's. The card's unit is the reference, the ledger books the record's moves
in it from here on, and a record left without one read "2 —" on the stock
table above a movement history saying "2 g". Quantity and identity stay the
record's own, and so does a unit it already has.

The link is not invisible, and it is not free of the rules the other doors
enforce. It goes through the same unit gate create and update use — a record
kept in one unit and a card kept in another is a choice somebody has to
confirm, and the confirmation reaches this door through a caller that has one
to ask: a document completion whose operator confirmed the choice on the
execution screen. Confirmed, the record takes the card's unit — restated, the
way create restates an entry, so the ledger that counts in the card's unit
never reads a record against itself — and the door leaves the same paper as
the others: an item-history row and an organization-journal entry naming the
card, so "what did this record become" is answerable from the record and from
the journal.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ServiceRejectionError
from app.models.audit_log import AuditAction, AuditTargetType
from app.models.item import Item
from app.models.item_history import ItemAction
from app.models.uom import Uom
from app.services._product_template_reads import get_template_for_org_async
from app.services.audit_service import audit_value, log_action_async

from ._unit_choice import (
    keep_in_card_unit_async,
    log_unit_chosen_over_template_async,
    refuse_unconfirmed_unit_difference_async,
)
from .history import log_history_async


async def _restate_record_into_card_unit_async(
    db: AsyncSession,
    item: Item,
    template: Any,
    *,
    confirmed: bool,
) -> dict[str, Any] | None:
    """Restate a confirmed unit difference into the card's unit, in place.

    The record's quantity and unit price are converted the way create
    restates an entry, and the unit becomes the card's — the ledger counts
    in the card's unit, so a record kept elsewhere would read against it.
    Returns the restatement's paper (the previous unit beside the numbers
    as they now stand), or None when there was no difference to restate.
    An unconfirmable difference is refused by name before anything is
    written: a number the stock cannot read is not one to confirm.
    """
    if (
        not confirmed
        or template.uom_id is None
        or item.uom_id is None
        or item.uom_id == template.uom_id
    ):
        return None
    restated: dict[str, Any] = {
        'previous_uom_id': item.uom_id,
        'quantity': item.quantity,
        'purchase_price': item.purchase_price,
        'uom_id': item.uom_id,
    }
    await keep_in_card_unit_async(db, restated, template, product_name=item.name)
    item.quantity = restated['quantity']
    item.purchase_price = restated['purchase_price']
    item.uom_id = restated['uom_id']
    return restated


async def bind_item_to_template_async(
    db: AsyncSession,
    item: Item,
    organization_id: UUID,
    template_id: UUID,
    *,
    user_id: UUID | None = None,
    source_document_id: UUID | None = None,
    unit_confirmed_over_template: bool = False,
) -> None:
    """Point *item* at the card *template_id*, with the paper that says so.

    The caller holds an open transaction and a record that predates its card;
    this writes the link, the record's history and the organization's journal
    in one breath, so a document that adopts a card cannot leave the shelves
    and the record telling different stories.

    A difference nobody confirmed is refused by name. One the operator
    confirmed on the way in (*unit_confirmed_over_template*) restates the
    record into the card's unit before anything else reads it — the opening
    balance, the delivery and the ledger conversions all ask the record's
    unit, and the ledger counts in the card's.
    """
    template = await get_template_for_org_async(db, organization_id, template_id)
    if template is None:
        raise ServiceRejectionError('product_template_not_found')
    if item.template_id == template.id:
        return

    # The card's unit is the reference (AGENTS.md §4). Unconfirmed, a record
    # kept in another unit is refused by name, with both units in the
    # reader's language. Confirmed, the difference was a choice — restated
    # here, before the door's own conversions and the opening balance read
    # the record, so every number below speaks the card's unit.
    entered_quantity = item.quantity
    previous_uom_id = item.uom_id
    await refuse_unconfirmed_unit_difference_async(
        db,
        template_uom_id=template.uom_id,
        chosen_uom_id=item.uom_id,
        product_name=item.name,
        confirmed=unit_confirmed_over_template,
    )
    restated = await _restate_record_into_card_unit_async(
        db, item, template, confirmed=unit_confirmed_over_template
    )

    previous_template_id = item.template_id
    previous_name: str | None = None
    if previous_template_id is not None:
        previous = await get_template_for_org_async(
            db, organization_id, previous_template_id
        )
        previous_name = previous.name if previous is not None else None

    old: dict[str, object] = {'template_id': audit_value(previous_template_id)}
    new: dict[str, object] = {'template_id': audit_value(template.id)}
    before: dict[str, object] = {'template_id': previous_name}
    after: dict[str, object] = {'template_id': template.name}
    fields = ['template_id']
    # The record joins the card's group on its shelf, whose anchor the
    # record's foreign key names; the lock creates it and holds both groups.
    from app.services._stock_quant_ops import lock_stock_async

    keys = [(template.id, item.storage_location_id)]
    if previous_template_id is not None:
        keys.append((previous_template_id, item.storage_location_id))
    await lock_stock_async(db, organization_id, keys=keys)
    item.template_id = template.id
    if item.uom_id is None and template.uom_id is not None:
        unit = await db.get(Uom, template.uom_id)
        old['uom_id'] = None
        new['uom_id'] = audit_value(template.uom_id)
        before['uom_id'] = None
        # Read by its symbol, the word the product screen prints.
        after['uom_id'] = unit.symbol if unit is not None else None
        fields.append('uom_id')
        item.uom_id = template.uom_id
    if restated is not None:
        # The restatement is a move of the unit column like the take above:
        # the row names what the record was kept in and what it takes now,
        # so the history reads as one story and not as a silent relabel.
        previous_uom = await db.get(Uom, previous_uom_id)
        unit = await db.get(Uom, template.uom_id)
        old['uom_id'] = audit_value(previous_uom_id)
        new['uom_id'] = audit_value(template.uom_id)
        before['uom_id'] = previous_uom.symbol if previous_uom else None
        after['uom_id'] = unit.symbol if unit else None
        fields.append('uom_id')
    await db.flush()

    await log_history_async(
        db,
        item,
        ItemAction.UPDATED,
        {'old': old, 'new': new},
        user_id=user_id,
        source_document_id=source_document_id,
    )
    await log_action_async(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.ITEM,
        target_id=item.id,
        snapshot={
            'name': item.name,
            'before': before,
            'after': after,
            'fields': fields,
        },
    )
    if restated is not None:
        # The same paper create leaves for a confirmed entry: the row says
        # what was held, in what unit, and what the record keeps now.
        await log_unit_chosen_over_template_async(
            db,
            item,
            ItemAction.UPDATED,
            template_uom_id=template.uom_id,
            chosen_uom_id=previous_uom_id,
            entered_quantity=entered_quantity,
            user_id=user_id,
        )
