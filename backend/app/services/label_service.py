import secrets
import string
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.contracts import UserContextDTO
from app.core.db_utils import acquire_advisory_lock, paginate_async
from app.core.exceptions import ServiceRejectionError
from app.core.logging import get_logger
from app.models.audit_log import AuditAction, AuditTargetType
from app.models.label_pool import LabelPool
from app.schemas.label_pool import LabelCodeItem, LabelPoolCreate
from app.services.audit_service import audit_value, log_action_async

logger = get_logger(__name__)

# Number of times generate_label_pool retries the whole batch when the
# short_code UNIQUE constraint fires (defense-in-depth — should be rare
# under the advisory lock, but covers edge cases like the transaction
# being killed between SELECT and INSERT by a different session).
LABEL_POOL_MAX_RETRIES = 5


async def generate_short_code_async(
    db: AsyncSession,
    prefix: str = 'STM',
    max_attempts: int = 100,
    organization_id: UUID | None = None,
) -> str:
    """Generates a short code unused by labels and locations.

    Both tables are unique per organization, so *organization_id* narrows the
    search to the tenant the code is for — without it one tenant's rows would
    keep shrinking every other tenant's code space. Omitting it falls back to
    a table-wide search, which is stricter than the constraints require and
    therefore always safe.
    """
    from app.models.storage_location import StorageLocation

    prefix = prefix.strip().replace('-', '').replace(' ', '').upper()
    for _ in range(max_attempts):
        code = ''.join(
            secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4)
        )
        short_code = f'{prefix}-{code}'

        label_query = select(LabelPool).where(LabelPool.short_code == short_code)
        storage_query = select(StorageLocation).where(
            StorageLocation.short_code == short_code
        )
        if organization_id is not None:
            label_query = label_query.where(
                LabelPool.organization_id == organization_id
            )
            storage_query = storage_query.where(
                StorageLocation.organization_id == organization_id
            )

        if not await db.scalar(label_query) and not await db.scalar(storage_query):
            return short_code

    raise Exception(
        f'Could not generate a unique code with prefix {prefix} after {max_attempts} attempts'
    )


async def _draw_unused_short_codes_async(
    db: AsyncSession,
    *,
    prefix: str,
    count: int,
    organization_id: UUID | None,
    max_attempts_per_code: int = 100,
) -> list[str]:
    """Draw *count* short codes free of both labels and locations.

    Two statements for the whole batch rather than two per label: the codes
    already taken under this prefix are read once, and the draw checks that set
    in memory. The caller holds the per-prefix advisory lock, so nothing else
    can take one of these between the read and the insert; the IntegrityError
    retry above still covers the case where it somehow does.
    """
    from app.models.storage_location import StorageLocation

    prefix = prefix.strip().replace('-', '').replace(' ', '').upper()
    like = f'{prefix}-%'

    label_codes = select(LabelPool.short_code).where(LabelPool.short_code.like(like))
    storage_codes = select(StorageLocation.short_code).where(
        StorageLocation.short_code.like(like)
    )
    if organization_id is not None:
        label_codes = label_codes.where(LabelPool.organization_id == organization_id)
        storage_codes = storage_codes.where(
            StorageLocation.organization_id == organization_id
        )

    taken = {code for code in (await db.scalars(label_codes)).all() if code}
    taken |= {code for code in (await db.scalars(storage_codes)).all() if code}

    drawn: list[str] = []
    for _ in range(count):
        for _attempt in range(max_attempts_per_code):
            body = ''.join(
                secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4)
            )
            short_code = f'{prefix}-{body}'
            if short_code not in taken:
                taken.add(short_code)
                drawn.append(short_code)
                break
        else:
            raise Exception(
                f'Could not generate a unique code with prefix {prefix} '
                f'after {max_attempts_per_code} attempts'
            )
    return drawn


