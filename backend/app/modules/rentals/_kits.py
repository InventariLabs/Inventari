"""Kits: a named set of assets or models a team hands out together.

A kit is not a second stock register. The booking stores one ordinary line
per member, all carrying the kit's id and name, so availability, pickup and
return keep working on units; the kit row only says which lines belong
together and carries the code a scanner reads.
"""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.contracts import AuditAction, AuditTargetType
from app.core.db_utils import acquire_advisory_lock
from app.core.module_sdk import (
    NotFoundException,
    ServiceRejectionError,
    get_current_lang,
)
from app.core.public_api import core_api
from app.modules.equipment.equipment_api import EquipmentAssetDTO, equipment_api

from .models import RentalKit, RentalKitMember
from .schemas import (
    KitCreate,
    KitListRow,
    KitMemberSchema,
    KitSchema,
    KitUpdate,
)

JOURNAL_TARGET = AuditTargetType.RENTAL_KIT


def _code_for(kit_id: UUID) -> str:
    """What a scanner reads: short, upper case, prefixed like an asset tag."""
    return f'KIT-{kit_id.hex[:8].upper()}'


async def _assets(db: AsyncSession, org_id: UUID) -> dict[UUID, EquipmentAssetDTO]:
    assets = await equipment_api.list_bookable_assets_async(db, org_id)
    return {asset.id: asset for asset in assets}


def _member_schema(
    member: RentalKitMember, assets: dict[UUID, EquipmentAssetDTO]
) -> KitMemberSchema:
    asset = assets.get(member.item_id) if member.item_id is not None else None
    return KitMemberSchema(
        id=member.id,
        item_id=member.item_id,
        item_name=asset.name if asset is not None else None,
        model=member.model,
        quantity=member.quantity,
    )


def _kit_schema(kit: RentalKit, assets: dict[UUID, EquipmentAssetDTO]) -> KitSchema:
    return KitSchema(
        id=kit.id,
        name=kit.name,
        code=kit.code,
        note=kit.note,
        members=[_member_schema(member, assets) for member in kit.members],
        created_at=kit.created_at,
    )


def _summary(kit: RentalKit, assets: dict[UUID, EquipmentAssetDTO]) -> str:
    parts: list[str] = []
    for member in kit.members:
        if member.item_id is not None:
            asset = assets.get(member.item_id)
            parts.append(asset.name if asset is not None else '—')
        else:
            model = member.model or ''
            parts.append(
                f'{model} ×{member.quantity}' if member.quantity > 1 else model
            )
    return ', '.join(part for part in parts if part)


def _validate_members(data: KitCreate, assets: dict[UUID, EquipmentAssetDTO]) -> None:
    seen: set[UUID] = set()
    for member in data.members:
        if member.item_id is not None:
            if member.item_id not in assets:
                raise ServiceRejectionError('rental_asset_not_bookable')
            if member.item_id in seen:
                raise ServiceRejectionError('rental_kit_member_on_two_lines')
            seen.add(member.item_id)
            continue
        if not any(asset.model == member.model for asset in assets.values()):
            raise ServiceRejectionError('rental_model_not_in_fleet')


async def _load_kit(db: AsyncSession, org_id: UUID, kit_id: UUID) -> RentalKit | None:
    result = await db.execute(
        select(RentalKit)
        .options(selectinload(RentalKit.members))
        .where(RentalKit.id == kit_id, RentalKit.organization_id == org_id)
        .execution_options(populate_existing=True)
    )
    return result.scalars().first()


async def _journal(
    db: AsyncSession,
    kit: RentalKit,
    action: AuditAction,
    user_id: UUID | None,
) -> None:
    await core_api.audit_log.log_action_async(
        db,
        organization_id=kit.organization_id,
        user_id=user_id,
        action=action,
        target_type=JOURNAL_TARGET,
        target_id=kit.id,
        snapshot={
            'name': kit.name,
            'code': kit.code,
            'members': [
                {
                    'item_id': str(member.item_id) if member.item_id else None,
                    'model': member.model,
                    'quantity': member.quantity,
                }
                for member in kit.members
            ],
        },
    )


