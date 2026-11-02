from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.context import ModuleContext
from app.core.interceptors import InterceptorError, ItemInterceptor
from app.i18n.service import get_current_lang, get_error_message


class DocumentsPurgeBlocker(ItemInterceptor):
    """Veto purges of items linked to posted documents or closed periods.

    ``DocumentLine.item_id`` is ``SET NULL`` on item deletion, so
       purging an item silently detaches it from posted documents, and the
       CASCADE-wiped history cannot restore the link. This interceptor blocks
       the purge with a structured list of blockers — the router surfaces it
       as HTTP 409 with ``details.blocks`` (type + count + ids).
    """

    priority = 40

    async def before_create(
        self, data: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        return data

    async def before_update(
        self, item_id: UUID, changes: dict[str, Any], context: ModuleContext
    ) -> dict[str, Any]:
        return changes

    async def before_purge(self, item_id: UUID, context: ModuleContext) -> None:
        from app.modules.warehouse.inventory_period_service import period_is_closed
        from app.modules.warehouse.models import (
            Document,
            DocumentLine,
            DocumentStatus,
            InventoryPeriod,
        )

        if not context.organization_id:
            return

        db = context._db
        if db is None:
            return

        posted_statuses = (
            DocumentStatus.CONFIRMED.value,
            DocumentStatus.COMPLETED.value,
        )

        rows = (
            await db.execute(
                select(
                    Document.id,
                    Document.scheduled_date,
                    Document.created_at,
                )
                .select_from(DocumentLine)
                .join(Document, DocumentLine.document_id == Document.id)
                .where(
                    DocumentLine.item_id == item_id,
                    Document.organization_id == context.organization_id,
                    Document.status.in_(posted_statuses),
                )
            )
        ).all()

        if not rows:
            return

        closed_periods = (
            await db.scalars(
                select(InventoryPeriod).where(
                    InventoryPeriod.organization_id == context.organization_id,
                    InventoryPeriod.closed_at.isnot(None),
                )
            )
        ).all()
        # ``closed_at`` records the last closure and survives a reopening, so
        # the current state comes from comparing it with ``reopened_at``.
        closed_months = {
            (p.year, p.month) for p in closed_periods if period_is_closed(p)
        }

        posted_doc_ids: set[UUID] = set()
        closed_doc_ids: set[UUID] = set()
        for doc_id, scheduled_date, created_at in rows:
            doc_date = scheduled_date or created_at.date()
            if (doc_date.year, doc_date.month) in closed_months:
                closed_doc_ids.add(doc_id)
            else:
                posted_doc_ids.add(doc_id)

        blocks: list[dict[str, Any]] = []
        if posted_doc_ids:
            blocks.append(
                {
                    'type': 'posted_document_lines',
                    'count': len(posted_doc_ids),
                    'ids': [str(i) for i in sorted(posted_doc_ids, key=str)],
                }
            )
        if closed_doc_ids:
            blocks.append(
                {
                    'type': 'closed_period_movements',
                    'count': len(closed_doc_ids),
                    'ids': [str(i) for i in sorted(closed_doc_ids, key=str)],
                }
            )

        raise InterceptorError(
            get_error_message('purge_blocked_by_audit_links', get_current_lang()),
            error_code='PURGE_BLOCKED_DOCUMENTS',
            details={'blocks': blocks},
        )
