from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import ItemHistoryDTO
from app.core.public_api._access import reads, writes
from app.services.items import log_async as log_item_history_async


class CoreItemHistoryAPI:
    """Public Core API for item history write access."""

    @writes
    async def log_async(
        self,
        db: AsyncSession,
        item_id: UUID,
        organization_id: UUID,
        user_id: UUID,
        action: str,
        changes: dict[str, Any],
    ) -> None:
        """Create an ItemHistory record. Calls db.flush() — caller commits."""
        await log_item_history_async(
            db,
            item_id=item_id,
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            changes=changes,
        )

    @reads
    async def list_for_item_async(
        self,
        db: AsyncSession,
        item_id: UUID,
        organization_id: UUID,
        *,
        limit: int = 50,
        actions: Sequence[str] | None = None,
    ) -> list[ItemHistoryDTO]:
        """Newest-first history of one item, as the entry DTO.

        ``actions`` narrows the query before ``limit`` cuts, so a caller
        asking for one kind of row gets ``limit`` of those.

        Read counterpart of :meth:`log_async`: a module that wants what the
        register already knows asks here rather than reaching into Core's
        services directly."""
        from app.services.item_history_service import list_for_item_async

        rows = await list_for_item_async(
            db, item_id, organization_id, limit=limit, actions=actions
        )
        return [ItemHistoryDTO.model_validate(row) for row in rows]