async def list_kits(db: AsyncSession, org_id: UUID) -> list[KitListRow]:
    kits = (
        (
            await db.execute(
                select(RentalKit)
                .options(selectinload(RentalKit.members))
                .where(RentalKit.organization_id == org_id)
                .order_by(RentalKit.name)
            )
        )
        .scalars()
        .all()
    )
    assets = await _assets(db, org_id)
    return [
        KitListRow(
            id=kit.id,
            name=kit.name,
            code=kit.code,
            member_count=len(kit.members),
            summary=_summary(kit, assets),
        )
        for kit in kits
    ]


async def kits_by_ids(
    db: AsyncSession, org_id: UUID, kit_ids: set[UUID]
) -> dict[UUID, RentalKit]:
    if not kit_ids:
        return {}
    kits = (
        (
            await db.execute(
                select(RentalKit)
                .options(selectinload(RentalKit.members))
                .where(
                    RentalKit.organization_id == org_id,
                    RentalKit.id.in_(kit_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    return {kit.id: kit for kit in kits}


async def kit_schema_by_id(db: AsyncSession, org_id: UUID, kit_id: UUID) -> KitSchema:
    kit = await _load_kit(db, org_id, kit_id)
    if kit is None:
        raise NotFoundException('rental_kit', get_current_lang())
    return _kit_schema(kit, await _assets(db, org_id))


async def create_kit(
    db: AsyncSession, org_id: UUID, data: KitCreate, user_id: UUID
) -> KitSchema:
    assets = await _assets(db, org_id)
    _validate_members(data, assets)
    await acquire_advisory_lock(db, f'rentals:kits:{org_id}')
    name = data.name.strip()
    if not name:
        raise ServiceRejectionError('rental_kit_needs_name')
    clash = (
        await db.execute(
            select(RentalKit.id).where(
                RentalKit.organization_id == org_id, RentalKit.name == name
            )
        )
    ).scalar()
    if clash is not None:
        raise ServiceRejectionError('rental_kit_name_taken')
    kit_id = uuid.uuid4()
    kit = RentalKit(
        id=kit_id,
        organization_id=org_id,
        name=name,
        code=_code_for(kit_id),
        note=(data.note or '').strip() or None,
    )
    db.add(kit)
    await db.flush()
    for member in data.members:
        db.add(
            RentalKitMember(
                organization_id=org_id,
                kit_id=kit.id,
                item_id=member.item_id,
                model=member.model,
                quantity=member.quantity,
            )
        )
    await db.flush()
    fresh = await _load_kit(db, org_id, kit.id)
    assert fresh is not None
    await _journal(db, fresh, AuditAction.CREATE, user_id)
    return _kit_schema(fresh, assets)


async def update_kit(
    db: AsyncSession, org_id: UUID, kit_id: UUID, data: KitUpdate, user_id: UUID
) -> KitSchema:
    assets = await _assets(db, org_id)
    _validate_members(data, assets)
    kit = await _load_kit(db, org_id, kit_id)
    if kit is None:
        raise NotFoundException('rental_kit', get_current_lang())
    await acquire_advisory_lock(db, f'rentals:kits:{org_id}')
    name = data.name.strip()
    if not name:
        raise ServiceRejectionError('rental_kit_needs_name')
    clash = (
        await db.execute(
            select(RentalKit.id).where(
                RentalKit.organization_id == org_id,
                RentalKit.name == name,
                RentalKit.id != kit.id,
            )
        )
    ).scalar()
    if clash is not None:
        raise ServiceRejectionError('rental_kit_name_taken')
    kit.name = name
    kit.note = (data.note or '').strip() or None
    for member in list(kit.members):
        await db.delete(member)
    await db.flush()
    for member_in in data.members:
        db.add(
            RentalKitMember(
                organization_id=org_id,
                kit_id=kit.id,
                item_id=member_in.item_id,
                model=member_in.model,
                quantity=member_in.quantity,
            )
        )
    await db.flush()
    fresh = await _load_kit(db, org_id, kit.id)
    assert fresh is not None
    await _journal(db, fresh, AuditAction.UPDATE, user_id)
    return _kit_schema(fresh, assets)


async def delete_kit(
    db: AsyncSession, org_id: UUID, kit_id: UUID, user_id: UUID
) -> None:
    kit = await _load_kit(db, org_id, kit_id)
    if kit is None:
        raise NotFoundException('rental_kit', get_current_lang())
    await db.delete(kit)
    await db.flush()
    await _journal(db, kit, AuditAction.HARD_DELETE, user_id)
