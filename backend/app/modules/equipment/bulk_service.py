from collections.abc import Awaitable, Callable
from typing import Any, NamedTuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts import AuditAction, AuditTargetType, UserContextDTO
from app.core.db_utils import acquire_advisory_lock
from app.core.exceptions import (
    ServiceRejectionError,
    is_reader_facing_value_error,
    refusal_code_of,
    rejection_code,
)
from app.core.interceptors import InterceptorError
from app.core.logging import get_logger
from app.i18n.service import get_current_lang, get_error_message

from ._unit_identity import audit_identity
from .models import EquipmentAssignment
from .status_machine import resolve_previous_status, validate_transition

logger = get_logger(__name__)

#: The statuses an asset cannot be handed out from, and the refusal each one
#: reads. A retired asset has left the lifecycle; one in maintenance is in the
#: workshop, and a checkout used to write DEPLOYED over it and leave its
#: repair entry open on an asset out on loan. The asset page offers Check Out
#: for neither, and the single and the batch checkout both ask this table, so
#: the two routes cannot drift apart again.
CHECKOUT_REFUSALS: dict[str, str] = {
    'RETIRED': 'equipment_cannot_checkout_retired',
    'MAINTENANCE': 'equipment_cannot_checkout_in_maintenance',
}


def row_error(exc: Exception) -> dict[str, str]:
    """The ``error`` a per-row result carries for a caught exception, and its ``code``.

    A refusal this codebase wrote (a plain or app-defined ``ValueError``, an
    interceptor veto, an envelope a nested call raised) is the reader's to
    see, with the code it was raised with when it has one — a client tells a
    checked-out asset from a missing one by the code, not the sentence.
    Anything else — a library's ``ValueError`` such as ``badly formed
    hexadecimal UUID string``, a database error carrying SQL — is logged with
    its traceback and answered with the translated generic sentence.
    """
    if isinstance(exc, HTTPException):
        detail = exc.detail
        text = (
            str(detail.get('message', '')) if isinstance(detail, dict) else str(detail)
        )
    elif isinstance(exc, (InterceptorError, PermissionError)) or (
        isinstance(exc, ValueError) and is_reader_facing_value_error(exc)
    ):
        text = str(exc)
    else:
        logger.error('bulk row failed', exc_info=exc)
        return {
            'error': get_error_message(
                'equipment_bulk_item_failed', get_current_lang()
            ),
            'code': rejection_code('equipment_bulk_item_failed'),
        }
    code = refusal_code_of(exc)
    return {'error': text} if code is None else {'error': text, 'code': code}


async def _log_asset_async(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    item: Any,
    *,
    target_type: AuditTargetType,
    target_id: UUID,
    snapshot: dict[str, Any],
    bulk: bool,
) -> None:
    """One row per asset, and a flag saying it came from a batch.

    The shape the core settled on for its own bulk edits: fifty items
    recategorised at once used to leave the same trace as nothing having
    happened, while the same edit made one at a time was fully recorded.
    The log is not supposed to depend on which button somebody pressed.
    """
    from app.core.public_api import core_api

    await core_api.audit_log.log_action_async(
        db,
        organization_id=org_id,
        user_id=user_id,
        action=AuditAction.UPDATE,
        target_type=target_type,
        target_id=target_id,
        snapshot={**audit_identity(item), **snapshot},
        meta_data={'bulk': True} if bulk else None,
    )


class _PendingEvent(NamedTuple):
    """A domain event a handler produced, waiting for the batch to commit.

    Emitting inside the loop would announce a checkout that the item's own
    savepoint could still roll back, and would announce it to subscribers
    before the row they would read exists.
    """

    event: Any
    payload: Any
    label: str


def _parse_uuid(value: str) -> UUID:
    """``UUID(value)``, with a malformed id refused as this row's, not as a library's."""
    try:
        return UUID(value)
    except (ValueError, TypeError):
        raise ServiceRejectionError('equipment_bulk_item_failed') from None


