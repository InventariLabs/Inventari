# architecture: allow_direct_db_access
# reason: Shopping suggestions aggregate low-stock and recent-consumption analytics across items
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.public_api import core_api
from app.models import Item, ItemHistory
from app.models.item_history import CONSUMPTION_ACTIONS, DISPOSAL_ACTIONS
from app.services.items.low_stock import low_stock_template_ids

from .schemas import RestockForecastRow


async def get_shopping_suggestions(
    db: AsyncSession, organization_id: UUID
) -> list[RestockForecastRow]:
    storage_ids = (
        await core_api.locations.list_storage_ids_async(db, organization_id)
        if organization_id
        else []
    )
    if not storage_ids:
        return []

    suggestions: list[RestockForecastRow] = []

    # The same rule the dashboard tile and the list filter read, from the
    # same module: a threshold belongs to the product, so a product kept
    # in six places is one shortage, not six. Comparing it against each
    # record separately proposed buying the same flour six times over.
    low_stock_result = await db.execute(
        select(Item)
        .options(joinedload(Item.category))
        .where(
            Item.storage_location_id.in_(storage_ids),
            Item.is_deleted.is_(False),
            Item.template_id.in_(low_stock_template_ids(organization_id)),
        )
        .distinct(Item.template_id)
        .order_by(Item.template_id, Item.id)
    )
    low_stock_items = low_stock_result.unique().scalars().all()

    for item in low_stock_items:
        suggestions.append(
            RestockForecastRow(
                product_name=item.name,
                category_name=item.category.name if item.category else 'Other',
                category_code=item.category.code if item.category else None,
                avg_consumption_rate=0.0,
                days_since_last_purchase=0,
                urgency='high',
                estimated_days_until_needed=0,
            )
        )

    recent_since = await core_api.organizations.window_start_async(
        db, organization_id, 7
    )
    # Trusts the filter on purpose: a use and a disposal are the same thing to
    # a restock suggestion — stock left the shelf, so check the minimum — and
    # the row is read for nothing but the record it names.
    recent_result = await db.execute(
        select(ItemHistory)
        .where(
            ItemHistory.organization_id == organization_id,
            ItemHistory.action.in_(CONSUMPTION_ACTIONS + DISPOSAL_ACTIONS),
            ItemHistory.created_at >= recent_since,
        )
        .order_by(ItemHistory.created_at.desc())
        .limit(20)
    )
    recent_consumed = recent_result.scalars().all()

    consumed_product_names: set[str] = set()

    history_item_ids = [h.item_id for h in recent_consumed if h.item_id]
    items_by_id: dict[UUID, Item] = {}
    if history_item_ids:
        batch_result = await db.execute(
            select(Item)
            .options(joinedload(Item.category), joinedload(Item.template))
            .where(
                Item.id.in_(history_item_ids),
                Item.organization_id == organization_id,
                Item.is_deleted.is_(False),
            )
        )
        items_by_id = {item.id: item for item in batch_result.unique().scalars().all()}

    for history in recent_consumed:
        if history.changes and 'consumed_by' not in history.changes:
            history_item = items_by_id.get(history.item_id)
            threshold = (
                float(history_item.template.min_quantity)
                if history_item
                and history_item.template
                and history_item.template.min_quantity
                and history_item.template.min_quantity > 0
                else None
            )
            if (
                history_item
                and threshold is not None
                and history_item.quantity <= threshold
            ):
                if history_item.name not in consumed_product_names:
                    consumed_product_names.add(history_item.name)
                    suggestions.append(
                        RestockForecastRow(
                            product_name=history_item.name,
                            category_name=history_item.category.name
                            if history_item.category
                            else 'Other',
                            category_code=history_item.category.code
                            if history_item.category
                            else None,
                            avg_consumption_rate=0.0,
                            days_since_last_purchase=7,
                            urgency='medium',
                            estimated_days_until_needed=3,
                        )
                    )

    return suggestions[:20]
