"""The item's own movement ledger.

The journal in ``services/audit_service.py`` answers "what was done to this
organization's records"; this one answers "what happened to this item".
Every quantity, location and lifecycle change lands here with its details —
document links, lot breakdowns, the no-op a caller asked for — whether or
not the act also rose to the organization journal.
"""

import uuid
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.posting_batch import current_batch
from app.models.item import Item
from app.models.item_history import ItemAction, ItemHistory

logger = get_logger(__name__)


async def log_async(
    db: AsyncSession,
    item_id: UUID,
    organization_id: UUID,
    user_id: UUID,
    action: str,
    changes: dict,
) -> None:
    """Create an ItemHistory record and flush (caller commits)."""
    entry = ItemHistory(
        item_id=item_id,
        organization_id=organization_id,
        user_id=user_id,
        action=action,
        changes=changes,
    )
    db.add(entry)
    await db.flush()


async def log_history_async(
    db: AsyncSession,
    item: Item,
    action: ItemAction,
    changes: dict,
    user_id: UUID | None = None,
    source_document_id: UUID | None = None,
) -> None:
    """Record an item history entry and flush (caller commits).

    Aligns with CoreAPI transaction semantics: write methods flush, never
    commit. The history entry becomes part of the caller's transaction.

    Takes the loaded ``Item``: callers always hold it, and the old
    signature issued an extra ``select(Item.organization_id)`` per write.
    """
    from fastapi.encoders import jsonable_encoder

    history = ItemHistory(
        item_id=item.id,
        organization_id=item.organization_id,
        action=action.value,
        changes=jsonable_encoder(changes),
        user_id=user_id,
        source_document_id=source_document_id,
    )
    batch = current_batch(db)
    if batch is not None:
        # Written with the rest of the posting's rows, as one set.
        history.id = uuid.uuid4()
        batch.add(history)
        return
    db.add(history)
    await db.flush()