async def _active_assignment(
    db: AsyncSession, org_id: UUID, item_id: UUID
) -> EquipmentAssignment | None:
    """The open checkout for this asset, if there is one.

    Deliberately without ``with_for_update()``, which the single checkout
    takes. Two open assignments on one asset cannot happen either way: the
    partial unique index ``uq_eq_assignments_active_per_item`` (item_id,
    ``WHERE checked_in_at IS NULL``) is what actually forbids it, and it
    forbids it on both routes. Row locking would add nothing here, because
    the race being imagined is two *inserts* — and there is no row to lock
    when the asset is free, which is exactly when the race happens. The
    batch additionally serialises itself per asset with an advisory lock.
    """
    result = await db.scalars(
        select(EquipmentAssignment).where(
            EquipmentAssignment.item_id == item_id,
            EquipmentAssignment.organization_id == org_id,
            EquipmentAssignment.checked_in_at.is_(None),
        )
    )
    return result.first()


def _guard_status_assignment_consistency(
    target_status: str, active: EquipmentAssignment | None
) -> None:
    """Keep the two sources of truth in step.

    The "Checked Out" dashboard tile counts assignments; the asset list
    filters by equipment_status.
      - AVAILABLE while checked out would hide an open assignment.
      - DEPLOYED without a checkout would claim nobody holds it.
    """
    if target_status == 'AVAILABLE' and active is not None:
        raise ServiceRejectionError('equipment_still_assigned')
    if target_status == 'DEPLOYED' and active is None:
        raise ServiceRejectionError('equipment_deploy_requires_checkout')


async def _change_status(
    db: AsyncSession,
    org_id: UUID,
    item: Any,
    data: dict[str, Any],
    user_id: UUID,
    *,
    bulk: bool = False,
) -> _PendingEvent | None:
    from app.core.public_api import core_api

    item_id = item.id
    new_status = data.get('status')
    if new_status is None:
        raise ServiceRejectionError('field_required')
    # Same rule as the maintenance writers: the register and the journal
    # record null where there was no status, never the sentinel.
    old_status = resolve_previous_status(
        ((item.meta_data or {}).get('equipment', {})).get('equipment_status')
    )
    validate_transition(old_status, str(new_status))

    # Resolve any active checkout once — used both by the status/assignment
    # consistency guard and by the RETIRED auto-close below. MAINTENANCE
    # intentionally leaves the assignment open (asset returns to the same
    # assignee).
    target_status_str = str(new_status)
    active = await _active_assignment(db, org_id, item_id)
    _guard_status_assignment_consistency(target_status_str, active)

    # If the target status closes the asset's lifecycle (RETIRED),
    # auto-close any active assignment so we don't end up with a retired asset
    # still pointing at an open checkout.
    produced: _PendingEvent | None = None
    if target_status_str == 'RETIRED' and active is not None:
        from datetime import UTC, datetime

        from app.core.contracts.events import EquipmentCheckinPayload

        from .events import EquipmentEvent

        active.checked_in_at = datetime.now(UTC)
        active.checked_in_by = user_id
        await core_api.item_history.log_async(
            db,
            item_id=item_id,
            organization_id=org_id,
            user_id=user_id,
            action='CHECKIN',
            changes={
                'reason': 'auto_closed_by_retired_status',
                'assignment_id': str(active.id),
            },
        )
        # Closing a checkout here is a return, and the single check-in
        # announces every return. A subscriber heard about the one and
        # nothing about this one, so an asset could retire out of somebody's
        # hands unannounced. No condition travels with it: nothing was
        # inspected, and a default like "GOOD" would be a measurement nobody
        # took. Handed to the caller rather than emitted here — the commit is
        # the batch loop's, and a subscriber must not hear about a return
        # that a later savepoint rollback undid.
        produced = _PendingEvent(
            event=EquipmentEvent.CHECKIN,
            payload=EquipmentCheckinPayload(
                organization_id=str(org_id),
                assignment_id=str(active.id),
                item_id=str(item_id),
                item_name=item.name,
                assigned_to_name=active.assigned_to_name,
                new_status=target_status_str,
                user_id=str(user_id),
            ),
            label='[equipment] CHECKIN',
        )

    await core_api.items.update_meta_data_async(
        db,
        org_id,
        item_id,
        'equipment',
        {'equipment_status': new_status},
    )
    if old_status != new_status:
        await core_api.item_history.log_async(
            db,
            item_id=item_id,
            organization_id=org_id,
            user_id=user_id,
            action='STATUS_CHANGED',
            changes={
                'old_status': old_status,
                'new_status': new_status,
            },
        )
    await _log_asset_async(
        db,
        org_id,
        user_id,
        item,
        target_type=AuditTargetType.EQUIPMENT_ASSET,
        target_id=item_id,
        snapshot={
            'before': {'equipment_status': old_status},
            'after': {'equipment_status': new_status},
        },
        bulk=bulk,
    )
    return produced