def _with_assigned_item(labels: list[LabelPool]) -> list[LabelPool]:
    """Copy the assigned product's fields onto the label rows.

    Not persisted — read at query time, so a renamed product renames its
    label. ``assigned_item`` must already be loaded.
    """
    for label in labels:
        if label.assigned_item:
            label.is_item_deleted = label.assigned_item.is_deleted
            label.assigned_item_name = label.assigned_item.name
            label.assigned_item_quantity = label.assigned_item.quantity
            label.assigned_item_unit = (
                label.assigned_item.uom.symbol if label.assigned_item.uom else None
            )
            label.assigned_item_expiry = label.assigned_item.expiry_date
            # What the label points at: the category the item is filed
            # under, which a row about the label cannot know from the
            # label's own purpose — a generic label assigned to an asset
            # points at an asset, not at a product. The listing's
            # joinedload carries the category for exactly this.
            label.assigned_item_context_tag = (
                label.assigned_item.category.context_tag
                if label.assigned_item.category
                else None
            )
        else:
            label.is_item_deleted = False
    return labels


class _CaptionSource(Protocol):
    """As much of a label as the caption needs — a row or its DTO."""

    description: str | None
    assigned_item_name: str | None


def label_caption(label: _CaptionSource) -> str | None:
    """What a person reads off the shelf.

    A label's own description wins — somebody typed it for this label. With
    none, the assigned product supplies one: its name, and the month and
    year it expires where it has an expiry. The caption on the screenshots
    that started this ("minced beef 8.2026") was typed by hand into the
    description field while both halves of it were already on the record.
    """
    if label.description:
        return label.description
    name = getattr(label, 'assigned_item_name', None)
    if not name:
        return None
    expiry = getattr(label, 'assigned_item_expiry', None)
    if expiry is None:
        return str(name)
    return f'{name} {expiry.month}.{expiry.year}'


def _locked(stmt: Select, for_update: bool) -> Select:
    """*stmt* taking the row lock, read again past the session's copy.

    ``populate_existing`` because a locking select otherwise hands back the
    instance already in the session without its columns read again — the
    state from before the wait.
    """
    if not for_update:
        return stmt
    return stmt.with_for_update().execution_options(populate_existing=True)


async def _journal_binding_async(
    db: AsyncSession,
    label: LabelPool,
    *,
    product_name: str | None,
    before: UUID | None,
    after: UUID | None,
    user_id: UUID | None,
) -> None:
    """One entry for a label that changed the product it answers for.

    The product's name travels with it: the id alone says nothing to the
    reader, and a freed label is usually freed from a product since deleted.
    """
    if before == after:
        return
    await log_action_async(
        db,
        organization_id=label.organization_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.LABEL,
        target_id=label.id,
        snapshot={
            'short_code': label.short_code,
            'product_name': product_name,
            'before': {'item_id': audit_value(before)},
            'after': {'item_id': audit_value(after)},
        },
    )


