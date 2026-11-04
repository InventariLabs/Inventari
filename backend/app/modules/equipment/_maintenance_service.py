from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.contracts import AuditAction, AuditTargetType, UserContextDTO
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    ServiceRejectionError,
)
from app.core.logging import get_logger
from app.i18n import Language
from app.i18n.service import get_current_lang, get_error_message

from ._unit_identity import audit_identity
from .models import EquipmentAssignment, EquipmentMaintenanceLog
from .schemas import MaintenanceLogCreate, MaintenanceLogSchema, MaintenanceLogUpdate
from .services import (
    _get_log_or_404,
    _log_item_history,
    _to_maintenance_schema,
    _update_equipment_status,
)
from .status_machine import resolve_previous_status

logger = get_logger(__name__)

#: The conditions a return can carry that put the asset into service. One
#: tuple, because the status branch and the service case must agree on which
#: returns open a workshop door.
SERVICE_CONDITIONS: tuple[str, ...] = ('DAMAGED', 'NEEDS_REPAIR')

#: The title of the service case a damaged return opens. A maintenance row
#: is stored text read months later, so it keeps the language of the return
#: -- the same contract notification copy holds.
SERVICE_CASE_TITLE: dict[str, dict[str, str]] = {
    'NEEDS_REPAIR': {
        'en': 'Returned — needs repair',
        'pl': 'Zwrócony — wymaga naprawy',
        'de': 'Zurückgegeben — Reparatur nötig',
        'fr': 'Retourné — réparation nécessaire',
        'es': 'Devuelto — necesita reparación',
        'pt': 'Devolvido — precisa de reparo',
    },
    'DAMAGED': {
        'en': 'Returned damaged',
        'pl': 'Zwrócony uszkodzony',
        'de': 'Beschädigt zurückgegeben',
        'fr': 'Retourné endommagé',
        'es': 'Devuelto dañado',
        'pt': 'Devolvido danificado',
    },
}


def _log_snapshot(log: EquipmentMaintenanceLog, item: Any = None) -> dict[str, Any]:
    """What a maintenance entry looks like in the organization log.

    The asset it is about comes first, because "a repair was booked" is not
    an answer to anything -- the reader wants to know which machine keeps
    going back to the shop, and at what cost. A ``Decimal`` and a ``date``
    both go into a JSON column, so both are rendered here rather than left
    for the serializer to refuse -- the cost as its exact digits, because a
    float is a less precise copy of the money than the column it came from.

    *item* is passed in for a log row that has only just been added: the
    relationship is eagerly loaded on a queried row and empty on a pending
    one, and reaching for it there is a lazy load on an async session.

    ``item_name`` rides beside ``item_id`` the way every named reference
    does: the row is about a maintenance entry, so the asset reaches the
    page as a reference id, and an id alone sends the reader hunting for a
    laptop they cannot see on this screen.
    """
    the_item = item if item is not None else log.item
    return {
        **audit_identity(the_item),
        'item_id': str(log.item_id),
        'item_name': getattr(the_item, 'name', None),
        'maintenance_type': log.maintenance_type,
        'title': log.title,
        'cost': str(log.cost) if log.cost is not None else None,
        'currency': log.currency,
        'performed_at': log.performed_at.isoformat() if log.performed_at else None,
    }


async def _assert_partner_is_ours(
    db: AsyncSession, org_id: UUID, partner_id: UUID | None, lang: Language
) -> None:
    """A service partner is a reference to our own address book, or nothing.

    The foreign key is not tenant-scoped, so an id arriving in a payload
    could name a partner belonging to another organization. Nothing of
    theirs comes back out -- the screens simply show a name this
    organization cannot resolve, pointing at a row its owner may delete.
    """
    if partner_id is None:
        return
    from app.core.public_api import core_api

    if await core_api.partners.get_async(db, org_id, partner_id) is None:
        raise ServiceRejectionError('partner_not_found')


