from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select

from app.core.context import ModuleContext
from app.core.interceptors import InterceptorError, StorageInterceptor
from app.i18n.service import get_current_lang, get_error_message


class ProductionOrderStorageGuard(StorageInterceptor):
    """Veto deletion of storage locations used by production orders.

       ``ProductionOrder.output_storage_location_id`` and
       ``ProductionOrderLine.source_storage_location_id`` are RESTRICT FKs,
       so deleting such a location fails at the database level with a raw
       constraint violation. Guard it here so the API answers with a domain
    error instead of a misleading "stock movements" message.
    """

    priority = 40

    async def before_delete(self, storage_id: UUID, context: ModuleContext) -> None:
        from app.modules.maker.models import ProductionOrder, ProductionOrderLine

        if not context.organization_id:
            return

        db = context._db
        if db is None:
            return

        order_count = await db.scalar(
            select(func.count())
            .select_from(ProductionOrder)
            .where(
                ProductionOrder.organization_id == context.organization_id,
                ProductionOrder.output_storage_location_id == storage_id,
            )
        )
        line_count = await db.scalar(
            select(func.count())
            .select_from(ProductionOrderLine)
            .join(
                ProductionOrder,
                ProductionOrderLine.production_order_id == ProductionOrder.id,
            )
            .where(
                ProductionOrder.organization_id == context.organization_id,
                ProductionOrderLine.source_storage_location_id == storage_id,
            )
        )

        if not order_count and not line_count:
            return

        raise InterceptorError(
            get_error_message(
                'storage_delete_blocked_by_production_orders', get_current_lang()
            ),
            error_code='STORAGE_HAS_PRODUCTION_ORDERS',
            details={
                'production_orders': order_count,
                'production_order_lines': line_count,
            },
        )