async def _change_location(
    db: AsyncSession,
    org_id: UUID,
    item: Any,
    data: dict[str, Any],
    user_id: UUID,
    *,
    bulk: bool = False,
) -> None:
    # No entry of its own: the move goes through the core's item update,
    # which writes one — a second row would say the same thing twice.

    from app.core.contracts import ItemUpdateDTO
    from app.core.public_api import core_api

    location_id = data.get('location_id')
    if location_id:
        loc = await core_api.locations.get_async(db, org_id, _parse_uuid(location_id))
        if not loc:
            raise ServiceRejectionError('storage_not_found')

    await core_api.items.update_async(
        db,
        org_id,
        item.id,
        ItemUpdateDTO(location_id=_parse_uuid(location_id) if location_id else None),
        user=UserContextDTO(id=user_id, organization_id=org_id),
    )


async def _assign_to(
    db: AsyncSession,
    org_id: UUID,
    item: Any,
    data: dict[str, Any],
    user_id: UUID,
    *,
    bulk: bool = False,
) -> _PendingEvent | None:

    from app.core.public_api import core_api

    item_id = item.id
    partner_id = data.get('partner_id')
    name = data.get('assigned_to_name')
    email = data.get('assigned_to_email')

    # The single checkout refuses a retired asset by name, and the batch used
    # to hand one out: `_assign_to` wrote DEPLOYED over RETIRED and the asset
    # reappeared under "My equipment", with nothing in the record saying it
    # had ever left the lifecycle. An asset in maintenance went the same way.
    # Same table and key, so both routes refuse the same statuses in one
    # sentence.
    equipment_ns = (item.meta_data or {}).get('equipment', {})
    refusal = CHECKOUT_REFUSALS.get(equipment_ns.get('equipment_status'))
    if refusal is not None:
        raise ServiceRejectionError(refusal)

    partner = None
    if partner_id:
        partner = await core_api.partners.get_async(db, org_id, _parse_uuid(partner_id))
        if not partner:
            raise ServiceRejectionError('partner_not_found')
        # The dialog sends the person it showed; a bare partner_id (older
        # callers, the raw API) still names the partner itself.
        name = name or partner.name
    if not (name and str(name).strip()):
        raise ServiceRejectionError('equipment_assignment_needs_person_or_location')

    if await _active_assignment(db, org_id, item_id) is not None:
        raise ServiceRejectionError('equipment_assignment_already_active')

    # The approvals queue is not a property of the button that was pressed.
    # `ApprovalError` is a `ValueError`, which the batch loop already reports
    # per asset, so a blocked item is refused and the rest of the batch goes
    # through — the same shape as every other per-asset refusal here.
    if await core_api.organizations.is_module_enabled_async(db, org_id, 'approvals'):
        from app.modules.approvals.approvals_api import approvals_api

        # Somebody the workflow does not name is not held here either.
        if not await approvals_api.requester_exempt(
            db, org_id, 'equipment_checkout', user_id
        ):
            await approvals_api.check_and_block(
                db, org_id, 'equipment_checkout', item_id
            )
            # The approval covers the holder its request named, here as in
            # the single checkout.
            from ._approval_checkout import ensure_approval_covers_checkout

            await ensure_approval_covers_checkout(
                db,
                org_id,
                item_id,
                assigned_to_name=name,
                assignee_partner_id=_parse_uuid(partner_id) if partner_id else None,
            )
            # The batch spends the approval too; a batch-issued asset must
            # not leave its grant live for every later checkout any more than
            # a single one does.
            await approvals_api.consume_approval(
                db, org_id, 'equipment_checkout', item_id, user_id
            )

    assignment = EquipmentAssignment(
        organization_id=org_id,
        item_id=item_id,
        assignee_partner_id=_parse_uuid(partner_id) if partner_id else None,
        assigned_to_name=name,
        # emails are case-insensitive (RFC 5321) — stored lowercase, the
        # same rule the single checkout follows. "My assets" matches the
        # holder by this field; without it a batch-issued asset is invisible
        # to the person holding it and unreachable by attestation.
        assigned_to_email=_validated_assignee_email(email) if email else None,
        checked_out_by=user_id,
    )
    db.add(assignment)
    await core_api.items.update_meta_data_async(
        db,
        org_id,
        item_id,
        'equipment',
        {'equipment_status': 'DEPLOYED'},
    )
    await core_api.item_history.log_async(
        db,
        item_id=item_id,
        organization_id=org_id,
        user_id=user_id,
        action='CHECKOUT',
        changes={'assigned_to': name},
    )
    # The same fact the single checkout records, and the same target type:
    # who holds this thing. Reached by a different route, which is exactly
    # why it must not read differently.
    await db.flush()
    await _log_asset_async(
        db,
        org_id,
        user_id,
        item,
        target_type=AuditTargetType.EQUIPMENT_ASSIGNMENT,
        target_id=assignment.id,
        snapshot={
            'before': {'assigned_to': None},
            'after': {'assigned_to': name},
        },
        bulk=bulk,
    )

    from app.core.contracts.events import EquipmentCheckoutPayload

    from .events import EquipmentEvent

    # Handed to the caller rather than emitted here: a subscriber must not
    # hear about a checkout that a later savepoint rollback undid, and the
    # commit is the loop's. The single checkout emits after its own commit
    # for the same reason.
    return _PendingEvent(
        event=EquipmentEvent.CHECKOUT,
        payload=EquipmentCheckoutPayload(
            organization_id=str(org_id),
            assignment_id=str(assignment.id),
            item_id=str(item_id),
            item_name=item.name,
            assigned_to_name=str(name),
            user_id=str(user_id),
        ),
        label='[equipment] CHECKOUT',
    )