class LabelService:
    @staticmethod
    async def generate_label_pool_async(
        db: AsyncSession, request: LabelPoolCreate, user: UserContextDTO
    ) -> list[LabelPool]:
        """Generate a pool of N unique labels.

        Concurrency: acquire pg_advisory_xact_lock keyed by (prefix) for the
        duration of the batch, so two parallel requests for the same prefix
        generate disjoint short_codes. The lock is released automatically at
        the caller's commit/rollback. The retry loop is a defense-in-depth
        measure for edge cases (e.g. lock-key collision across prefixes, or the
        rare intra-batch random collision); each attempt runs in a savepoint so
        a collision undoes only its own batch, never the caller's work.
        """
        last_exc: IntegrityError | None = None
        for _attempt in range(LABEL_POOL_MAX_RETRIES):
            # Serialize per-prefix code generation across concurrent requests.
            await acquire_advisory_lock(db, f'label_pool:{request.prefix}')

            labels = []
            try:
                async with db.begin_nested():
                    codes = await _draw_unused_short_codes_async(
                        db,
                        prefix=request.prefix,
                        count=request.count,
                        organization_id=user.organization_id,
                    )
                    for short_code in codes:
                        label = LabelPool(
                            short_code=short_code,
                            organization_id=user.organization_id,
                            created_by=user.id,
                            is_assigned=False,
                            label_type=request.label_type,
                            description=request.description,
                            target_storage_location_id=request.target_location_id,
                            context_tag=request.context_tag,
                        )
                        db.add(label)
                        labels.append(label)
            except IntegrityError as exc:
                last_exc = exc
                continue
            # One statement for the whole batch. Refreshing per row turned a
            # request for 500 labels into 500 more round trips.
            label_ids = [label.id for label in labels]
            if label_ids:
                reloaded = (
                    await db.scalars(
                        select(LabelPool).where(LabelPool.id.in_(label_ids))
                    )
                ).all()
                by_id = {row.id: row for row in reloaded}
                labels = [by_id[lid] for lid in label_ids if lid in by_id]
            return labels
        raise last_exc or RuntimeError(
            f'Could not generate {request.count} unique label(s) '
            f'after {LABEL_POOL_MAX_RETRIES} attempts'
        )

    @staticmethod
    async def create_from_codes_async(
        db: AsyncSession,
        codes: list[LabelCodeItem],
        user: UserContextDTO,
        *,
        label_type: str = 'GENERIC',
        context_tag: str | None = None,
    ) -> list[LabelPool]:
        """Create labels with explicit short_codes, scoped to the user's org.

        Raises ValueError on intra-request duplicates or short_codes already
        present in the org (the composite unique constraint is the final guard
        against races).
        """
        seen: set[str] = set()
        for entry in codes:
            if entry.short_code in seen:
                raise ServiceRejectionError(
                    'short_code_duplicate_in_request', short_code=entry.short_code
                )
            seen.add(entry.short_code)

        existing = (
            await db.scalars(
                select(LabelPool).where(
                    LabelPool.short_code.in_(seen),
                    LabelPool.organization_id == user.organization_id,
                )
            )
        ).all()
        if existing:
            taken = ', '.join(sorted(lbl.short_code for lbl in existing))
            raise ServiceRejectionError('short_codes_taken', codes=taken)

        labels = []
        for entry in codes:
            label = LabelPool(
                short_code=entry.short_code,
                organization_id=user.organization_id,
                created_by=user.id,
                is_assigned=False,
                label_type=label_type,
                description=entry.description,
                context_tag=context_tag,
            )
            db.add(label)
            labels.append(label)
        await db.flush()
        for label in labels:
            await db.refresh(label)
        return labels

    @staticmethod
    async def delete_label_async(
        db: AsyncSession, label: LabelPool, *, user_id: UUID | None = None
    ) -> None:
        label.is_assigned = False
        label.item_id = None
        await db.flush()

        await log_action_async(
            db,
            organization_id=label.organization_id,
            user_id=user_id,
            action=AuditAction.HARD_DELETE,
            target_type=AuditTargetType.LABEL,
            target_id=label.id,
            snapshot={'short_code': label.short_code, 'description': label.description},
        )

        await db.delete(label)
        await db.flush()

    @staticmethod
    async def unassign_label_async(
        db: AsyncSession, label: LabelPool, *, user_id: UUID | None = None
    ) -> LabelPool:
        # Keep item.label_code consistent: clearing the binding on the LabelPool
        # must also clear the cached FK on the Item, otherwise the Item keeps
        # pointing at a label that is no longer assigned to it.
        from app.models.item import Item

        bound_to = label.item_id
        item = None
        if bound_to:
            item = await db.scalar(select(Item).where(Item.id == bound_to))
            if item and item.label_code == label.short_code:
                item.label_code = None
        label.is_assigned = False
        label.item_id = None
        label.assigned_at = None
        await _journal_binding_async(
            db,
            label,
            product_name=item.name if item else None,
            before=bound_to,
            after=None,
            user_id=user_id,
        )
        await db.flush()
        await db.refresh(label)
        return label

    @staticmethod
    async def assign_to_existing_item_async(
        db: AsyncSession,
        label: LabelPool,
        item_id: UUID,
        *,
        user_id: UUID | None = None,
    ) -> LabelPool:
        # Free any label previously assigned to this item before binding the
        # new one, so the previous label does not become a permanent zombie
        # (is_assigned stays True, item_id points nowhere).
        from app.models.item import Item

        item = await db.scalar(select(Item).where(Item.id == item_id))
        if item and item.label_code and item.label_code != label.short_code:
            # Locked like the label itself: a concurrent bind may be freeing
            # it right now, and what it was bound to is journalled below.
            prev = await db.scalar(
                _locked(
                    select(LabelPool).where(
                        LabelPool.short_code == item.label_code,
                        LabelPool.organization_id == item.organization_id,
                    ),
                    True,
                )
            )
            if prev:
                freed_from = prev.item_id
                prev.is_assigned = False
                prev.item_id = None
                prev.assigned_at = None
                await _journal_binding_async(
                    db,
                    prev,
                    product_name=item.name,
                    before=freed_from,
                    after=None,
                    user_id=user_id,
                )
        bound_to = label.item_id
        label.item_id = item_id
        label.is_assigned = True
        label.assigned_at = datetime.now(UTC)
        if item:
            item.label_code = label.short_code
        await _journal_binding_async(
            db,
            label,
            product_name=item.name if item else None,
            before=bound_to,
            after=item_id,
            user_id=user_id,
        )
        await db.flush()
        await db.refresh(label)
        return label

    @staticmethod
    async def mark_as_printed_by_ids_async(
        db: AsyncSession, label_ids: list[UUID], organization_id: UUID
    ) -> None:
        if not label_ids:
            return
        now = datetime.now(UTC)
        result = await db.scalars(
            select(LabelPool).where(
                LabelPool.id.in_(label_ids),
                LabelPool.organization_id == organization_id,
            )
        )
        labels = result.all()
        for label in labels:
            label.printed_at = now
        await db.flush()

    @staticmethod
    async def get_by_id_async(
        db: AsyncSession,
        label_id: UUID,
        organization_id: UUID,
        *,
        for_update: bool = False,
    ):
        """The label, or ``None``; ``for_update`` as in ``get_by_short_code_async``."""
        return await db.scalar(
            _locked(
                select(LabelPool).where(
                    LabelPool.id == label_id,
                    LabelPool.organization_id == organization_id,
                ),
                for_update,
            )
        )

    @staticmethod
    async def get_by_short_code_async(
        db: AsyncSession,
        short_code: str,
        organization_id: UUID,
        *,
        for_update: bool = False,
    ):
        """The label, or ``None``; ``for_update`` locks the row first.

        A binding change locks the label before it reads the product it
        journals as ``before``, so a concurrent change is waited for and read
        rather than written over in the journal.
        """
        return await db.scalar(
            _locked(
                select(LabelPool).where(
                    LabelPool.short_code == short_code,
                    LabelPool.organization_id == organization_id,
                ),
                for_update,
            )
        )

    @staticmethod
    async def list_for_org_async(
        db: AsyncSession,
        organization_id: UUID,
        *,
        unassigned_only: bool = False,
        label_type: str | None = None,
    ) -> list[LabelPool]:
        query = select(LabelPool).where(LabelPool.organization_id == organization_id)
        if unassigned_only:
            query = query.where(LabelPool.is_assigned.is_(False))
        if label_type:
            query = query.where(LabelPool.label_type == label_type)

        result = await db.scalars(query.order_by(LabelPool.created_at.desc()))
        return list(result.unique().all())

    @staticmethod
    async def list_for_org_with_relations_async(
        db: AsyncSession,
        organization_id: UUID,
        *,
        unassigned_only: bool = False,
        label_type: str | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[LabelPool], int]:
        from sqlalchemy import func
        from sqlalchemy.sql.elements import ColumnElement

        from app.models.item import Item

        conditions: list[ColumnElement[bool]] = [
            LabelPool.organization_id == organization_id
        ]
        if unassigned_only:
            conditions.append(LabelPool.is_assigned.is_(False))
        if label_type:
            conditions.append(LabelPool.label_type == label_type)
        if status:
            if status == 'FREE':
                conditions.extend(
                    (
                        LabelPool.is_assigned.is_(False),
                        LabelPool.printed_at.is_(None),
                    )
                )
            elif status == 'PRINTED':
                conditions.extend(
                    (
                        LabelPool.is_assigned.is_(False),
                        LabelPool.printed_at.isnot(None),
                    )
                )
            elif status == 'ASSIGNED':
                conditions.extend(
                    (
                        LabelPool.is_assigned.is_(True),
                        LabelPool.assigned_item.has(Item.is_deleted.is_(False)),
                    )
                )
            elif status == 'ARCHIVED':
                conditions.extend(
                    (
                        LabelPool.is_assigned.is_(True),
                        LabelPool.assigned_item.has(Item.is_deleted.is_(True)),
                    )
                )

        query = (
            select(LabelPool)
            .options(joinedload(LabelPool.assigned_item).joinedload(Item.category))
            .where(*conditions)
            .order_by(LabelPool.created_at.desc())
        )
        if limit is not None:
            labels, total = await paginate_async(db, query, limit=limit, offset=offset)
        else:
            total = (
                await db.scalar(
                    select(func.count()).select_from(LabelPool).where(*conditions)
                )
            ) or 0
            result = await db.scalars(query)
            labels = list(result.unique().all())

        _with_assigned_item(labels)

        return labels, total or 0

    @staticmethod
    async def list_in_ids_async(
        db: AsyncSession, label_ids: list[UUID], organization_id: UUID
    ) -> list[LabelPool]:
        if not label_ids:
            return []
        result = await db.scalars(
            select(LabelPool)
            .options(joinedload(LabelPool.assigned_item))
            .where(
                LabelPool.id.in_(label_ids),
                LabelPool.organization_id == organization_id,
            )
        )
        return _with_assigned_item(list(result.unique().all()))

    @staticmethod
    async def list_by_short_codes_async(
        db: AsyncSession, short_codes: list[str], organization_id: UUID
    ) -> list[LabelPool]:
        if not short_codes:
            return []
        result = await db.scalars(
            select(LabelPool)
            .options(joinedload(LabelPool.assigned_item))
            .where(
                LabelPool.short_code.in_(short_codes),
                LabelPool.organization_id == organization_id,
            )
        )
        return _with_assigned_item(list(result.unique().all()))

    @staticmethod
    async def list_unprinted_unassigned_async(
        db: AsyncSession,
        organization_id: UUID,
        *,
        limit: int,
        exclude_ids: list[UUID] | None = None,
    ) -> list[LabelPool]:
        query = select(LabelPool).where(
            LabelPool.organization_id == organization_id,
            LabelPool.is_assigned.is_(False),
            LabelPool.printed_at.is_(None),
        )
        if exclude_ids:
            query = query.where(LabelPool.id.notin_(exclude_ids))
        query = query.limit(limit)
        result = await db.scalars(query)
        return list(result.unique().all())

    @staticmethod
    async def get_pool_stats_async(db: AsyncSession, organization_id: UUID) -> dict:
        from sqlalchemy import case, func

        counts = (
            await db.execute(
                select(
                    func.count(LabelPool.id).label('total'),
                    func.sum(case((LabelPool.is_assigned.is_(True), 1), else_=0)).label(
                        'assigned'
                    ),
                ).where(LabelPool.organization_id == organization_id)
            )
        ).one_or_none()

        total = (counts.total or 0) if counts else 0
        assigned = (counts.assigned or 0) if counts else 0
        return {
            'total': total,
            'assigned': assigned,
            'unassigned': total - assigned,
        }
