# architecture: allow_direct_db_access
# reason: Complex multi-join GROUP BY analytics for shopping suggestions cannot be expressed through CoreAPI
"""Async shopping suggestion generation — select() + GROUP BY analytics."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import String, func, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.i18n.service import get_current_lang, get_shopping_label
from app.models.item import Item
from app.models.item_history import CONSUMPTION_ACTIONS, DISPOSAL_ACTIONS, ItemHistory
from app.models.product_template import ProductTemplate
from app.models.storage_location import StorageLocation
from app.models.uom import Uom
from app.services.items.low_stock import low_stock_template_ids

T = TypeVar('T')


class ShoppingSuggestion:
    def __init__(
        self,
        name: str,
        item_id: UUID | None = None,
        template_id: UUID | None = None,
        category_id: UUID | None = None,
        quantity: int = 1,
        uom_id: UUID | None = None,
        unit: str | None = None,
        source: str = 'auto_low_stock',
        priority: int = 0,
        estimated_price: Decimal | None = None,
        notes: str | None = None,
    ):
        self.item_id = item_id
        #: The product template this proposal is about, where the source has
        #: one. The low-stock and consumption sources group by template and
        #: leave ``item_id`` null, and a template's name is not unique in an
        #: organization — without this, two products sharing a name are one
        #: row to every reader downstream (the modal's selection by row, the
        #: duplicate filter by name).
        self.template_id = template_id
        self.category_id = category_id
        self.name = name
        self.quantity = quantity
        self.uom_id = uom_id
        self.unit = unit
        self.source = source
        self.priority = priority
        self.estimated_price = estimated_price
        self.notes = notes

    def to_dict(self) -> dict[str, Any]:
        return {
            'item_id': self.item_id,
            'template_id': self.template_id,
            'category_id': self.category_id,
            'name': self.name,
            'quantity': self.quantity,
            'uom_id': self.uom_id,
            'unit': self.unit,
            'source': self.source,
            'priority': self.priority,
            'estimated_price': self.estimated_price,
            'notes': self.notes,
        }


async def generate_suggestions(
    db: AsyncSession,
    organization_id: UUID,
    include_low_stock: bool = True,
    include_frequent: bool = True,
    include_expiring: bool = True,
    min_consumption_count: int = 3,
    days_for_expiring: int = 7,
) -> list[ShoppingSuggestion]:
    suggestions: list[ShoppingSuggestion] = []

    if include_low_stock:
        # The rule is one, and it is not written here: the tile, the list
        # filter, the statistics screen and this engine all read
        # `low_stock_template_ids`. This query only decorates its answer
        # with the name and unit a suggestion needs.
        low_stock_ids = low_stock_template_ids(organization_id).subquery()
        category_id = (
            select(func.max(func.cast(Item.category_id, String)))
            .where(
                Item.organization_id == organization_id,
                Item.template_id == ProductTemplate.id,
                Item.is_deleted.is_(False),
            )
            .correlate(ProductTemplate)
            .scalar_subquery()
        )
        result = await db.execute(
            select(
                ProductTemplate.id,
                ProductTemplate.name,
                Uom.id.label('uom_id'),
                Uom.symbol.label('unit'),
                func.cast(category_id, PG_UUID).label('category_id'),
            )
            .join(low_stock_ids, low_stock_ids.c.id == ProductTemplate.id)
            .outerjoin(Uom, ProductTemplate.uom_id == Uom.id)
            .where(ProductTemplate.organization_id == organization_id)
            .order_by(ProductTemplate.name, ProductTemplate.id)
        )

        for (
            t_id,
            t_name,
            t_uom_id,
            t_unit,
            t_cat,
        ) in result.all():
            suggestions.append(
                ShoppingSuggestion(
                    name=t_name,
                    item_id=None,
                    template_id=t_id,
                    category_id=t_cat,
                    quantity=1,
                    uom_id=t_uom_id,
                    unit=t_unit,
                    source='auto_low_stock',
                    priority=1,
                )
            )

    if include_frequent:
        thirty_days_ago = date.today() - timedelta(days=30)

        frequent_result = await db.execute(
            select(
                ItemHistory.item_id,
                func.count(ItemHistory.id).label('consumption_count'),
            )
            .join(Item)
            .join(StorageLocation)
            .where(
                StorageLocation.organization_id == organization_id,
                ItemHistory.action.in_(CONSUMPTION_ACTIONS + DISPOSAL_ACTIONS),
                ItemHistory.created_at >= thirty_days_ago,
                Item.template_id.isnot(None),
            )
            .group_by(ItemHistory.item_id)
            .having(func.count(ItemHistory.id) >= min_consumption_count)
        )

        for item_id, count in frequent_result.all():
            current_result = await db.execute(
                select(Item).where(
                    Item.organization_id == organization_id,
                    Item.id == item_id,
                    Item.is_deleted.is_(False),
                )
            )
            current_item = current_result.scalars().first()

            if not current_item or current_item.quantity <= 0:
                source_result = await db.execute(
                    select(Item)
                    .join(ProductTemplate, Item.template_id == ProductTemplate.id)
                    .outerjoin(Uom, ProductTemplate.uom_id == Uom.id)
                    .where(
                        Item.organization_id == organization_id,
                        Item.id == item_id,
                    )
                    .order_by(Item.created_at.desc())
                )
                source_item = current_item or source_result.scalars().first()

                if source_item:
                    unit_symbol = (
                        source_item.template.uom.symbol
                        if (source_item.template and source_item.template.uom)
                        else None
                    )
                    uom_id = (
                        source_item.template.uom_id
                        if source_item.template
                        else source_item.uom_id
                    )

                    suggestions.append(
                        ShoppingSuggestion(
                            name=source_item.name,
                            item_id=None,
                            template_id=source_item.template_id,
                            category_id=source_item.category_id,
                            quantity=1,
                            uom_id=uom_id,
                            unit=unit_symbol,
                            source='auto_consumption',
                            priority=0,
                            notes=get_shopping_label(
                                'suggestion_frequently_consumed', get_current_lang()
                            ).format(count=count),
                        )
                    )

    if include_expiring:
        lang = get_current_lang()
        expiring_threshold = date.today() + timedelta(days=days_for_expiring)

        expiring_result = await db.execute(
            select(Item)
            .join(StorageLocation)
            .where(
                StorageLocation.organization_id == organization_id,
                StorageLocation.usage == 'internal',
                Item.is_deleted.is_(False),
                Item.effective_expiry_date.isnot(None),
                Item.effective_expiry_date <= expiring_threshold,
            )
        )

        for item in expiring_result.scalars().all():
            days_left = (
                (item.effective_expiry_date - date.today()).days
                if item.effective_expiry_date
                else 0
            )
            # A thing already past its date is not "expiring in minus forty-nine
            # days" — it has gone off, and the reason it is on a shopping list is
            # a different one from "running out soon".
            if days_left < 0:
                label = get_shopping_label('suggestion_expired_days_ago', lang).format(
                    days=abs(days_left)
                )
                source = 'auto_expired'
            elif days_left == 0:
                label = get_shopping_label('suggestion_expires_today', lang)
                source = 'auto_expiring'
            else:
                label = get_shopping_label('suggestion_expires_in_days', lang).format(
                    days=days_left
                )
                source = 'auto_expiring'
            suggestions.append(
                ShoppingSuggestion(
                    name=item.name,
                    item_id=item.id,
                    category_id=item.category_id,
                    quantity=1,
                    unit=item.uom.symbol if item.uom else None,
                    uom_id=item.uom_id,
                    source=source,
                    priority=2,
                    notes=label,
                )
            )

    return suggestions


def filter_duplicate_suggestions(
    suggestions: list[ShoppingSuggestion],
    existing_items: list[dict[str, Any]],
) -> list[ShoppingSuggestion]:
    """Remove suggestions already present in the list (not yet purchased)."""
    existing_names = {
        item['name'].lower() for item in existing_items if not item['is_purchased']
    }
    return [s for s in suggestions if s.name.lower() not in existing_names]
