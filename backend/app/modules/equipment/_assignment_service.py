from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.contracts import (
    AuditAction,
    AuditTargetType,
    ItemUpdateDTO,
    UserContextDTO,
)
from app.core.db_utils import paginate_async
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    ServiceRejectionError,
    rejection_code,
)
from app.core.logging import get_logger
from app.i18n.service import get_current_lang, get_error_message

from ._approval_checkout import ensure_approval_covers_checkout
from ._org_day import pin_org_day_end
from ._unit_identity import audit_identity
from .bulk_service import CHECKOUT_REFUSALS, row_error
from .models import EquipmentAssignment
from .schemas import AssignmentCheckin, AssignmentCreate, AssignmentSchema
from .services import (
    _get_assignment_or_404,
    _log_item_history,
    _to_assignment_schema,
    _update_equipment_status,
)

logger = get_logger(__name__)


async def checkout(
    db: AsyncSession,
    org_id: UUID,
    data: AssignmentCreate,
    user_id: UUID,
) -> AssignmentSchema:
    from app.core.public_api import core_api

    lang = get_current_lang()

    # An assignment hands the asset to a person or deploys it to a place, and
    # it has to be one of the two: an assignment naming neither answers
    # nobody's question about where the asset went. The rule used to be split
    # in half and written down in neither half -- the form validated one
    # field or the other by mode, the schema demanded the name
    # unconditionally -- so the location mode posted a body its own schema
    # refused, and no deployment to a location ever became a record.
    person = bool(data.assigned_to_name.strip() or data.assignee_partner_id)
    place = data.checkout_location_id is not None
    if person == place or (place and data.assigned_to_email):
        raise ServiceRejectionError('equipment_assignment_needs_person_or_location')

    item = await core_api.items.get_async(db, org_id, data.item_id)
    if not item:
        raise NotFoundException('item', lang)

    equipment_ns = (item.meta_data or {}).get('equipment', {})
    refusal = CHECKOUT_REFUSALS.get(equipment_ns.get('equipment_status'))
    if refusal is not None:
        raise ConflictException(
            code=rejection_code(refusal), message=get_error_message(refusal, lang)
        )

    result = await db.execute(
        select(EquipmentAssignment)
        .with_for_update()
        .where(
            EquipmentAssignment.item_id == data.item_id,
            EquipmentAssignment.organization_id == org_id,
            EquipmentAssignment.checked_in_at.is_(None),
        )
    )
    active = result.scalars().first()
    if active:
        raise ConflictException(
            code='ASSIGNMENT_ALREADY_ACTIVE',
            message=get_error_message('equipment_assignment_already_active', lang),
        )
    # Approvals gate — only invoked when the org has the approvals module
    # enabled (so deployments without approvals rows continue to pass).
    if await core_api.organizations.is_module_enabled_async(db, org_id, 'approvals'):
        from app.modules.approvals.approvals_api import approvals_api

        # The workflow names whose checkouts it holds; somebody it does not
        # name checks out without an approval, and spends nobody's.
        if not await approvals_api.requester_exempt(
            db, org_id, 'equipment_checkout', user_id
        ):
            await approvals_api.check_and_block(
                db, org_id, 'equipment_checkout', data.item_id
            )
            # And it buys the checkout it was asked for: a hand-out to
            # somebody else needs a request of its own.
            await ensure_approval_covers_checkout(
                db,
                org_id,
                data.item_id,
                assigned_to_name=data.assigned_to_name,
                assignee_partner_id=data.assignee_partner_id,
                checkout_location_id=data.checkout_location_id,
            )
            # One approval buys one checkout. Spend it here, so the next
            # checkout of this asset needs a fresh request; a later refusal in
            # this same transaction rolls the spend back with everything else
            # it wrote.
            await approvals_api.consume_approval(
                db, org_id, 'equipment_checkout', data.item_id, user_id
            )

    # Validate that an explicitly-supplied ``checkout_location_id``
    # belongs to the current organization. Without this guard a malicious
    # caller could create an assignment pointing at any storage UUID in the
    # system; the FK alone is not tenant-scoped.
    if data.checkout_location_id is not None:
        loc = await core_api.locations.get_async(db, org_id, data.checkout_location_id)
        if not loc:
            raise ServiceRejectionError('storage_not_found')

    # The field beside it, under the same rule and for the same reason. It
    # went unguarded long enough for the two lines to sit four apart with
    # opposite behaviour.
    assigned_to_name = data.assigned_to_name
    if data.assignee_partner_id is not None:
        partner = await core_api.partners.get_async(
            db, org_id, data.assignee_partner_id
        )
        if not partner:
            raise ServiceRejectionError('partner_not_found')
        # A bare partner id names the partner itself, as the batch issue
        # does: the protocol, the history and the journal read the name, and
        # without it they printed an empty receiver for a person the
        # Assignments tab could name.
        if not assigned_to_name.strip():
            assigned_to_name = partner.name

    # The expected return is a day, not a moment: the form sends an instant
    # inside the organization's day and the service pins the end of the day
    # it reads there, so every reader — and the overdue check — sees the day
    # the form said, whatever clock the reader's browser runs (review 2026-09-23).
    expected_return_at = data.expected_return_at
    if expected_return_at is not None:
        tz = await core_api.organizations.timezone_async(db, org_id)
        expected_return_at = pin_org_day_end(expected_return_at, tz)

    assignment = EquipmentAssignment(
        organization_id=org_id,
        item_id=data.item_id,
        assignee_partner_id=data.assignee_partner_id,
        assigned_to_name=assigned_to_name,
        # emails are case-insensitive (RFC 5321) — store them
        # lowercase so "My assets" matching stays exact on one form.
        assigned_to_email=(
            data.assigned_to_email.lower() if data.assigned_to_email else None
        ),
        expected_return_at=expected_return_at,
        checkout_notes=data.checkout_notes,
        checkout_location_id=data.checkout_location_id,
        checked_out_by=user_id,
    )
    db.add(assignment)

    await _update_equipment_status(db, data.item_id, org_id, 'DEPLOYED')
    await _log_item_history(
        db,
        data.item_id,
        org_id,
        user_id,
        'CHECKOUT',
        {
            'assigned_to': assigned_to_name,
            'checkout_location_id': (
                str(data.checkout_location_id)
                if data.checkout_location_id is not None
                else None
            ),
        },
    )

    # And the organization journal. "Who has the laptop" is the central
    # material responsibility in asset management, and the screen that
    # answers "what happened in this organization" could not answer it: this
    # path wrote the item's own history and stopped there.
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.EQUIPMENT_ASSIGNMENT,
        target_id=assignment.id,
        snapshot={
            **audit_identity(item),
            'before': {'assigned_to': None},
            'after': {
                'assigned_to': assigned_to_name,
                'expected_return_at': (
                    expected_return_at.isoformat()
                    if expected_return_at is not None
                    else None
                ),
            },
        },
    )

    await db.flush()
    await db.refresh(assignment)

    from app.core.contracts.events import EquipmentCheckoutPayload
    from app.core.events import emit_safe

    from .events import EquipmentEvent

    await emit_safe(
        EquipmentEvent.CHECKOUT,
        EquipmentCheckoutPayload(
            organization_id=str(org_id),
            assignment_id=str(assignment.id),
            item_id=str(item.id),
            item_name=item.name,
            assigned_to_name=assigned_to_name,
            user_id=str(user_id),
        ),
        label='[equipment] CHECKOUT',
    )

    return _to_assignment_schema(assignment)