async def create_log(
    db: AsyncSession,
    org_id: UUID,
    data: MaintenanceLogCreate,
    user_id: UUID,
) -> MaintenanceLogSchema:
    from app.core.public_api import core_api

    lang = get_current_lang()
    item = await core_api.items.get_async(db, org_id, data.item_id)
    if not item:
        raise NotFoundException('item', lang)

    await _assert_partner_is_ours(db, org_id, data.service_partner_id, lang)

    log = EquipmentMaintenanceLog(
        organization_id=org_id,
        item_id=data.item_id,
        maintenance_type=data.maintenance_type,
        title=data.title,
        description=data.description,
        cost=data.cost,
        currency=data.currency,
        performed_at=data.performed_at,
        performed_by=data.performed_by,
        service_partner_id=data.service_partner_id,
        next_maintenance_at=data.next_maintenance_at,
        created_by=user_id,
    )
    db.add(log)

    await _log_item_history(
        db,
        data.item_id,
        org_id,
        user_id,
        'MAINTENANCE',
        {
            'type': data.maintenance_type,
            'title': data.title,
            'cost': float(data.cost) if data.cost else None,
        },
    )
    await db.flush()
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.EQUIPMENT_MAINTENANCE,
        target_id=log.id,
        snapshot=_log_snapshot(log, item),
    )
    await db.flush()
    await db.refresh(log)
    return _to_maintenance_schema(log)


async def open_service_case(
    db: AsyncSession,
    org_id: UUID,
    item_id: UUID,
    user_id: UUID,
    *,
    condition: str,
    notes: str | None = None,
    item: Any = None,
) -> EquipmentMaintenanceLog:
    """File the reason a return put the asset into service.

    The check-in already moves the asset into MAINTENANCE; this writes the row
    that lets the Maintenance tab answer why, instead of "No maintenance
    records" on the very state it displays. The case opens as a REPAIR entry:
    what the condition names is work still to be done, not a repair performed,
    and the title says so. Cost and technician stay empty -- they arrive with
    the actual repair, filed against this case like any other entry.

    The caller owns the transaction (check-in commits); this only flushes. It
    does not touch the status either: the check-in has already decided it, and
    running the transition again here would write a second status history row
    for one act.
    """
    from app.core.public_api import core_api

    lang = get_current_lang()
    titles = SERVICE_CASE_TITLE.get(condition) or SERVICE_CASE_TITLE['NEEDS_REPAIR']
    title = titles.get(lang, titles['en'])

    log = EquipmentMaintenanceLog(
        organization_id=org_id,
        item_id=item_id,
        maintenance_type='REPAIR',
        title=title,
        description=notes,
        performed_at=await core_api.organizations.today_async(db, org_id),
        created_by=user_id,
    )
    db.add(log)
    await _log_item_history(
        db,
        item_id,
        org_id,
        user_id,
        'MAINTENANCE',
        {'type': 'REPAIR', 'title': title},
    )
    await db.flush()
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.CREATE,
        target_type=AuditTargetType.EQUIPMENT_MAINTENANCE,
        target_id=log.id,
        snapshot=_log_snapshot(log, item),
    )
    return log


async def _reject_if_assigned(
    db: AsyncSession, org_id: UUID, item_id: UUID, lang: Language
) -> None:
    """Raise 409 when *item_id* has an open assignment.

    Mirrors the delete interceptor's contract — same status code and error
    code — so every way out of the active register answers alike.
    """
    open_assignment = (
        await db.execute(
            select(EquipmentAssignment.id).where(
                EquipmentAssignment.organization_id == org_id,
                EquipmentAssignment.item_id == item_id,
                EquipmentAssignment.checked_in_at.is_(None),
            )
        )
    ).first()
    if open_assignment is not None:
        raise ConflictException(
            code='EQUIPMENT_ASSIGNED',
            message=get_error_message('equipment_still_assigned', lang),
        )


async def retire_item(
    db: AsyncSession,
    org_id: UUID,
    item_id: UUID,
    user: UserContextDTO,
    *,
    bulk: bool = False,
) -> None:
    """Retire an asset: set ``equipment_status=RETIRED``.

    Retiring keeps the asset in the register and in the dashboard's retired
    tile — archiving (soft delete) is a separate operation, ``archive_item``.

    An asset someone still holds cannot be retired: the status and the
    assignment table would then contradict each other (the asset would be
    counted as both checked out and retired), and the eventual check-in
    would reset the status to AVAILABLE, undoing the retirement silently.
    Archiving and deleting already refuse in the same situation.
    """
    from app.core.public_api import core_api

    lang = get_current_lang()
    item = await core_api.items.get_async(db, org_id, item_id)
    if not item:
        raise NotFoundException('item', lang)

    await _reject_if_assigned(db, org_id, item_id, lang)

    # The register records what was, not the model's word for nothing:
    # an asset that never carried a status transitions from null, so no
    # reader downstream ever meets the sentinel as if it were a state.
    old_status = resolve_previous_status(
        ((item.meta_data or {}).get('equipment', {})).get('equipment_status')
    )
    await _update_equipment_status(db, item_id, org_id, 'RETIRED')

    await _log_item_history(
        db,
        item_id,
        org_id,
        user.id,
        'STATUS_CHANGED',
        {'old_status': old_status, 'new_status': 'RETIRED'},
    )
    # Taking an asset out of service is a fact about the object, not a note
    # about it, so it belongs in the organization log beside the handover.
    # One row per asset even in a batch, and the flag says it was a batch —
    # the core settled that shape for bulk edits, and the log is not supposed
    # to depend on which button somebody pressed.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user.id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.EQUIPMENT_ASSET,
        target_id=item_id,
        snapshot={
            **audit_identity(item),
            'before': {'equipment_status': old_status},
            'after': {'equipment_status': 'RETIRED'},
        },
        meta_data={'bulk': True} if bulk else None,
    )
    await db.flush()