def _validated_assignee_email(raw: Any) -> str:
    """Validate the address the same way the single checkout's schema does.

    ``AssignmentCreate`` enforces ``EmailStr`` at its edge; the bulk request
    carries a free-form dict, so the same rule is applied here, one item at
    a time — attestation launches mail from this stored field.
    """
    from pydantic import EmailStr, TypeAdapter, ValidationError

    try:
        return str(TypeAdapter(EmailStr).validate_python(raw)).lower()
    except ValidationError as exc:
        raise ServiceRejectionError('invalid_email') from exc


_BULK_ACTIONS: dict[str, Callable[..., Awaitable[Any]]] = {
    'change_status': _change_status,
    'change_location': _change_location,
    'assign_to': _assign_to,
}


async def bulk_edit_items(
    db: AsyncSession,
    org_id: UUID,
    item_ids: list[UUID],
    action: str,
    data: dict[str, Any],
    user_id: UUID,
) -> tuple[int, list[dict[str, str]]]:
    """Apply *action* to each item; one item's refusal never stops the batch.

    The docstring used to promise that and the code did the opposite. A
    database error was caught per item and the loop went on, but the failed
    statement had already poisoned the transaction: every later ``execute``
    raised ``PendingRollbackError`` — itself a ``SQLAlchemyError``, so it fell
    into the same handler and looked like one more rejected row — and the
    final ``commit()`` then failed outright. One bad asset took down the whole
    batch with a 500, including every row that had gone through.

    A savepoint per item is what makes the promise true: a rollback undoes
    that one asset and leaves the transaction usable.
    """
    from app.core.public_api import core_api

    updated = 0
    errors: list[dict[str, str]] = []
    # The screen reuses this path for a single asset, and one asset edited on
    # its own is not a batch.
    bulk = len(item_ids) > 1

    handler = _BULK_ACTIONS.get(action)
    pending_events: list[_PendingEvent] = []

    for item_id in item_ids:
        try:
            async with db.begin_nested():
                await acquire_advisory_lock(db, f'equipment:bulk_edit:{item_id}')
                item = await core_api.items.get_async(db, org_id, item_id)
                if not item:
                    raise ServiceRejectionError('item_not_found')
                if handler is None:
                    raise ServiceRejectionError('unknown_bulk_action', action=action)

                produced = await handler(db, org_id, item, data, user_id, bulk=bulk)
            if produced is not None:
                pending_events.append(produced)
            updated += 1
        except (ValueError, SQLAlchemyError) as exc:
            errors.append({'item_id': str(item_id), **row_error(exc)})

    await db.flush()

    # A webhook subscribed to checkouts was hearing about assets handed out
    # one at a time and nothing about a batch of forty — the same event, the
    # same fact, silent on one of the two routes.
    from app.core.events import emit_safe

    for produced in pending_events:
        await emit_safe(produced.event, produced.payload, label=produced.label)

    return updated, errors