async def checkin(
    db: AsyncSession,
    org_id: UUID,
    assignment_id: UUID,
    data: AssignmentCheckin,
    user_id: UUID,
) -> AssignmentSchema:
    from app.core.public_api import core_api

    from ._maintenance_service import SERVICE_CONDITIONS, open_service_case

    lang = get_current_lang()

    assignment = await _get_assignment_or_404(db, assignment_id, org_id)

    if assignment.checked_in_at is not None:
        raise ConflictException(
            code='ASSIGNMENT_ALREADY_CHECKED_IN',
            message=get_error_message('equipment_assignment_already_checked_in', lang),
        )

    # Refused before anything is written: a return to a place this
    # organization does not have must not half-happen.
    if data.return_location_id is not None and not await core_api.locations.get_async(
        db, org_id, data.return_location_id
    ):
        raise ServiceRejectionError('storage_not_found')

    now = datetime.now(UTC)
    assignment.checked_in_at = now
    assignment.checked_in_by = user_id
    assignment.checkin_notes = data.checkin_notes
    assignment.checkin_condition = data.checkin_condition

    if data.checkin_condition in SERVICE_CONDITIONS:
        new_status = 'MAINTENANCE'
    else:
        new_status = 'AVAILABLE'

    await _update_equipment_status(db, assignment.item_id, org_id, new_status)
    if data.return_location_id is not None:
        await _return_to(
            db, org_id, assignment.item_id, data.return_location_id, user_id
        )
    await _log_item_history(
        db,
        assignment.item_id,
        org_id,
        user_id,
        'CHECKIN',
        {'condition': data.checkin_condition, 'new_status': new_status},
    )
    returned_item = await core_api.items.get_async(db, org_id, assignment.item_id)
    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=AuditTargetType.EQUIPMENT_ASSIGNMENT,
        target_id=assignment.id,
        snapshot={
            **audit_identity(returned_item),
            'before': {'assigned_to': assignment.assigned_to_name},
            'after': {'assigned_to': None, 'condition': data.checkin_condition},
        },
    )

    # The return that opens the workshop door files the reason with it: the
    # status says "in service", and the Maintenance tab must say why. Same
    # transaction as the status change -- a case that fails to write must not
    # leave an asset in a state nothing explains.
    if data.checkin_condition in SERVICE_CONDITIONS:
        await open_service_case(
            db,
            org_id,
            assignment.item_id,
            user_id,
            condition=data.checkin_condition,
            notes=data.checkin_notes,
            item=returned_item,
        )

    await db.flush()
    await db.refresh(assignment)

    item = await core_api.items.get_async(db, org_id, assignment.item_id)
    item_name = item.name if item else ''

    from app.core.contracts.events import EquipmentCheckinPayload
    from app.core.events import emit_safe

    from .events import EquipmentEvent

    await emit_safe(
        EquipmentEvent.CHECKIN,
        EquipmentCheckinPayload(
            organization_id=str(org_id),
            assignment_id=str(assignment.id),
            item_id=str(assignment.item_id),
            item_name=item_name,
            assigned_to_name=assignment.assigned_to_name,
            checkin_condition=data.checkin_condition,
            new_status=new_status,
            user_id=str(user_id),
        ),
        label='[equipment] CHECKIN',
    )

    return _to_assignment_schema(assignment)


