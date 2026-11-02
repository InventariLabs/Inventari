"""Convert a shopping list into a DRAFT Purchase Order.

Groups un-purchased items that carry a ``template_id`` into PO lines and
marks them purchased; items without a template are skipped and reported.
Cross-module access goes through ``purchase_orders_api`` (public API).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import (
    PurchaseOrderCreateInput,
    PurchaseOrderDTO,
    PurchaseOrderLineInput,
)
from app.core.exceptions import ServiceRejectionError
from app.core.public_api import core_api
from app.i18n import Language
from app.i18n.service import get_shopping_label
from app.modules.purchase_orders.purchase_orders_api import purchase_orders_api

from ._helpers import get_shopping_list_or_404
from .models import ShoppingListItem


async def convert_list_to_po_async(
    db: AsyncSession,
    list_id: UUID,
    org_id: UUID,
    user_id: UUID,
    *,
    supplier_id: UUID | None = None,
    lang: Language | None = None,
) -> tuple[PurchaseOrderDTO, int, list[str]]:
    """Create a DRAFT PO from the list's un-purchased, template-linked items.

    Returns (po, converted_count, skipped_item_names). Raises ValueError when
    the purchase_orders module is disabled, the partner is invalid, or no
    item qualifies for conversion.
    """
    shopping_list = await get_shopping_list_or_404(db, list_id, org_id, lang)

    org = await core_api.organizations.get_async(db, org_id)
    enabled = set(org.enabled_modules or []) if org else set()
    if enabled and 'purchase_orders' not in enabled:
        raise ServiceRejectionError(
            'modules_not_enabled', module_name='purchase_orders'
        )

    items = (
        await db.scalars(
            select(ShoppingListItem).where(
                ShoppingListItem.shopping_list_id == list_id,
                ShoppingListItem.is_purchased.is_(False),
            )
        )
    ).all()

    convertible = [i for i in items if i.template_id is not None]
    skipped_names = [i.name for i in items if i.template_id is None]
    if not convertible:
        raise ServiceRejectionError('shopping_list_nothing_to_convert')

    # Group by template: one PO line per template, summed quantities.
    by_template: dict[UUID, dict[str, Any]] = {}
    for item in convertible:
        if item.template_id is None:
            continue  # already filtered above; narrows the key type
        group = by_template.setdefault(
            item.template_id, {'name': item.name, 'quantity': 0, 'uom_id': None}
        )
        group['quantity'] += item.quantity or 1
        if group['uom_id'] is None:
            group['uom_id'] = item.uom_id

    po = await purchase_orders_api.create_purchase_order_async(
        db,
        org_id,
        PurchaseOrderCreateInput(
            partner_id=supplier_id,
            # The order's own note — editable there and printed on its PDF —
            # so it is written once, in the language of whoever converts.
            notes=get_shopping_label('po_note_from_list', lang).format(
                name=shopping_list.name
            ),
            lines=[
                PurchaseOrderLineInput(
                    product_template_id=template_id,
                    name=group['name'],
                    quantity_ordered=Decimal(group['quantity']),
                    uom_id=group['uom_id'],
                )
                for template_id, group in by_template.items()
            ],
        ),
        user_id,
    )

    now = datetime.now(UTC)
    for item in convertible:
        item.is_purchased = True
        item.purchased_at = now
        item.purchased_by = user_id
        # The order's number is a part the list composes in the reader's
        # language, beside whatever the item already said. A sentence
        # appended to ``notes`` was English in every language, and on a
        # meal-plan line, whose note the list composes from ``note_data``,
        # it never showed at all.
        item.note_data = {**(item.note_data or {}), 'converted_to_po': po.number}

    await db.flush()
    return po, len(convertible), skipped_names