async def archive_item(
    db: AsyncSession,
    org_id: UUID,
    item_id: UUID,
    user: UserContextDTO,
) -> None:
    """Archive an asset: soft delete it out of the register."""
    from app.core.public_api import core_api

    lang = get_current_lang()
    deleted = await core_api.items.soft_delete_async(
        db, org_id, item_id, user, reason='ARCHIVED'
    )
    if not deleted:
        raise NotFoundException('item', lang)
    await db.flush()


async def count_item_logs(db: AsyncSession, org_id: UUID, item_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(EquipmentMaintenanceLog)
            .where(
                EquipmentMaintenanceLog.organization_id == org_id,
                EquipmentMaintenanceLog.item_id == item_id,
            )
        )
    ) or 0


async def get_item_logs(
    db: AsyncSession, org_id: UUID, item_id: UUID, limit: int = 50, offset: int = 0
) -> list[MaintenanceLogSchema]:
    from app.core.public_api import core_api

    lang = get_current_lang()
    # The Maintenance tab is part of the archived card — the log is the
    # record of what was done to the asset, which archiving does not undo.
    item = await core_api.items.get_any_async(db, org_id, item_id)
    if not item:
        raise NotFoundException('item', lang)
    result = await db.execute(
        select(EquipmentMaintenanceLog)
        .options(selectinload(EquipmentMaintenanceLog.item))
        .where(
            EquipmentMaintenanceLog.organization_id == org_id,
            EquipmentMaintenanceLog.item_id == item_id,
        )
        .order_by(
            EquipmentMaintenanceLog.performed_at.desc(),
            EquipmentMaintenanceLog.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    rows = result.scalars().all()
    return [_to_maintenance_schema(r) for r in rows]


async def update_log(
    db: AsyncSession,
    org_id: UUID,
    log_id: UUID,
    data: MaintenanceLogUpdate,
    user_id: UUID,
) -> MaintenanceLogSchema:
    from app.core.public_api import core_api

    log = await _get_log_or_404(db, log_id, org_id)
    await _assert_partner_is_ours(
        db, org_id, data.service_partner_id, get_current_lang()
    )
    before = _log_snapshot(log)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(log, field, value)
    await db.flush()
    after = _log_snapshot(log)
    moved = {key for key, value in after.items() if before[key] != value}
    if moved:
        await core_api.audit_log.log_action_async(
            db,
            organization_id=org_id,
            user_id=user_id,
            action=AuditAction.UPDATE,
            target_type=AuditTargetType.EQUIPMENT_MAINTENANCE,
            target_id=log.id,
            snapshot={
                **audit_identity(log.item),
                'before': {key: before[key] for key in moved},
                'after': {key: after[key] for key in moved},
            },
        )
    await db.flush()
    await db.refresh(log)
    return _to_maintenance_schema(log)


async def delete_log(
    db: AsyncSession, org_id: UUID, log_id: UUID, user_id: UUID
) -> None:
    log = await _get_log_or_404(db, log_id, org_id)

    from app.core.public_api import core_api

    # Before the row goes, not after: this is the only account of the repair
    # that will survive it, and the deletion rule exists because the record
    # that would have explained the act is the one being removed.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.HARD_DELETE,
        target_type=AuditTargetType.EQUIPMENT_MAINTENANCE,
        target_id=log.id,
        snapshot=_log_snapshot(log),
    )
    await db.delete(log)
    await db.flush()