async def _return_to(
    db: AsyncSession, org_id: UUID, item_id: UUID, location_id: UUID, user_id: UUID
) -> None:
    """Put the returned asset where the return says it went.

    The asset's location is its home: a checkout to a place shows the place
    while it lasts and never moves the asset in the record, so a return that
    lands at home writes nothing, and one that lands elsewhere moves it there
    through the core's item update (which keeps the move in its history).
    """
    from app.core.public_api import core_api

    item = await core_api.items.get_async(db, org_id, item_id)
    if item is None or item.location_id == location_id:
        return
    await core_api.items.update_async(
        db,
        org_id,
        item_id,
        ItemUpdateDTO(location_id=location_id),
        user=UserContextDTO(id=user_id, organization_id=org_id),
    )


async def bulk_checkin_items(
    db: AsyncSession,
    org_id: UUID,
    item_ids: list[UUID],
    condition: str | None,
    notes: str | None,
    user_id: UUID,
    return_location_id: UUID | None = None,
) -> tuple[int, list[dict[str, str]]]:
    """Bulk return: check in every selected asset with an active
    assignment, one condition for the whole batch.

    Items without an active assignment are reported as errors instead of
    failing the batch. Each checkin commits on its own, mirroring the
    single-checkin path.
    """
    checked_in = 0
    errors: list[dict[str, str]] = []

    for item_id in item_ids:
        assignment_result = await db.execute(
            select(EquipmentAssignment).where(
                EquipmentAssignment.organization_id == org_id,
                EquipmentAssignment.item_id == item_id,
                EquipmentAssignment.checked_in_at.is_(None),
            )
        )
        assignment = assignment_result.scalars().first()
        if assignment is None:
            # The client shows these verbatim when a batch is partly
            # rejected — keep them in the caller's language.
            errors.append(
                {
                    'item_id': str(item_id),
                    **row_error(ServiceRejectionError('assignment_not_found')),
                }
            )
            continue
        try:
            await checkin(
                db,
                org_id,
                assignment.id,
                AssignmentCheckin(
                    checkin_condition=condition,
                    checkin_notes=notes,
                    return_location_id=return_location_id,
                ),
                user_id,
            )
            checked_in += 1
        except (ConflictException, ValueError) as exc:
            errors.append({'item_id': str(item_id), **row_error(exc)})

    return checked_in, errors


