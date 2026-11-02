"""ShoppingList CRUD operations.

All create/read/update/delete operations on ShoppingList aggregate.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.contracts import AuditAction, AuditTargetType
from app.core.db_utils import acquire_advisory_lock, paginate_async
from app.core.exceptions import ConflictException, NotFoundException
from app.core.public_api import core_api
from app.i18n import Language
from app.i18n.service import (
    get_current_lang,
    get_error_message,
    get_shopping_label,
)

from ._helpers import get_shopping_list_or_404
from .models import (
    ShoppingList,
    ShoppingListHistory,
    ShoppingListItem,
    ShoppingListStatus,
)
from .schemas import ShoppingListUpdate


async def create_shopping_list(
    db: AsyncSession,
    org_id: UUID,
    created_by: UUID,
    name: str | None,
    lang: Language | None,
) -> ShoppingList:
    await acquire_advisory_lock(db, f'shopping_list:create:{org_id}')
    list_name = name
    if not list_name:
        now = datetime.now(UTC)
        today_start = datetime.combine(now.date(), datetime.min.time()).replace(
            tzinfo=UTC
        )
        count_result = await db.execute(
            select(func.count(ShoppingList.id)).where(
                ShoppingList.organization_id == org_id,
                ShoppingList.created_at >= today_start,
            )
        )
        count_today = count_result.scalar() or 0
        month_label = get_shopping_label(f'month_{now.month}', lang)
        template = get_shopping_label('default_name_template', lang)
        base_name = template.format(day=now.day, month=month_label)
        list_name = f'{base_name} ({count_today + 1})' if count_today > 0 else base_name

    shopping_list = ShoppingList(
        organization_id=org_id,
        name=list_name,
        created_by=created_by,
    )
    db.add(shopping_list)
    # Flush-only (caller commits): cross-module callers (e.g. recipes)
    # compose create + add_items into one atomic operation — an inner
    # commit here would orphan an empty list when the follow-up writes
    # fail. Request-scoped callers are committed by get_async_db.
    await db.flush()
    await db.refresh(shopping_list)
    return shopping_list


async def list_shopping_lists(
    db: AsyncSession,
    org_id: UUID,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[ShoppingList], int]:
    stmt = select(ShoppingList).where(ShoppingList.organization_id == org_id)
    if active_only:
        # "Active" here means live, not deleted: a completed list is frozen
        # but still readable, while an archived one left every screen.
        stmt = stmt.where(ShoppingList.status != ShoppingListStatus.ARCHIVED.value)
    return await paginate_async(
        db,
        stmt.order_by(ShoppingList.created_at.desc(), ShoppingList.id),
        limit=limit,
        offset=skip,
    )


async def get_shopping_list_with_items(
    db: AsyncSession, list_id: UUID, org_id: UUID, lang: Language | None
) -> ShoppingList:
    result = await db.execute(
        select(ShoppingList)
        .options(
            selectinload(ShoppingList.items).selectinload(ShoppingListItem.category)
        )
        .where(
            ShoppingList.id == list_id,
            ShoppingList.organization_id == org_id,
        )
    )
    shopping_list = result.unique().scalars().first()
    if not shopping_list:
        raise NotFoundException('shopping_list', lang)
    return shopping_list


async def update_shopping_list_fields(
    db: AsyncSession, shopping_list: ShoppingList, data: ShoppingListUpdate
) -> ShoppingList:
    # enforce state-machine transitions; reject edits to terminal states
    if shopping_list.status in ('completed', 'archived') and not data.model_dump(
        exclude_unset=True
    ).keys() & {'status'}:
        raise ConflictException(
            code='SHOPPING_LIST_NOT_EDITABLE',
            message=get_error_message('shopping_list_not_editable', get_current_lang()),
        )

    update_payload = data.model_dump(exclude_unset=True)
    new_status = update_payload.get('status')
    now = datetime.now(UTC)
    if new_status == 'completed' and shopping_list.status != 'completed':
        update_payload['completed_at'] = now
    if new_status == 'archived' and shopping_list.status != 'archived':
        update_payload['archived_at'] = now

    for field, value in update_payload.items():
        setattr(shopping_list, field, value)
    await db.flush()
    await db.refresh(shopping_list)
    return shopping_list


async def delete_shopping_list_by_id(
    db: AsyncSession,
    list_id: UUID,
    org_id: UUID,
    lang: Language | None,
    user_id: UUID,
) -> None:
    """soft-delete with archive of purchased items.

    Hard-cascading delete destroyed the only place that recorded
    `purchased_at` / `purchased_by` / `estimated_price` totals. We now
    snapshot every purchased item to ``shopping_list_history`` before
    soft-deleting the list (``status='archived'``, ``archived_at=now``).

    The list does leave every screen, so the organization journal takes a
    row — ``SOFT_DELETE``, because the row itself stays, archived. See the
    rule in ``AuditTargetType``: a working note earns an entry for its
    deletion, not for its edits, and the name goes in the snapshot beside
    the id.
    """
    # Load the list with items eagerly so the for-loop below doesn't trigger
    # lazy IO in async context (MissingGreenlet).
    result = await db.execute(
        select(ShoppingList)
        .options(selectinload(ShoppingList.items))
        .where(
            ShoppingList.id == list_id,
            ShoppingList.organization_id == org_id,
        )
        .with_for_update()
    )
    shopping_list = result.scalars().first()
    if shopping_list is None:
        await get_shopping_list_or_404(db, list_id, org_id, lang)
        return  # unreachable — the helper above raises 404
    if shopping_list.status == ShoppingListStatus.ARCHIVED.value:
        # Already archived — idempotent no-op, and not an act: nothing
        # changed, so nothing is written down.
        return
    org_uuid = org_id if isinstance(org_id, UUID) else UUID(str(org_id))

    for item in shopping_list.items:
        if item.is_purchased:
            db.add(
                ShoppingListHistory(
                    organization_id=org_uuid,
                    original_list_id=shopping_list.id,
                    original_list_name=shopping_list.name,
                    item_name=item.name,
                    quantity=item.quantity,
                    estimated_price=item.estimated_price,
                    purchased_at=item.purchased_at,
                    purchased_by=item.purchased_by,
                )
            )

    shopping_list.status = 'archived'
    shopping_list.archived_at = datetime.now(UTC)
    # Flushed in the same transaction as the archive above, so a journal
    # that says the list went away and a list that went away cannot
    # disagree. The commit below is ours; ``log_action_async`` only flushes.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_uuid,
        user_id=user_id,
        action=AuditAction.SOFT_DELETE,
        target_type=AuditTargetType.SHOPPING_LIST,
        target_id=shopping_list.id,
        snapshot={'name': shopping_list.name},
    )
    await db.flush()
