"""Service blocks and buffer rules: time an asset cannot be booked, and why."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType
from app.core.db_utils import acquire_advisory_lock, paginate_async
from app.core.module_sdk import (
    NotFoundException,
    ServiceRejectionError,
    get_current_lang,
)
from app.core.public_api import core_api
from app.modules.equipment.equipment_api import EquipmentAssetDTO, equipment_api

from ._availability import displaced_bookings, load_world
from .exceptions import RentalConflictError
from .models import RentalBlock, RentalBufferRule
from .schemas import (
    BlockCreate,
    BlockSchema,
    BlockUpdate,
    BufferRuleIn,
    BufferRuleSchema,
)


def _now() -> datetime:
    return datetime.now(UTC)


async def _lock_asset_and_model(
    db: AsyncSession, org_id: UUID, asset: EquipmentAssetDTO
) -> None:
    """Hold the unit and the model whose promise the unit can take a part of.

    Acquired in the same order ``service._lock`` uses: the item first, then
    the model.
    """
    await acquire_advisory_lock(db, f'rentals:item:{org_id}:{asset.id}')
    if asset.model:
        await acquire_advisory_lock(db, f'rentals:model:{org_id}:{asset.model}')


async def _assets_map(db: AsyncSession, org_id: UUID) -> dict[UUID, EquipmentAssetDTO]:
    assets = await equipment_api.list_bookable_assets_async(
        db, org_id, include_retired=True
    )
    return {asset.id: asset for asset in assets}


async def _buffer_rules(db: AsyncSession, org_id: UUID) -> list[RentalBufferRule]:
    return list(
        (
            await db.execute(
                select(RentalBufferRule).where(
                    RentalBufferRule.organization_id == org_id
                )
            )
        )
        .scalars()
        .all()
    )


async def _blocking_bookings(
    db: AsyncSession,
    org_id: UUID,
    item_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
) -> list[dict]:
    """The active bookings a block of this window would take the asset from."""
    # A block on one day can take the last unit a model line promised for the
    # whole week, so the world covers every booking the block's window touches.
    world = await load_world(db, org_id, starts_at, ends_at, cover_bookings=True)
    asset = world.assets_by_id.get(item_id)
    if asset is None:
        return []
    conflicts: list[dict] = []
    for displaced in displaced_bookings(world, item_id, starts_at, ends_at):
        booking = displaced.booking
        if displaced.unit is not None:
            before, _after = world.buffer_for(asset)
        else:
            before, _after = world.buffer_for_model(asset.model or '')
        conflicts.append(
            {
                'booking_id': str(booking.id),
                'borrower_name': booking.borrower_name,
                'starts_at': booking.starts_at.isoformat(),
                'ends_at': booking.ends_at.isoformat(),
                'item_id': str(item_id),
                'item_name': asset.name,
                'suggested_until': (
                    booking.starts_at - timedelta(hours=before)
                ).isoformat(),
            }
        )
    return conflicts


async def _journal_block(
    db: AsyncSession,
    block: RentalBlock,
    action: AuditAction,
    user_id: UUID | None,
) -> None:
    await core_api.audit_log.log_action_async(
        db,
        organization_id=block.organization_id,
        user_id=user_id,
        action=action,
        target_type=AuditTargetType.RENTAL_BLOCK,
        target_id=block.id,
        snapshot={
            'item_id': str(block.item_id),
            'starts_at': block.starts_at.isoformat(),
            'ends_at': block.ends_at.isoformat(),
            'reason': block.reason,
            'source': block.source,
        },
    )


def block_schema(
    block: RentalBlock, assets: dict[UUID, EquipmentAssetDTO]
) -> BlockSchema:
    asset = assets.get(block.item_id)
    return BlockSchema(
        id=block.id,
        item_id=block.item_id,
        item_name=asset.name if asset is not None else '',
        model=asset.model if asset is not None else None,
        starts_at=block.starts_at,
        ends_at=block.ends_at,
        reason=block.reason,
        source=block.source,  # type: ignore[arg-type]
        booking_id=block.booking_id,
        borrower_name=None,
        created_at=block.created_at,
    )


async def list_blocks(
    db: AsyncSession,
    org_id: UUID,
    *,
    item_id: UUID | None = None,
    active_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[BlockSchema], int]:
    stmt = select(RentalBlock).where(RentalBlock.organization_id == org_id)
    if item_id is not None:
        stmt = stmt.where(RentalBlock.item_id == item_id)
    if active_only:
        now = _now()
        stmt = stmt.where(RentalBlock.starts_at <= now, RentalBlock.ends_at > now)
    stmt = stmt.order_by(RentalBlock.ends_at)
    blocks, total = await paginate_async(db, stmt, limit=limit, offset=offset)
    assets = await _assets_map(db, org_id)
    return [block_schema(block, assets) for block in blocks], total


async def create_block(
    db: AsyncSession, org_id: UUID, data: BlockCreate, user_id: UUID
) -> BlockSchema:
    assets = await _assets_map(db, org_id)
    if data.item_id not in assets:
        raise ServiceRejectionError('rental_asset_not_bookable')
    await _lock_asset_and_model(db, org_id, assets[data.item_id])
    conflicts = await _blocking_bookings(
        db, org_id, data.item_id, data.starts_at, data.ends_at
    )
    if conflicts:
        raise RentalConflictError(
            'rental_block_over_booking',
            code='RENTAL_BLOCK_OVER_BOOKING',
            details={'conflicts': conflicts},
        )
    block = RentalBlock(
        organization_id=org_id,
        item_id=data.item_id,
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        reason=data.reason.strip(),
        source='MANUAL',
        created_by=user_id,
    )
    db.add(block)
    await db.flush()
    await _journal_block(db, block, AuditAction.CREATE, user_id)
    return block_schema(block, assets)


async def _require_block(db: AsyncSession, org_id: UUID, block_id: UUID) -> RentalBlock:
    block = (
        (
            await db.execute(
                select(RentalBlock).where(
                    RentalBlock.id == block_id,
                    RentalBlock.organization_id == org_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if block is None:
        raise NotFoundException('rental_block', get_current_lang())
    return block


async def update_block(
    db: AsyncSession,
    org_id: UUID,
    block_id: UUID,
    data: BlockUpdate,
    user_id: UUID,
) -> BlockSchema:
    block = await _require_block(db, org_id, block_id)
    asset = (await _assets_map(db, org_id)).get(block.item_id)
    if asset is not None:
        await _lock_asset_and_model(db, org_id, asset)
    else:
        await acquire_advisory_lock(db, f'rentals:item:{org_id}:{block.item_id}')
    conflicts = await _blocking_bookings(
        db, org_id, block.item_id, data.starts_at, data.ends_at
    )
    if conflicts:
        raise RentalConflictError(
            'rental_block_over_booking',
            code='RENTAL_BLOCK_OVER_BOOKING',
            details={'conflicts': conflicts},
        )
    block.starts_at = data.starts_at
    block.ends_at = data.ends_at
    block.reason = data.reason.strip()
    await db.flush()
    await _journal_block(db, block, AuditAction.UPDATE, user_id)
    return block_schema(block, await _assets_map(db, org_id))


async def delete_block(
    db: AsyncSession, org_id: UUID, block_id: UUID, user_id: UUID
) -> None:
    block = await _require_block(db, org_id, block_id)
    await db.delete(block)
    await db.flush()
    await _journal_block(db, block, AuditAction.HARD_DELETE, user_id)


async def list_buffer_rules(db: AsyncSession, org_id: UUID) -> list[BufferRuleSchema]:
    rules = await _buffer_rules(db, org_id)
    categories = {
        category.id: category
        for category in await core_api.categories.list_async(db, org_id)
    }
    return [
        BufferRuleSchema(
            id=rule.id,
            model=rule.model,
            category_id=rule.category_id,
            category_code=(
                categories[rule.category_id].code
                if rule.category_id in categories
                else None
            ),
            category_name=(
                categories[rule.category_id].name
                if rule.category_id in categories
                else None
            ),
            hours_before=rule.hours_before,
            hours_after=rule.hours_after,
        )
        for rule in rules
    ]


async def set_buffer_rule(
    db: AsyncSession, org_id: UUID, data: BufferRuleIn, user_id: UUID
) -> BufferRuleSchema:
    if data.category_id is not None:
        categories = await core_api.categories.list_async(db, org_id)
        if all(category.id != data.category_id for category in categories):
            raise ServiceRejectionError('category_not_found')
    await acquire_advisory_lock(db, f'rentals:buffer:{org_id}')
    stmt = select(RentalBufferRule).where(RentalBufferRule.organization_id == org_id)
    if data.model is not None:
        stmt = stmt.where(RentalBufferRule.model == data.model)
    else:
        stmt = stmt.where(RentalBufferRule.category_id == data.category_id)
    rule = (await db.execute(stmt)).scalars().first()
    if rule is None:
        rule = RentalBufferRule(
            organization_id=org_id,
            model=data.model,
            category_id=data.category_id,
            hours_before=data.hours_before,
            hours_after=data.hours_after,
        )
        db.add(rule)
    else:
        rule.hours_before = data.hours_before
        rule.hours_after = data.hours_after
    await db.flush()
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.RENTAL_BUFFER_RULE,
        target_id=rule.id,
        snapshot={
            'model': rule.model,
            'category_id': str(rule.category_id) if rule.category_id else None,
            'hours_before': rule.hours_before,
            'hours_after': rule.hours_after,
        },
    )
    category_map = {
        category.id: category
        for category in await core_api.categories.list_async(db, org_id)
    }
    return BufferRuleSchema(
        id=rule.id,
        model=rule.model,
        category_id=rule.category_id,
        category_code=(
            category_map[rule.category_id].code
            if rule.category_id in category_map
            else None
        ),
        category_name=(
            category_map[rule.category_id].name
            if rule.category_id in category_map
            else None
        ),
        hours_before=rule.hours_before,
        hours_after=rule.hours_after,
    )


async def delete_buffer_rule(
    db: AsyncSession, org_id: UUID, rule_id: UUID, user_id: UUID
) -> None:
    rule = (
        (
            await db.execute(
                select(RentalBufferRule).where(
                    RentalBufferRule.id == rule_id,
                    RentalBufferRule.organization_id == org_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if rule is None:
        raise NotFoundException('rental_buffer_rule', get_current_lang())
    await db.delete(rule)
    await db.flush()
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.HARD_DELETE,
        target_type=AuditTargetType.RENTAL_BUFFER_RULE,
        target_id=rule.id,
        snapshot={'model': rule.model},
    )