async def list_active_assignments(
    db: AsyncSession,
    org_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AssignmentSchema], int]:
    stmt = (
        select(EquipmentAssignment)
        .options(
            selectinload(EquipmentAssignment.item),
            selectinload(EquipmentAssignment.assignee_partner),
            selectinload(EquipmentAssignment.checkout_location),
        )
        .where(
            EquipmentAssignment.organization_id == org_id,
            EquipmentAssignment.checked_in_at.is_(None),
        )
        .order_by(EquipmentAssignment.checked_out_at.desc())
    )
    rows, total = await paginate_async(db, stmt, limit=limit, offset=offset)
    return [_to_assignment_schema(a) for a in rows], total


async def _operator_names(
    db: AsyncSession, org_id: UUID, assignments: list[EquipmentAssignment]
) -> dict[UUID, str]:
    """Batch-resolve the accounts behind ``checked_out_by`` / ``checked_in_by``.

    A timeline entry used to name only the person the asset was with, so a
    return an administrator checked off read as if the holder had carried
    the asset back. One IN-query for every operator id on the page; a user
    the org no longer knows (deleted, moved) simply stays unnamed.
    """
    from app.core.public_api import core_api

    ids = {
        uid for a in assignments for uid in (a.checked_out_by, a.checked_in_by) if uid
    }
    if not ids:
        return {}
    users = await core_api.users.get_by_ids_async(db, org_id, list(ids))
    return {u.id: u.full_name or u.email for u in users}


async def count_item_assignment_history(
    db: AsyncSession, org_id: UUID, item_id: UUID
) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(EquipmentAssignment)
            .where(
                EquipmentAssignment.organization_id == org_id,
                EquipmentAssignment.item_id == item_id,
            )
        )
    ) or 0


async def get_item_assignment_history(
    db: AsyncSession, org_id: UUID, item_id: UUID, limit: int = 50, offset: int = 0
) -> list[AssignmentSchema]:
    result = await db.execute(
        select(EquipmentAssignment)
        .options(
            selectinload(EquipmentAssignment.item),
            selectinload(EquipmentAssignment.assignee_partner),
            selectinload(EquipmentAssignment.checkout_location),
        )
        .where(
            EquipmentAssignment.organization_id == org_id,
            EquipmentAssignment.item_id == item_id,
        )
        .order_by(
            EquipmentAssignment.checked_out_at.desc(), EquipmentAssignment.id.desc()
        )
        .limit(limit)
        .offset(offset)
    )
    rows = list(result.scalars().all())
    names = await _operator_names(db, org_id, rows)
    return [_to_assignment_schema(a, names) for a in rows]
