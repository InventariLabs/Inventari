from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.context import ModuleContext
from app.core.interceptors import InterceptorError, ItemInterceptor
from app.i18n.service import get_current_lang, get_error_message


class StockTakesPurgeBlocker(ItemInterceptor):
    """Veto purges of items that appear on a stock-take line.

    ``StockTakeItem.item_id`` has ``ondelete='CASCADE'``, so purging
       a counted item silently destroys the counting evidence. The interceptor
       blocks the purge with a structured blocker list; the FK migration
       ``002`` switches the constraint to ``SET NULL`` as defense-in-depth for
       deployments where this module is disabled (no interceptor, but the rows
       still survive with their denormalized ``item_name``).
    """

    priority = 50

    async def before_create(
        self, data: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        return data

    async def before_update(
        self, item_id: UUID, changes: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        return changes

    async def before_purge(self, item_id: UUID, context: ModuleContext) -> None:
        from app.modules.stock_takes.models import StockTake, StockTakeItem

        if not context.organization_id:
            return

        db = context._db
        if db is None:
            return

        take_ids = (
            await db.scalars(
                select(StockTake.id)
                .select_from(StockTakeItem)
                .join(StockTake, StockTakeItem.stock_take_id == StockTake.id)
                .where(
                    StockTakeItem.item_id == item_id,
                    StockTake.organization_id == context.organization_id,
                )
                .distinct()
            )
        ).all()

        if not take_ids:
            return

        raise InterceptorError(
            get_error_message('purge_blocked_by_audit_links', get_current_lang()),
            error_code='PURGE_BLOCKED_STOCK_TAKES',
            details={
                'blocks': [
                    {
                        'type': 'stock_take_items',
                        'count': len(take_ids),
                        'ids': [str(i) for i in sorted(take_ids, key=str)],
                    }
                ]
            },
        )
